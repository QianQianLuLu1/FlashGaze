# FlashGaze Agent 引导文档

> **用途**：本文件是 Qoder Agent 每次会话开始时自动读取的**跨会话项目上下文导航入口**。
> **维护约定**：任何对架构、依赖上限、CI 门禁、发布流程的修改，须同步更新对应作用域文档。
> **保护机制**：`.pre-commit-config.yaml` 与 `.github/workflows/ci.yml` 强制本文件存在且包含必要章节。

---

## 1. 项目概述

**FlashGaze**（瞬选灵眸）是 AI 辅助本地图片评分 CLI，采用 **CV + VLM 混合评分引擎**，
设计目标是让 AI Agent 能稳定调用（MCP Server + CLI + Web GUI 三入口）。

- **包名**：`flashgaze`
- **Python**：`>=3.10`（CI 矩阵：3.10 / 3.11 / 3.12 / 3.13）
- **许可**：MIT
- **当前版本**：见 `flashgaze/__init__.py::__version__`（唯一版本源）
- **仓库**：https://github.com/QianQianLuLu1/FlashGaze

---

## 2. 关键架构决策（摘要）

- **混合评分引擎**：CV 层（清晰度+曝光度）→ VLM 层（场景补偿）→ 混合评分器（最终分）
- **可选 CV 增强**：构图（实验性）/ BRISQUE 噪点 / 色彩丰富度 / 人像专项 / PHash 去重（全部默认关闭）
- **三入口一致性**：CLI + MCP Server + Web GUI，配置优先级链统一
- **清理安全护栏**：默认 dry-run；实际删除先同卷改名进 `.flashgaze_deleted/` 回收站并落 JSONL 审计清单（可 `flashgaze restore <清单>` 回滚），**绝不裸 unlink**（唯一例外 `--no-recycle`，须配 `--force`）；`--force` 必须配 dry_run 清单指纹 `--confirm-fingerprint`（两步确认）；95% 批量删除比例护栏（`--guard-min-sample`，默认 6，不可经配置关闭）；路径边界校验，绝不影响目录外文件

> 完整细节 → [docs/agent-context/architecture.md](docs/agent-context/architecture.md)

---

## 3. 已知陷阱（摘要）

| # | 陷阱 | 关键约束 |
|---|---|---|
| 3.1 | numpy 上限 `<2.3` | 双因：2.3 起 requires-python ≥3.11（生效项）；2.5+ stubs 用 PEP 695，解锁门槛是 mypy 目标 3.12+。改前重跑 extras job |
| 3.2 | opencv-python-headless | CI 无 OpenGL，禁止用非 headless 版 |
| 3.3 | PEP 695 语法禁用 | 用 TypeVar / TypeAlias / Generic 传统写法 |
| 3.4 | json5 容忍 VLM JSON | VLM 返回可能含围栏或尾随逗号 |
| 3.5 | mypy strict 全量 | 禁止新增 `# type: ignore` |
| 3.6 | pytest 默认口径 | 裸跑不含 e2e/benchmarks |
| 3.7 | coverage 引擎钉版 | 不钉时 12 腿矩阵分裂两个引擎（7.17.0 起 requires-python ≥3.11）；平台不可达行用 skipif 明写，不加 pragma |
| 3.8 | 静态门禁的平台盲区 | lint/typecheck 跑 ubuntu：`EXE001` 在 NTFS 恒不可见（`tools/*.py` 勿加 shebang）；mypy 按运行平台解析 typeshed，须 `--platform linux` 才看得见 CI 那一面。ruff/mypy/types-requests 已钉死单版本 |
| 3.9 | 测试桩的原语选择 | 挂起用 `Event().wait(30/120)` 而非 `sleep(1e9)`（py3.10 Win/macOS 立即抛错）；验 workers 必钉 `os.cpu_count`；只读目标语义分平台、须互为反向 skipif；PTY 合流须 `raw_decode`；权重归一化用 `math.fsum` |
| 3.10 | 排队好图被连带判死 | `future.running()` 进 call_queue 即为真 → 看门狗 deadline 从入队起算；真实池下非确定性。产品缺口已知未修，强断言由确定性假池用例钉住 |
| 3.11 | 可选依赖探测漏 `SystemExit` | `except ImportError` 挡不住 `face_recognition` import 期的 `quit()`（`SystemExit` 不是 `ImportError`）→ 收集阶段打死 session、覆盖率无数据、门禁假报「不达标」。**订正**：兜住 `SystemExit` 只解决「进程被打死」；上游那句 `print()` 仍会落在 CLI 子进程 stdout **头部**（进程活、rc=0、JSON 完整），严格 `json.loads(stdout)` 的调用方全数解析失败 → 探测块还须 `redirect_stdout/stderr` 静默吞掉 |
| 3.12 | 脚本用退出码表达级别，调用方把非零当失败 | `tools/extras_health.py` 用 `rc=2` 表达 critical，`extras-health.yml` 的 `Evaluate health` 步骤未兜非零码 → 步骤红 → 写锁/建 Issue/关 Issue 三处（无 `if: always()`）整批 skipped ⇒ **R4 熔断被自己的退出码第二次掐断**。须逐值放行（只容忍 2），不可写成 `\|\| true` 或步级 `continue-on-error`（那会把真崩溃也吞掉） |
| 3.13 | 模块级导入被 spawn worker 逐个重付 | worker 按 `module+qualname` 重导入 `hybrid_scorer` → 模块顶层导入 `deduplicator`/`portrait_engine`/`vlm_client` 等于给**每个 worker** 加一遍 imagededup/face_recognition/litellm 的 import，成本是「池代数 × worker 数」的乘法。只在装全 extras 的腿上存在（默认矩阵与开发机都看不见），实测让 extras macOS 腿 2091s 跑不完。判据用假包 + 落盘哨兵，不用计时；**「永不导入」也是绿**，须双向断言，且装配点构造必须保持无条件 |

> 完整细节 → [docs/agent-context/pitfalls.md](docs/agent-context/pitfalls.md)

---

## 4. 历史修复经验（摘要）

| # | 编号 | 主题 | 核心教训 |
|---|---|---|---|
| 4.1 | M-12 | 覆盖率门禁收紧 | `continue-on-error` 会静默放行，用契约测试锁定 |
| 4.2 | M-11 | 配置文件层三入口一致 | 多入口配置下沉到共享函数 |
| 4.3 | M-05 | BrisqueIntegrityError | 供应链信号靠专属日志标签 + 顺序敏感 except 分支辨识；退出码仍是 `IMAGE_ERROR(4)`，不另设专属码 |
| 4.4 | M-17 | pytest 默认口径校验 | 默认口径必须用 CI 守卫 |
| 4.5 | H-10/11/12 | MCP 高危审查 | MCP 安全护栏必须比 CLI 更严格 |
| 4.6 | 产物复核 | 12 腿覆盖率产物 | 只在 1/12 腿命中的行是测试稳定性信号而非噪声；产物只含 coverage.xml 时「腿为什么红」不可诊断 |
| 4.7 | 跨平台收口 | 8 类 CI 红灯 | 本地绿≠CI 绿：静态 job 跑 ubuntu，须 `mypy --platform linux` 自检；测试桩的原语选择本身就是跨平台契约；请求自带的前提（「版本漂移」）要在证据到位后复核并公开订正 |
| 4.8 | §4.7 复验 | 双向证据补录 | fixes.md §4.8 是 §4.7 的独立复验补录（未在本表单列教训）；「本地全绿」的前提是工具链与被钉版本同源 + 对照副本真的是未修复那一份 |
| 4.9 | extras 收口 | extras 腿 + 趋势图双红灯 | 「配了但没接线」第三例：`continue-on-error` 吞掉 INTERNALERROR → 门禁把「无数据」误报成「未达标」；action 入参名与引号 heredoc 里的 `$GITHUB_OUTPUT` 都只会在真跑时暴露。初判（覆盖率跌破 floor）被日志证伪并公开订正 |
| 4.10 | §4.9 连带后果 | extras 超时 + rc=2 断电 + stdout 污染 | 守卫修好后**三条新事实浮现**：macOS extras 腿实需 ~31 分钟（同一 628 条子集 ubuntu 97s vs macOS 824s = 8.5 倍，非卡死；**该外推已被 §4.11 证伪**）；`rc=2` 把刚接通的 R4 熔断再次掐死（写锁/建 Issue 三处 skipped，`extras-strict.lock` 至今 404）；上游 `print()` 污染 stdout 暴露 4 条 CLI 用例失败——兜异常不够，还得兜输出。口径冲突按方向② 收口（判定集 = 有逐模块 floor 的 3 模块；R5 必须同步收敛，否则锁永远解不掉）；`tools/extras_health.py` 的 R1-R5 此前零单测 |
| 4.11 | extras macOS 腿超时 | 上一轮「≈31 分钟」的线性外推**被 CI run 40174423841 证伪**（测试步独自跑到 2091s 仍未结束）。根因不是 macOS 天生慢（默认矩阵同平台只差 1.46 倍），而是 hybrid_scorer 的模块顶层导入让每个 spawn worker 重付 imagededup/face_recognition/litellm 的 import（见 §3.13）。改按需导入，**预算与全部阈值一条都没改**；探测时机随之从 import 期推迟到装配期，§3.11 的代价没消失只换了触发点。**CI 终验已过**（连续三轮全绿 40183752144 / 40186485850 / 40189037679）：macOS 腿由「881s 未完」「2091s 未完」两轮被杀变成三轮全部完成（测试步 375~505s、job 最差 882s = 14.7 分钟），而 **ubuntu 侧修复前后同为 302~404s 无可测变化**——因为 Linux 走 fork、worker 不重导入，这笔税只在 spawn 平台存在，ubuntu 不变反而是根因成立的旁证；40 分钟自此是**余量天花板（≥2.7 倍 headroom）而非实测需求**（三个 run 号必须同时挂在注释里，缺任一判红） |

> 完整细节 → [docs/agent-context/fixes.md](docs/agent-context/fixes.md)

---

## 5. 关键命令

```bash
make install       # pip install -r requirements-dev.txt + pre-commit install（不装 -e .、不装 extras）
make lint          # python -m ruff check .
make format        # python -m ruff format .（会改写文件）
make format-check  # python -m ruff format --check .（CI 口径，不改写）
make typecheck     # python -m mypy（strict，范围见 [tool.mypy] files；按当前机器平台解析 typeshed）
make typecheck-posix # python -m mypy --platform linux（复现 CI typecheck job 的 Linux 视角，见 §3.8）
make check         # lint + format-check + typecheck + typecheck-posix
make test          # python -m pytest tests/ -q（继承默认过滤，不含 e2e）
make test-all      # python -m pytest tests/ -q -o addopts=（清空默认过滤）
make verify        # check + test（不跑会改写文件的 format）
make hooks         # pre-commit run --all-files（安装 hook 用 make install）
make dist          # pip install build twine → python -m build → twine check
```

> 安装可编辑包与 extras 需自行执行 `pip install -e ".[mcp,gui,exif,heic]"`（`make install` 只装开发工具链）。
>
> **覆盖率不在 `make test`/`make verify` 里**：二者不带 `--cov`，`fail_under=80` 只在 CI 生效。
> 本地要收口须显式跑 `python -m pytest tests/ -q --cov=flashgaze --cov-report=term-missing`。

---

## 6. 关键文件路径

```
flashgaze/                  # 源码根目录
├── __init__.py             # 唯一版本源（__version__）
├── __main__.py             # python -m flashgaze 入口
├── defaults.py             # 默认配置 + FLASHGAZE_CONFIG_FILE
├── mcp_server.py           # MCP Server（5 个工具）
├── cli/                    # CLI 入口（parser.py 参数面 + entry.py 子命令 score/cleanup/restore + progress.py）
├── core/                   # 核心评分逻辑（cv_engine / vlm_client / hybrid_scorer / cleanup 等）
├── models/                 # 数据模型（options.py::ScoringOptions）
├── plugins/                # 插件发现器
├── utils/                  # 工具函数（atomic_write / config / image_io / logging / net_guard）
└── webui/                  # Web GUI（app.py 界面 + runner.py 执行层 + gallery.py；Gradio 4.21–6.x，完整实测钉 6.24.0）

tests/                      # 单元测试 + fixtures（e2e 默认排除）
├── test_coverage_gate_contract.py   # 门禁契约守卫（18 条，纯 stdlib，不 import yaml）
├── test_portrait_import_guard.py    # 可选依赖 import 期 quit() 的子进程回归用例（见 §3.11）
├── test_worker_import_budget.py     # spawn worker 冷启动不得加载重可选依赖（假包+落盘哨兵，见 §3.13）
└── test_extras_health_rules.py      # R1-R5 判定契约，子进程真实调用 tools/extras_health.py 并断言退出码（见 §3.12）
benchmarks/                 # 性能基准（pytest-benchmark，默认排除）
pyproject.toml              # 单一配置源（PEP 621）
.coveragerc / .coveragerc-extras  # 覆盖率门禁
.github/workflows/          # CI/CD（ci / security / release / extras-health / benchmark）
docs/agent-context/         # 作用域文档（architecture / pitfalls / fixes / release）
```

---

## 7. CI 门禁矩阵

| Job | 触发 | 阻塞 | 关键步骤 |
|---|---|---|---|
| `test` | push/PR | ✅ | 12 腿矩阵（3 OS × 4 Python），覆盖率 fail_under=80；每腿产出 `coverage-*`（只含 coverage.xml）+ `junit-*` 两个产物，并把通过/失败/错误写进 job summary |
| `typecheck` | push/PR | ✅ | mypy strict 全量（`files = flashgaze + tests + tools/bench`） |
| `lint` | push/PR | ✅ | ruff check + format --check |
| `agents-md-integrity` | push/PR | ✅ | `python -m tools.check_agents_md`：AGENTS.md 1-9 节齐全 **且** `docs/agent-context/` 四篇作用域文档存在（纯 stdlib，无需装依赖） |
| `extras` | push/PR | ✅ | 可选模块硬门槛（mcp_server 82 / webui.app 80 / xlsx_exporter 95）；step 6 带 `.coverage` **存在且非空**前置检查，把「无数据」与「未达标」在日志里分开（2026-10-24 前这 3 条下限从未在 CI 真实比对过；run 40107357212（2026-10-24）首次真实通过 ubuntu 腿）；`timeout-minutes: 40`（原 20 会在 58% 进度处被杀并派生出「无覆盖率数据」的假门禁红；据此外推的「~31 分钟」**已被 run 40174423841 证伪**——同一腿测试步跑到 2091s 仍未结束。40 是已观测下界之上的预算，真正的修法是消掉 worker 冷启动的可选依赖税，见 §3.13 / §4.11；修后实测 macOS 腿全程 661 / 681 / 882s、测试步 375~505s（run 40183752144、40186485850、40189037679 三轮全绿，最差 14.7 分钟），**ubuntu 侧 302~404s 修复前后无可测变化**（Linux fork、worker 不重导入——这反而是根因成立的旁证），**40 因此是余量天花板（最差一轮仍 ≥2.7 倍 headroom）而非实测需求**，注释须同时挂起点/证伪/实测三个 run 号）；逐腿产出 `coverage-extras-*` + `junit-extras-*` 两个产物（产物名必须带 `extras` 前缀，否则与 test job 同矩阵名重名报错） |
| `check-strict` | push/PR | ➡️ 前置 | 读 `.github/extras-strict.lock` sentinel，输出 `strict` 供 `extras` job 决定是否把总下限加严到 60 |
| `e2e` | push/PR | ✅ | Playwright Chromium + Firefox 双必选门禁 |
| `e2e-webkit` | 手动 dispatch 且勾选 `run_webkit` | ❌ 非门禁 | `continue-on-error: true`，默认不触发 |
| `audit` | PR/每日定时 | ✅ | pip-audit 依赖漏洞扫描 |
| `benchmark` | PR/nightly | ✅ | 性能回归门禁（mean ±15%） |
| `release` | 标签推送 | ✅ | preflight → build → verify → attest → publish |

> 另有独立 workflow `extras-health.yml`（定时 `collect` / `charts` / `weekly-report`），达到临界点时向仓库写 `.github/extras-strict.lock`，由上表 `check-strict` 消费。两点口径须记住：① `tools/extras_health.py` 用**退出码 2** 表达 critical，`Evaluate health` 步骤只容忍 rc∈{0,2}（写成 `|| true` 或步级 `continue-on-error` 会把真崩溃一起吞掉，见 §3.12）；② R1/R2/R4/R5 的判定集是 `JUDGED_MODULES`（= ci.yml 里带逐模块 `--fail-under` 的 3 个模块），`deduplicator` / `portrait_engine` 因走降级口径**只观测不判死**，代价与锁死方式见 `docs/extras-governance.md` §4。

**本地 pre-commit hooks**：`ruff-check` / `ruff-format` / `mypy` / `agents-md-exists`

四个 hook 均 `always_run: true` → **每次提交都跑**，与 CI 口径一致（`agents-md-exists` 上另配的 `files: ^AGENTS\.md$` 被 `always_run` 覆盖，是惰性配置，不要误读为「只在 AGENTS.md 变更时执行」）。

---

## 8. 发布流程语义（摘要）

- **唯一真实发布路径**：`git tag vx.y.z && git push origin vx.y.z`
- **手动触发**：恒为演练，不发布
- **发布认证**：PyPI Trusted Publishing（OIDC）
- **版本源**：`flashgaze/__init__.py::__version__`

> 完整细节 → [docs/agent-context/release.md](docs/agent-context/release.md)

---

## 9. 维护约定

1. **本文件是跨会话项目上下文的导航入口**：详细内容由 `docs/agent-context/` 作用域文档承载。
2. **保护机制**：`.pre-commit-config.yaml` 的 `agents-md-exists` hook 与 `.github/workflows/ci.yml` 的 `agents-md-integrity` job 强制本文件存在且包含必要章节（1-9 节）。
3. **与 Qoder Memories 的关系**：本文件是**项目级静态上下文**（每次会话自动注入），Qoder Memories 是**用户级可检索记忆**（通过 SearchMemory 查询）。两者互补，不替代。
4. **更新时机**：
   - 新增架构决策 → 更新 `docs/agent-context/architecture.md` + 本文件 §2 摘要
   - 发现新陷阱 → 更新 `docs/agent-context/pitfalls.md` + 本文件 §3 摘要
   - 重要修复（M-xx / H-xx）→ 更新 `docs/agent-context/fixes.md` + 本文件 §4 摘要
   - 新增 Makefile 目标 → 更新本文件 §5
   - 新增源码根目录 / 测试文件 → 更新本文件 §6
   - 新增 CI job / 修改门禁 → 更新本文件 §7
   - 修改发布流程 → 更新 `docs/agent-context/release.md` + 本文件 §8 摘要
5. **入库要求（易踩）**：`docs/agent-context/` 四篇作用域文档与 `tools/check_agents_md.py` **必须纳入版本跟踪**。作用域文档存在性检查是阻塞项，但只看磁盘：文件留在工作区时本地必绿，CI 在全新 checkout 上必红。提交前用 `git ls-files docs/agent-context tools/check_agents_md.py` 复核（应为 5 条）。
   - **反向情形**：`.qoder/rules/` 与 `.qoder/` 下其余内容被 `.gitignore` 忽略（`git ls-files .qoder` 为空），是**只对本机 Agent 生效的规则目录**。在其中写的口径同步**不会进入 `main`、CI 与其他开发者都看不到**——需要跨会话/跨人一致的约束必须写进本文件或 `docs/agent-context/`，不能只落在 `.qoder/`。

---

**最后更新**：2026-10-25（收口 `main @ 7288d7d` 的唯一红灯。**先说结论：其余 20 个 job 全绿**，CI run 40174423841 的 `cancelled` 只来自 `extras (macos-latest, py3.12)` 撞上 `timeout-minutes: 40`——该腿的测试步独自跑到 **2091s 仍未结束**（job 全程 2428s），`Coverage gate (hard floors)` 的 failure 是它的派生红，`coverage-extras-macos-*` / `junit-extras-macos-*` 两个产物因此再次未生成。**上一轮那条「macOS 腿实测需 ~31 分钟」被这一 run 证伪**，且错在方法不在算术：31 分钟是「20 分钟杀在 58% 进度」的线性外推，而 pytest 进度按用例条数走、耗时按用例种类分布，后半程集中了真进程池用例。根因不是 macOS 天生慢——同一条命令 ubuntu 测试步 404s、默认 12 腿矩阵的 ubuntu→macOS 只差 1.46 倍；差额来自 `hybrid_scorer` 在**模块顶层**导入 `deduplicator` / `portrait_engine` / `vlm_client`，而 spawn worker 按 `module+qualname` 重导入本模块，于是每个 worker 都重付一遍 `imagededup` / `face_recognition`(dlib) / `litellm` 的 import，成本乘在「池代数 × worker 数」上（`test_score_batch_is_deterministic_without_vlm` 一条就是 10 次 `score_batch` × 4 worker = 40 次 spawn）。旁证：同文件阶段 1 的 PHash 编码**早就是**函数内导入且有 `enable_dedup` 守卫、`tests/test_dedup.py` 还专门断言这一形态——仓库本来就有正确写法，只是被模块顶层导入整个抵消。**这条成本在结构上被依赖矩阵掩盖**：默认矩阵只装 `mcp,gui,exif,heic`、开发机装不上 dlib/imagededup，所以本地与 12 腿恒为 0 税、看不见。

**本轮改动（阈值/矩阵/预算一条未动）**：`hybrid_scorer.py` 改**按需导入**——`PortraitEngine` / `VLMClient` 的类型引用进 `if TYPE_CHECKING:`（`VLMClient` 全文件只有注解用途，真实构造点在 `core/factory.py`），运行时导入进函数体；`HybridScorer.__init__` 的两个可选引擎构造点**保持无条件**（它们是 extras 覆盖率里 `deduplicator`/`portrait_engine` 的真实来源，条件化会让数字静默下移）；worker 侧人像构造收进 `if enable_portrait:`，关闭时直接给 `PortraitResult(face_count=0)`，与 `PortraitEngine(enable=False).evaluate()` 的早返回逐字段相同。三个可选依赖的模块级探测块**一行未改**（§3.11 刚修的 `except (ImportError, SystemExit)` + `redirect_stdout/stderr` 原样留在原位）。**没有**用「抬预算」掩盖根因、**没有**撤 macOS 腿、**没有**缩小 extras 测试范围。新增 `tests/test_worker_import_budget.py` **4 条**（假包经 `PYTHONPATH` 前置注入 + 独立落盘哨兵作判据——不用计时、不依赖真实可选依赖，故 12 腿与 extras 双腿都是有效测量；含「直接 import 假包必然落哨兵」的非空洞性对照与「开启/装配时必须加载」的反向守卫，防止「拿删功能换时长」伪装成优化成功）+ `test_coverage_gate_contract.py` **17→18 条**（静态兜底只认第 0 列导入、函数体内缩进导入不误报，附反例）+ `test_hybrid_scorer.py` **1 条**进程内 `enable_portrait=True` 用例（`.coveragerc` 开了 `branch = true`，新 `if` 的真分支此前只有子进程走到、而子进程不计入覆盖率，会留 partial branch 缺口）。ci.yml 的 extras 注释公开订正那次被证伪的外推并绑定新 run 号，`EXTRAS_TIMEOUT_FALSIFIED_RUN` 进契约（删掉 run 号即判红，否则那条外推会重新被当成依据）。**双向证据**：修复前 4 条用例 **3 红 1 绿**（绿的必须是非空洞性对照，0.76s 跑完）、修复后全绿；四条反例逐条实跑判红并用备份还原（`git diff` 复核无残留）——A 把 `Deduplicator` 导回第 0 列（动态+静态两侧同时判红）、B 把人像改成永不加载（开启侧判红）、C 把装配点构造条件化（探针侧判红）、D 删掉证伪 run 号（契约判红）。**连带口径变化须与 §3.11 一起读**：可选依赖探测时机从「import 期」推迟到「装配 `HybridScorer` 时」，§3.11 的两个缺陷（`SystemExit` 穿透、探测期 `print()` 污染 stdout）**没有因此消失**，只是从「收集期打死 session」变成「运行期崩在评分入口」；`portrait_engine.py` 与 `tests/test_portrait_import_guard.py` 里描述崩溃链的注释已同步订正，不留「注释说谎」。§3 新增 3.13、§4 新增 4.11、§6 补一条测试路径、§7 `extras` 行订正 timeout 出处。**取证通道仍受限（本机实测）**：Actions job logs 免鉴权 403、artifact zip 401，只有 runs/jobs/steps 时序与产物清单可公开取——本轮的 2091s / 2428s / 404s 全部来自 step 时序差，不依赖日志。**CI 终验已通过（连续三轮全绿：run 40183752144、40186485850、40189037679，各 21 个 job、0 失败）**：① `extras (macos-latest, py3.12)` 测试步 **380 / 375 / 505s**、job 全程 **661 / 681 / 882s**（三轮全部正常跑完，最差 14.7 分钟），对比修复前「881s 未完」「2091s 未完」两轮均被杀；`Coverage gate` 真实通过；`coverage-extras-macos-*` / `junit-extras-macos-*` **首次真实生成**（产物 26→28 条）。**ubuntu 侧修复前后同为 302~404s、无可测变化——这恰是机理的正面证据**：Linux 默认 fork、worker 不重新导入本模块，这笔 import 税只在 spawn 平台（macOS/Windows）存在，所以正确的对照是「macOS 从两轮跑不完变成三轮全部完成」而不是「两平台都变快」（初稿写成「ubuntu 也顺带降到 302s」，是把跨运行噪声当因果，已订正）。macOS→ubuntu 由 ≥5.2 倍回到 **0.98~1.31 倍**，与默认矩阵 1.46 倍同带。**另一笔自己的账**：第一版只看 macOS 一轮 380s 就写「变成 ~377s 完成」，第三轮实测 505s、同轮 install 也从 252s 跳到 349s——同一条腿波动约 ±35%，所以这里只报完成性与区间、不报单点值。② `benchmark` job 同 SHA **success**，±15% 均值门禁未受影响。③ **预估 vs 实测如实记账**：预估「测试步 ~10 分钟」，实测 375~505s（6.3~8.4 分钟），预估偏保守；预估倍率「回落到 ~1.46 倍」，实测 0.98~1.31 倍，方向正确、幅度更优。据此把 `timeout-minutes: 40` 重新定性为**刻意留的余量天花板（最差一轮仍 ≥2.7 倍 headroom），不是实测需求**，注释与契约文案均要求「起点 40107357212 / 证伪 40174423841 / 实测 40183752144」三个 run 号同时在场、缺任一判红；**未**下调 40（下调省不了任何墙钟时间——最差一轮也只要 14.7 分钟——却把未来的用例增长重新变成超时分母，是净风险零收益）。**推论（尚未做）**：给 extras 加 Windows 腿会立刻重新暴露这笔税（Windows 同样 spawn），加 Linux 腿不会。**仍只剩一项需要真实执行确认**：承接上一轮的 extras-health 链路（rc 管道 + `charts` + `weekly-report`）首次真实执行，今晚 19:17 UTC 定时，与本条独立。**需你处理的仓库配置（未变）**：Codecov 每条腿仍报 `Token required - not valid tokenless upload` ⇒ `secrets.CODECOV_TOKEN` 缺失或失效，`fail_ci_if_error: false` 使其恒绿，`extras-ubuntu`/`extras-macos` 两个 flag 依旧零数据；属仓库设置项，不改代码绕过。逐条取证见 `docs/agent-context/fixes.md` §4.11）

**同日更早更新**：2026-10-25（收口 `main @ dcf8c59` 的三条连带问题。**先说结论：`dcf8c59` 的 import 守卫确实生效**——CI run 40107357212 的 `extras (ubuntu-latest, py3.12)` 首次带真实覆盖率数据转绿，82/80/95 三条逐模块下限第一次真实通过，21 个 job 里 20 个绿。数据一真实就浮现三件事：① **该 run 结论 `cancelled` 的唯一原因是 `extras (macos-latest, py3.12)` 撞 `timeout-minutes: 20`**——job 全程 20m28s、被 runner 在 20 分钟上限杀掉，当时 pytest 进度只到 58%；同一 628 条用例子集 ubuntu 97s vs macOS 824s（**8.5 倍**，默认矩阵该比值仅 1.46 倍），单条最慢 `test_score_batch_is_deterministic_without_vlm` 145.6s，成本集中在 macOS 的 `spawn` 进程池 + 3 核，**不是卡死而是预算错配**，外推整 job ≈31 分钟；`Coverage gate (hard floors)`（`if: always()`）随后报「无覆盖率数据」是超时的派生红。② **`extras-health` run 40134963461 红在 `Evaluate health`，根因是脚本自己的退出码**：`tools/extras_health.py` 用 `rc=2` 表达 critical，步骤未兜非零码 → `Publish sentinel state`/建 Issue/关 Issue 三处（无 `if: always()`）整批 skipped ⇒ `dcf8c59` 刚接通的 `$GITHUB_OUTPUT` **一次也没被消费**，`extras-strict.lock` 至今仍是 404。`decision.json` 实测 `critical` 的唯一来源是 R4 `portrait_engine 47.62% < 50`（history 为空 ⇒ R2/R3/R4-lag 不可能触发），即 governance §4 那颗「待排期」的口径冲突雷**如实引爆**。③ junit 里 **4 条 CLI 用例失败**的真因是 stdout 污染：上游 `face_recognition` 探测期 `print()` 落在子进程 stdout **头部**（进程活、rc=0、JSON 完整），严格 `json.loads(stdout)` 全数报 `Expecting value: line 1 column 1 (char 0)`；旁证是同一文件用容错 `_extract_json` 的 4 条 `TestPtyTerminal` 全绿、`tests/test_cli_e2e.py` 被 `pytestmark = e2e` 全程去选、默认 12 腿 0 失败（未装 face_recognition 走纯 ImportError 无 print）。**六处修复（阈值一条未改）**：`portrait_engine.py` 探测块加 `contextlib.redirect_stdout/stderr` 静默吞掉第三方输出（不投 logger——`set_verbose` 在 `cli/entry.py:58` 才生效、晚于模块级探测，WARNING 级默认输出又会在 `--json 2>&1` 合流时重新污染）；`test_portrait_import_guard.py` 非空洞性凭证换成独立落盘哨兵、断言方向翻为 `hint not in stdout`；`extras-health.yml` 步骤只放行 rc∈{0,2}、其它非零原样退出；`extras_health.py` 新增 `JUDGED_MODULES`（= ci.yml 带 `--fail-under` 的 3 模块）限定 R1/R2/R4，**R5 同步收敛**（否则 portrait 的降级口径会让锁一旦写上永远解不掉、自愈形同虚设），dedup/portrait 保留观测并在 Issue 表格逐行标注；ci.yml extras `timeout-minutes: 20→40`（注释绑定 run 号）+ 补 `--junitxml` 与 `junit-extras-*` 产物（名字必须带前缀，否则与 test job 同矩阵名重名报错），但**未**复制 test job 那 55 行摘要 heredoc——两处各一份迟早漂移，属 §4.6/§4.9 同族风险。新增 `tests/test_extras_health_rules.py` **7 条**（该脚本 R1-R5 此前**零单测**，用例按 CI 真实 coverage.xml 的行数构造、子进程真实调用并同时断言 decision 与退出码）+ `test_coverage_gate_contract.py` **14→17 条**（判定集↔floor 表双向相等、rc 管道三向反例、timeout 下限与 run 引用），各带内置反例。§3.11 订正 + 新增 §3.12、§4.10、§6 补一条测试路径、§7 `extras` 行与 extras-health 注补口径。**取证通道受限须记住**：Actions 的 job logs/annotations 免鉴权返回 403/404、artifact zip 返回 401，只有 runs/jobs/steps 时序与产物清单可公开取——日志与产物仍需人工下载。**仍只能 CI 终验**：macOS 40 分钟够不够（31 分钟是 58% 处的线性外推）、`charts` 与 `weekly-report` 在 collect 转绿后的**首次真实执行**（下一触发 2026-10-27 周一，往 Issue #11 发评论；该 Issue 已核实 open 带 `extras-health` 标签）。**方向② 的代价**：dedup/portrait 跌破 60% 甚至 50% 都不再自动告警/加锁，需人工看趋势图。**需你处理的仓库配置**：Codecov 每条腿都报 `Token required - not valid tokenless upload` ⇒ `secrets.CODECOV_TOKEN` 缺失或失效，`fail_ci_if_error: false` 使其恒绿，所以 `e837d50` 对齐好的 `extras-ubuntu`/`extras-macos` 两个 flag 至今**零数据**，§2 可视化防线第一层仍是死的；不改代码绕过。逐条取证见 `docs/agent-context/fixes.md` §4.10）

**前次更新**：2026-10-24（收口 `main @ 9659ad5` 的两个远端红灯 + 一条不红隐患。**初判已被证伪并公开订正**：先假设「extras 腿是 2026-09-06 冻结的逐模块下限 82/80/95 与当前真实覆盖率第一次对撞」，拿到 raw log 后证实根本没有覆盖率数据——`face_recognition` 在 import 期 `quit()` 抛 `SystemExit`（py3.12 venv 无 setuptools → `pkg_resources` 缺失），穿透了只兜 `ImportError` 的守卫，pytest 在收集阶段 `INTERNALERROR` exit 3，被 `continue-on-error` 吞掉，门禁于是 `No data to report.` exit 1，与「未达标」在日志里不可分辨（`coverage-extras-*` 产物跨最近 5 次 run 从未存在）。三处修复：① `portrait_engine.py` 探测守卫改 `except (ImportError, SystemExit)` + 新增 `tests/test_portrait_import_guard.py`（子进程注入「import 即 quit()」的假包，第二用例钉住 `SystemExit(None)` 退出码为 **0** 这一陷阱——它会吞掉 CLI 的 JSON 输出）；② `extras-health.yml` charts 步骤 `raw-data-file` → `output-file-path` 并删 `output-storage`（均非该 action 的入参，runner 原文已抓）；③ 同文件 `python - <<'PY'` 里的 `open("$GITHUB_OUTPUT")` 改 `os.environ[...]`（引号定界符不展开变量 → `steps.eval.outputs.*` 恒空 → R4 熔断加锁与建/关 Issue 四处步骤从未执行过一次）。新增 `tests/test_coverage_gate_contract.py` 两条守卫（12→14 条：benchmark 入参名、引号 heredoc 内的 `$GITHUB_OUTPUT`，各带内置反例；守卫落地时被自己的注释打回一次，顺带证明非恒真）；ci.yml `Coverage gate (hard floors)` 加 `.coverage` 存在性前置检查与 4 条命令标签，**阈值一条未改**、也未制造第二条红源。新增 §3.11 与 §4.9；§6 补两条测试文件路径；§7 `extras` 行补口径。**待排期的口径冲突**：extras-governance §2.1 接受 dedup/portrait 的降级路径数字（不设逐模块 floor），而 §4 的 R1/R4 按「任一模块」绝对线判——链路接通后 `portrait_engine` 44% 会直接触发 R4 critical 并真的往 `main` 写 `.github/extras-strict.lock` + 开 Issue（5 模块总本地 78% ≥ 抬升后的 60，不新增红灯，但锁与 Issue 是真实产物）。逐条取证与仍只能 CI 终验项见 `docs/agent-context/fixes.md` §4.9）

**更早更新**：2026-10-23（收口 run 39909374394 的 8 类 CI 红灯：两个静态 job（`ruff` 的 `EXE001` × 2、`mypy` 的 `_winapi.CreateJunction`——根因是 ubuntu 门禁 / Windows 开发机的**平台盲区**，**不是**最初判断的版本漂移；该前提已在拿到日志后证伪并公开订正）+ `test` 12 腿红 10 条的六类跨平台/跨版本用例问题（macOS 3 核把 workers 钳到 3、py3.10 上 `time.sleep(1e9)` 立即抛错而非挂起、POSIX 只读目标不挡 `os.replace`、PTY 合流使 JSON 尾部多出 INFO 行、真实池排队好图被同代 deadline 连带判死、3.10/3.11 权重末位与 3.12+ 不等）。新增 §3.8/§3.9/§3.10 与 §4.7；`tools/*.py` 去掉 shebang；`requirements-dev.txt` 钉死 `ruff==0.16.10`/`mypy==1.20.2`/`types-requests==2.33.0.20261006`；`Makefile` 增 `typecheck-posix` 并并入 `make check`；`tests/test_coverage_gate_contract.py` 由 11 条增至 12 条；§5 补「覆盖率门禁不在 `make test`/`make verify` 里」的口径提示。逐类取证与未本地验证项见 `docs/agent-context/fixes.md` §4.7）

**复核补充**：2026-10-23 对上述未提交改动做独立复验（工具链先对齐到钉版 `ruff 0.16.10`/`mypy 1.20.2`/
`types-requests 2.33.0.20261006`/`coverage 7.16.2`）。本地可证四类取得**修复前失效 + 修复后通过**双向证据：
在 `e837d50` 的 detached worktree 上逐字复现 `mypy --platform linux` 的 `CreateJunction` 报错（97:9，78 files）、
以 `os.cpu_count=lambda:3` 复现 5 条 `assert 3 == 4`、以同一合成 PTY 缓冲复现旧 `_extract_json` 的
`Extra data`、以真实 py3.11 复现权重 `0.39999999999999997`（并实测「只改一处归一化」得 `0.4000000000000001`
更偏）。反例：把 `_POOL_REBUILD_LIMIT` 归零后 `[5]` 用例判红且日志给出「重建代数(0)已耗尽」；
`_extract_json` 喂结构合法但非报告的 JSON 触发 `"summary" in data` 断言。本地全绿基线：`ruff check`/
`format --check`/两面 mypy/`tools.check_agents_md`/`1038 passed, 29 skipped, 38 deselected`。
**仍属 CI 终验**：ubuntu 的 `EXE001`（NTFS 无 exec 位语义，已实测同版 ruff 在本地带 shebang 也恒不报）、
POSIX 只读语义、真实 PTY（本机整类 skip）、py3.10 的 `Sleep`/`select`（本机无 3.10 解释器）、
macos-latest 真实核数与真实 spawn 池代际拆分。另订正 §9.5：`.qoder/` 不入库，其口径同步不可达 CI。

**更早更新**：2026-10-23（复核 12 腿覆盖率产物：无门禁失败，但定位到四类真实问题并修复——新增假池 `_FakeProc` + `__procs__` 使「terminate 未生效→升级 kill」由 1/12 腿计时偶然变为确定性覆盖；补 `atomic_write` 两处 OSError 兜底与 `image_io._is_junction` lstat 竞态用例（后者此前 12/12 腿未覆盖）；test job 逐腿产出 junit 与失败摘要（`coverage-*` 产物保持只含 coverage.xml）；extras 投递 Codecov 的 flag 名与 `codecov.yml` 声明对齐；`coverage[toml]` 钉死 7.16.2 消除 12 腿双引擎。§3.7 / §4.6 / §7 `test` 行与 `tests/test_coverage_gate_contract.py`（8→11 条）同步）
