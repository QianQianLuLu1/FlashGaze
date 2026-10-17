# FlashGaze 已知陷阱（修改前必读）

> 本文件从 `AGENTS.md` §3 拆分而来，承载完整的已知陷阱细节。
> AGENTS.md 保留摘要与导航链接。

---

## 3.1 numpy 上限 `<2.3`（PEP 695 兼容）

- **约束**：`numpy>=1.24.0,<2.3`（`pyproject.toml`）
- **原因**（两个独立成因，任一未解除都不能放宽上限）：
  ① numpy 2.3 起 `requires-python` 升至 `>=3.11`（官方发布说明：2.3.0 支持 Python 3.11–3.13），与本项目 `requires-python = ">=3.10"` 直接冲突——这是当前 `<2.3` 的**生效约束**；
  ② numpy **2.5+** 内置 stubs 使用 PEP 695 `type` 语法，与 mypy `python_version=3.10` 目标冲突（语法级错误，无法通过 `follow_imports` 绕过）。
- **解除条件**：mypy 上游支持低版本目标的 PEP 695 向下兼容解析 **OR** 项目最低 Python 升到 **3.12+**。实测 mypy 1.20.2：`--python-version 3.10` 与 `3.11` 均报 `Type statement is only supported in Python 3.12 and greater`，仅 3.12 通过 → **升到 3.11 不足以解除成因 ②**。
- **权威说明**：`docs/PEP695_COMPAT.md`（SSoT，配置注释只做指针）。注意 `pyproject.toml` 注释现写的「mypy 目标升至 3.11+」偏松，以本节实测为准。
- **修改前**：必须重跑 CI `extras` job 验证依赖解析

## 3.2 opencv-python-headless（CI 无 OpenGL）

- **约束**：使用 `opencv-python-headless` 而非 `opencv-python`
- **原因**：CI runner（ubuntu-latest）无 OpenGL 库，headless 版不链接 libGL
- **BRISQUE 依赖**：`opencv-contrib-python-headless`（含 `cv2.quality` 模块）

## 3.3 PEP 695 语法禁用

- **约束**：代码库**禁止**使用 PEP 695 语法（`type X = ...`、`class Box[T]`、`def f[T](x: T)`）
- **原因**：mypy 在 `python_version=3.10` 目标下无法解析 PEP 695，报语法级错误
- **替代写法**：`TypeVar` / `typing.TypeAlias` / `Generic[T]` 传统写法
- **解锁路线图**：见 `docs/PEP695_COMPAT.md` 第 4-5 节

## 3.4 json5 容忍 VLM JSON 围栏格式

- **约束**：`json5>=0.9`（`pyproject.toml`）
- **原因**：VLM 返回的 JSON 可能含围栏（```json ... ```）或尾随逗号，json5 容忍这些格式
- **降级路径**：`vlm_client.py` 对 **HTTP 状态码 200 但响应体不是 dict**（数组/字符串等非 dict JSON）的响应降级为 `None`——源码注释里的「200」指状态码，**不是响应行数**

## 3.5 mypy strict 模式（全量加严）

- **约束**：`[tool.mypy] strict = true`，`files = ["flashgaze", "tests", "tools/bench"]`（`tools/check_agents_md.py` 与 `tools/extras_health.py` 刻意留在范围外，前者纯 stdlib 无第三方类型依赖）
- **历史**：阶段 1-4 逐模块加严（2026-08），阶段 5 全量 strict（2026-09）
- **修改前**：任何新代码必须通过 `python -m mypy`（0 错误）
- **禁止**：新增 `# type: ignore`（既有 3 处保留）

## 3.6 pytest 默认口径（裸跑不含 e2e/benchmarks）

- **约束**：`pyproject.toml [tool.pytest.ini_options] addopts = '-m "not e2e'"`（单引号包裹、内层双引号），`testpaths = ["tests"]`
- **原因**：e2e 需要 playwright + 浏览器，benchmarks 需要 pytest-benchmark，默认排除
- **CI 守卫**：`Bare pytest default gate (collect-only)` 步骤验证裸跑不含 e2e/benchmarks 节点 ID
- **本地全量**：`pytest tests/ benchmarks/ -m ""`（显式覆盖 marker 过滤），或 `make test-all`（等价 `-o addopts=` 整体清空默认过滤）
