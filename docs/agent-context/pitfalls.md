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
- **权威说明**：`docs/PEP695_COMPAT.md`（SSoT，配置注释只做指针）。`pyproject.toml` numpy 条目注释已对齐本节的 3.12+ 口径；两处若再次分叉，以 SSoT 为准。
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

## 3.7 覆盖率测量引擎与平台不可达行

- **约束**：`requirements-dev.txt` 钉死 `coverage[toml]==7.16.2`（单版本，不用区间）
- **原因**：coverage 7.17.0（2026-10-22 发布）起 `requires-python >=3.11`。不钉版时
  CI 12 腿矩阵会被 resolver 按 Python 版本分裂成两个引擎（py3.10 腿 7.16.2、其余
  7.17.0，2026-10-23 `c202ed2` 那轮 12 份 `coverage.xml` 的 `version` 属性实证），
  跨腿覆盖率不再同口径——差异无法区分「代码变了」还是「引擎变了」。`coverage` 只经
  `pytest-cov` 间接引入，所以必须显式钉它。
- **解除条件**：测试矩阵放弃 py3.10（与 `docs/PEP695_COMPAT.md` 路线 B「最低 Python
  升 3.12+」联动）后改回区间式；解除前须全 12 腿重跑确认 `fail_under=80` 不回退。
- **契约测试**：`tests/test_coverage_gate_contract.py::test_coverage_engine_is_pinned_to_single_version`
- **平台不可达行的记账口径**：`utils/atomic_write.py` 的 `os.chown` 体（114-118）在
  Windows 腿永不可执行（`hasattr(os, "chown")` 恒 False），`utils/image_io.py:145`
  的非 nt 早返回在 POSIX 腿之外不可达。这类行**不加 `# pragma: no cover`**（pragma 会
  连带屏蔽那些平台上的真实执行，且仓库现有 2 处 pragma 均非平台用途），也**不在
  Windows 上伪造 `os.chown` 存在**（假的跨平台绿灯，还会掩盖有人删掉 `hasattr` 守卫
  的回归）。口径：能跑的平台跑、跑不了的用 `skipif` 明写并留文档，Windows 腿总覆盖率
  与 POSIX 腿相差约 ±0.1pp 属真实平台差异，不是缺陷。

## 3.8 静态门禁的 Linux/Windows 语义盲区

- **事实**：CI 的 `lint` / `typecheck` job 跑在 ubuntu，而开发机常在 Windows。有两类问题
  **本地恒绿、CI 恒红**，且与工具版本无关（2026-10-23 run 39909374394 两个 job 各栽一种）：
  1. **ruff `EXE001`**（shebang present but file is not executable）：判据是文件 exec 位，
     NTFS 无该语义，本地 `python -m ruff check --select EXE001 tools/` 实测恒不报。
     口径：`tools/*.py` **一律不加 shebang**——调用方全是 `python -m tools.check_agents_md`
     （`ci.yml` / `.pre-commit-config.yaml`）或 `python tools/extras_health.py …`
     （`extras-health.yml`），仓库 0 个 `100755` 跟踪文件，shebang 是一句做不到的承诺。
  2. **mypy 按运行平台解析 typeshed 的 `sys.platform` 分支**，而 `os.name` 守卫**不做**死分支
     分析：`tests/test_image_io.py` 的 `_winapi.CreateJunction` 在 win32 视角存在、Linux 视角
     报 `attr-defined`。本地复现口径：`python -m mypy --platform linux`（已固化为
     `make typecheck-posix` 并并入 `make check`）。
- **禁止的取巧**：给这类行加 `# type: ignore[attr-defined]`——win32 视角下它不是错误，
  `strict` 自带的 `warn_unused_ignores` 会反过来把本地 `python -m mypy` 打红；改用
  `getattr(mod, "Name", None)` + 显式 `pytest.skip`。也不要用 `if sys.platform == "win32"`
  包裹——Linux 视角判死分支后 `warn_unreachable` 报 unreachable 新错。
- **工具版本口径**：`ruff==0.16.10` / `mypy==1.20.2` / `types-requests==2.33.0.20261006`
  钉死单版本（同 §3.7 的 coverage 逻辑）。`types-requests` 按日期滚动发版，上游签名一变
  就能在无人改一行代码时把 `typecheck` 打红。**诚实标注**：钉版消除的是「先怀疑版本」的
  归因成本，它拦不住本节两类平台盲区。
- **契约测试**：`tests/test_coverage_gate_contract.py::test_static_analysis_tools_are_pinned_to_single_version`
- **反方向未覆盖**：CI（ubuntu）不跑 `mypy --platform win32` 视角，Windows-only 的类型错误
  仍只靠开发机默认 `python -m mypy` 发现。本轮未加该步骤，因为无法在 Windows 之外实测它会
  带出多少既有报错——加进去等于用一次新的红灯换对称性，需单独排期。

## 3.9 测试桩的跨平台/跨版本原语选择

四条口径，全部由 2026-10-23 那轮 10/12 腿变红的用例反推出来：

1. **模拟挂起勿用 `time.sleep(1e9)`**：CPython 3.10 上 Windows（`Sleep` 的 32 位毫秒计数）与
   macOS（`select` EINVAL）会**立即抛错而非挂起**，异常经 `err_holder` 被看门狗原样重抛，
   要测的超时分支根本不触发。替代口径按存活位置分：被放弃的**看门线程**用
   `threading.Event().wait(30)`（`_hang_thread_stub`），**子进程**用 `wait(120)`。
2. **断言 workers 必须钉核数**：`utils/config.py` 把 workers 钳到 `min(cpu_count, 16)`，
   macos-latest runner 报 3 核 → `DEFAULT_WORKERS=4` 被钳成 3。用例一律
   `monkeypatch.setattr(os, "cpu_count", lambda: 16)`（`tests/test_cli_parser.py:93-94` 起即此口径）。
   **唯一例外**：`tests/test_mcp_server.py:88-94` 故意按真实核数验证钳制，它是 `config.py`
   钳制分支的唯一覆盖来源——给它加 pin 等于删掉那段覆盖。
3. **只读目标（0o444）语义分平台**：Windows 上 `os.replace` 抛 `PermissionError`，POSIX 由
   父目录写位决定、直接成功。同一场景的两种期望必须互为反向 `skipif`
   （`tests/test_atomic_write.py` 的 `test_readonly_target_rejected_leaves_no_tmp` /
   `test_readonly_target_posix_replaced_in_place`）。
4. **PTY 合流 stdout+stderr**：`--verbose` 下 CLI 的「完成: N 张图」INFO 会跟在 JSON 报告
   之后进同一条流，从首个 `\n{` 起 `json.loads` 整段尾部必报 `Extra data`。必须用
   `json.JSONDecoder().raw_decode` 只取第一个完整文档，并断言其结构（否则伪锚点会静默
   返回错文档）。见 `tests/test_cli_terminal_e2e.py::_extract_json`。

另附**跨解释器数值口径**：权重归一化用 `math.fsum` 而非 `sum`（CPython 3.12 起 `sum()` 改用
Neumaier 补偿求和，3.10/3.11 仍是朴素左折叠；叠加两次归一化后同一份 `--weights` 的 `sharpness`
在 3.11 上是 `0.39999999999999997`、3.12+ 上是 `0.4`）。`_parse_weights` 与
`_adjust_custom_weights` **两处必须同改**，只改前一处 3.10 上会得到更偏的 `0.4000000000000001`。
`hybrid_scorer.py` 的加权求和**故意不动**：同类非确定性，但出口 `round(final, 2)` 不可观测，
动它要把已钉死的分数基线重测一遍。

## 3.10 阶段1看门狗会把「排队未开工的好图」连带判死（已知未修）

- **事实**：`ProcessPoolExecutor` 的 `future.running()` 在**进入 call_queue 时**即为真
  （`concurrent/futures/process.py` 的 `add_call_item_to_queue`），而看门狗在首次观察到
  `f.running()` 时才起算 deadline（`core/hybrid_scorer.py` 单图超时处）。该处注释写的
  「排队等待不计入」与实现不符：池容量 `max_workers + 1` 的队列槽位同样算「已在执行」。
- **后果**：重建后的新一代里，排队好图可能与 ≥2 张挂起图**同代派发、共享同一 deadline**，
  被连带标 `阶段1超时(>Ns)`；一旦标记就从 `pending` 中 `discard`，而下代只重提交
  `unresolved = [futures[f] for f in pending]`，因此**救不回来**。
- **命中条件**：非确定性——取决于 `_HUNG_POLL_SEC=1.0` 的轮询粒度（挂起图的 deadline 是否
  被拆到两个 tick）与 `pending` 集合的迭代顺序。2026-10-23 仅 macos-latest py3.13 腿命中
  （该腿实测耗时 48.9s ≈ 3 代 × 15s，说明跑满了 `_POOL_REBUILD_LIMIT`）。
- **当前处置**：`test_phase1_real_pool_hung_worker_teardown_bounded[5]` 不再断言「排队好图
  必须出分」，改断「不得被整批判死」+ `phase1_stats["rebuilds"] >= 1` 指纹；该强断言由
  确定性假池用例 `test_phase1_pool_rebuild_rescues_queued_images` 钉住（12 腿都跑）。
- **未修原因**：正解要在重建时重提交本代挂起图，破坏「`pending` 严格收缩」的终止性论证，
  并改变 `test_phase1_pool_rebuild_limit_bounds_all_hang_batch` 语义；属能力变更，需单独
  排期与兼容性评估。**勿用「把 `PER_IMAGE_TIMEOUT_SEC` 调大」当作修复**——那是同代共享
  deadline 的结构问题，翻倍阈值不改变结构，只让 12 条腿一起付墙钟。

## 3.11 可选依赖的 import 守卫：`SystemExit` 不是 `ImportError`

- **事实**：上游 `face_recognition` 在 `face_recognition_models` 导入失败时（Python 3.12 的
  venv 不再自带 setuptools，`pkg_resources` 因此缺失；PEP 660 的 build isolation 只把
  setuptools 装进隔离环境、**不进目标 venv**）打印一句 `pip install git+https://…` 提示后
  直接调用 `quit()`。`quit()` 抛的是 `SystemExit`，它继承自 `BaseException`、**不是**
  `ImportError`，因此 `except ImportError` 形式的依赖探测完全拦不住它。
- **后果（CI）**：异常沿 `portrait_engine → hybrid_scorer → factory → cleanup →
  tests/test_cleanup.py` 一路上抛，在 pytest **收集阶段**打死整个 session（exit 3，
  `INTERNALERROR`）。extras 腿的测试步骤带 `continue-on-error: true`，于是 INTERNALERROR
  被吞、`.coverage`/`coverage.xml` 根本没生成，硬门禁四条命令的第一条只打
  `No data to report.` + exit 1 —— 在日志里与「覆盖率低于 floor」**长得一模一样**。
  `Upload coverage artifact` 的 `if-no-files-found: warn` 再放行一次，所以
  `coverage-extras-*` 产物从未存在过（跨最近 5 次 run 核实）。
- **后果（产品）**：装了 `.[portrait]` 而 venv 无 setuptools 的用户，`python -m flashgaze
  score` 会在 import 期被第三方包判死；`SystemExit(None)` 的**退出码是 0**，stdout 只有那句
  pip 提示、没有任何 JSON —— 直接违反 CLI「stdout 只输出 JSON」契约（§4.7 ⑥ 同一契约）。
  「退出码 0 即成功」的判据在这条链路上是无效的，`tests/test_portrait_import_guard.py`
  的第二条用例专门把这个陷阱钉住。
- **正确写法**：可选依赖的模块级探测必须 `except (ImportError, SystemExit)`
  （见 `flashgaze/core/portrait_engine.py`）。`flashgaze/core/deduplicator.py` 同为
  `except ImportError`，但 imagededup 无 import 期 `quit()` 的已知触发点，**暂不改动**；
  新增可选依赖探测时若上游包会在 import 期做退出/打印之类动作，一律并列 `SystemExit`。
- **复现要点**：本地 Windows 装不上 dlib/face_recognition，无法原样复现；
  `tests/test_portrait_import_guard.py` 用子进程在 `PYTHONPATH` 前置一个「import 即
  `raise SystemExit`」的假包复现，既确定性又不污染 `tests/test_portrait.py` 的双向 skipif。
