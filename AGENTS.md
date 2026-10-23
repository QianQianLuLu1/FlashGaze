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

> 完整细节 → [docs/agent-context/fixes.md](docs/agent-context/fixes.md)

---

## 5. 关键命令

```bash
make install       # pip install -r requirements-dev.txt + pre-commit install（不装 -e .、不装 extras）
make lint          # python -m ruff check .
make format        # python -m ruff format .（会改写文件）
make format-check  # python -m ruff format --check .（CI 口径，不改写）
make typecheck     # python -m mypy（strict，范围见 [tool.mypy] files）
make check         # lint + format-check + typecheck
make test          # python -m pytest tests/ -q（继承默认过滤，不含 e2e）
make test-all      # python -m pytest tests/ -q -o addopts=（清空默认过滤）
make verify        # check + test（不跑会改写文件的 format）
make hooks         # pre-commit run --all-files（安装 hook 用 make install）
make dist          # pip install build twine → python -m build → twine check
```

> 安装可编辑包与 extras 需自行执行 `pip install -e ".[mcp,gui,exif,heic]"`（`make install` 只装开发工具链）。

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
| `test` | push/PR | ✅ | 12 腿矩阵（3 OS × 4 Python），覆盖率 fail_under=80 |
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

---

**最后更新**：2026-10-23（§4.3 M-05 核心教训订正为「专属日志标签 + 顺序敏感 except 分支，退出码仍 `IMAGE_ERROR(4)`」，原述「必须用专属退出码」与代码及 `tests/test_cli_main.py` 四处断言不符；`docs/plans/` 11 份已完成的一次性修复计划归档移出仓库，覆盖率逐模块下限的取值溯源改由 `docs/extras-governance.md` §2.1 承载；`CHANGELOG.md` 的 PEP 695 解锁门槛与 `pyproject.toml` 注释一并对齐为 3.12+）

**上次更新**：2026-10-17（订正 §5 与 Makefile 不符的五个目标注释、§6 幻影路径 `utils/path_safety`、§7 缺失的 `agents-md-integrity` / `check-strict` / `e2e-webkit` 三行、§2 清理护栏与 §3.1 numpy 上限成因；`docs/agent-context/` 四篇与守卫脚本首次入库）
