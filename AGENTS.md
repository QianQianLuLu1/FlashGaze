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
| `extras` | push/PR | ✅ | 可选模块硬门槛（mcp_server 82 / webui.app 80 / xlsx_exporter 95） |
| `check-strict` | push/PR | ➡️ 前置 | 读 `.github/extras-strict.lock` sentinel，输出 `strict` 供 `extras` job 决定是否把总下限加严到 60 |
| `e2e` | push/PR | ✅ | Playwright Chromium + Firefox 双必选门禁 |
| `e2e-webkit` | 手动 dispatch 且勾选 `run_webkit` | ❌ 非门禁 | `continue-on-error: true`，默认不触发 |
| `audit` | PR/每日定时 | ✅ | pip-audit 依赖漏洞扫描 |
| `benchmark` | PR/nightly | ✅ | 性能回归门禁（mean ±15%） |
| `release` | 标签推送 | ✅ | preflight → build → verify → attest → publish |

> 另有独立 workflow `extras-health.yml`（定时 `collect` / `charts` / `weekly-report`），达到临界点时向仓库写 `.github/extras-strict.lock`，由上表 `check-strict` 消费。

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

**最后更新**：2026-10-23（收口 run 39909374394 的 8 类 CI 红灯：两个静态 job（`ruff` 的 `EXE001` × 2、`mypy` 的 `_winapi.CreateJunction`——根因是 ubuntu 门禁 / Windows 开发机的**平台盲区**，**不是**最初判断的版本漂移；该前提已在拿到日志后证伪并公开订正）+ `test` 12 腿红 10 条的六类跨平台/跨版本用例问题（macOS 3 核把 workers 钳到 3、py3.10 上 `time.sleep(1e9)` 立即抛错而非挂起、POSIX 只读目标不挡 `os.replace`、PTY 合流使 JSON 尾部多出 INFO 行、真实池排队好图被同代 deadline 连带判死、3.10/3.11 权重末位与 3.12+ 不等）。新增 §3.8/§3.9/§3.10 与 §4.7；`tools/*.py` 去掉 shebang；`requirements-dev.txt` 钉死 `ruff==0.16.10`/`mypy==1.20.2`/`types-requests==2.33.0.20261006`；`Makefile` 增 `typecheck-posix` 并并入 `make check`；`tests/test_coverage_gate_contract.py` 由 11 条增至 12 条；§5 补「覆盖率门禁不在 `make test`/`make verify` 里」的口径提示。逐类取证与未本地验证项见 `docs/agent-context/fixes.md` §4.7）

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

**上次更新**：2026-10-23（复核 12 腿覆盖率产物：无门禁失败，但定位到四类真实问题并修复——新增假池 `_FakeProc` + `__procs__` 使「terminate 未生效→升级 kill」由 1/12 腿计时偶然变为确定性覆盖；补 `atomic_write` 两处 OSError 兜底与 `image_io._is_junction` lstat 竞态用例（后者此前 12/12 腿未覆盖）；test job 逐腿产出 junit 与失败摘要（`coverage-*` 产物保持只含 coverage.xml）；extras 投递 Codecov 的 flag 名与 `codecov.yml` 声明对齐；`coverage[toml]` 钉死 7.16.2 消除 12 腿双引擎。§3.7 / §4.6 / §7 `test` 行与 `tests/test_coverage_gate_contract.py`（8→11 条）同步）
