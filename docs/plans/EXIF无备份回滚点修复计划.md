# EXIF 无备份回滚点修复计划（审查条目 H-2）

- **审查条目**：H-2 `--no-exif-backup` 下原地改写用户原图无任何回滚点，且 EXIF 写入失败不改变退出码
- **审查域**：文件与数据安全
- **违背原则**：安全优先、Agent 友好
- **证据**：`flashgaze/core/exif_writer.py:319-324`、`flashgaze/cli/entry.py:116-128`
- **日期**：2026-08-31

## 1. 依赖声明

| 依赖 | 版本 | 变更 | 安装方式 |
|---|---|---|---|
| `piexif` | 1.1.3（本机已装） | 无变更，可选 extras `.[exif]` | `pip install -e ".[exif]"` |
| Python 标准库 `hashlib` / `json` / `datetime` / `os` | 随解释器 | 新增 import（撤销日志用） | 无需安装 |
| `ruff` / `mypy` | 见 `requirements-dev.txt` | 无变更 | 已装 |

**结论：本次零新增第三方依赖。** 撤销日志只用标准库实现，不引入日志框架或外部 schema 库。

## 2. 启动说明

### 环境准备

- 工作区根目录：`d:/Qoder项目/SaiTu skill`（Windows / PowerShell，非 git 仓库）
- Python 3.12.10，`piexif 1.1.3` 已安装（`tests/test_exif_writer.py` 的 `importorskip("piexif")` 可真实生效）
- 命令一律在仓库根直接执行（中文路径下 `cd` 会被 GBK 误解析）

### 常用命令

```powershell
# 单个节点的回归子集
python -m pytest tests/test_exif_writer.py tests/test_cli_main.py tests/test_exporter.py -q

# 全量回归（test_cli_e2e 在本机需 PYTHONIOENCODING=utf-8，否则为环境假阳性）
$env:PYTHONIOENCODING="utf-8"; python -m pytest tests/ -q

# 静态/类型门禁（Makefile 目标真实存在）
python -m ruff check .
python -m ruff format --check .
python -m mypy            # 基线 0 错误，必须保持 0
```

### 手工验证方式（端到端）

```powershell
# 1) 无回滚点且未确认 → 退出码 1，不改动任何图片
python -m flashgaze tests/fixtures --no-vlm --exif --no-exif-backup
echo $LASTEXITCODE   # 期望 1

# 2) 显式确认 → 退出码 0，并产出撤销日志
python -m flashgaze tests/fixtures --no-vlm --exif --no-exif-backup --force
echo $LASTEXITCODE   # 期望 0
Get-ChildItem tests/fixtures/.flashgaze_undo   # 期望 exif_undo_<UTC>_<pid>.jsonl
```

> 手工验证用 `tests/fixtures` 会被写脏，验证后须还原（推荐改用临时副本目录）。

## 3. 错误处理

| 分支 | 处理 | 日志级别 | 退出码影响 |
|---|---|---|---|
| `--exif` 且无回滚点且未 `--force` | 在扫描/评分前拒绝，**不构造 `ExifWriter`**（绝不落笔），提示「加 `--force` 或去掉 `--no-exif-backup`」 | ERROR | `PARAM_ERROR(1)` |
| 撤销日志 `mkdir` / 写盘 `OSError` | 每进程仅 WARNING 一次（实例 flag 去重，避免逐图刷屏）→ 继续写入 EXIF | WARNING | 无（`result.ok` 不受影响） |
| 读原图计算 SHA256 `OSError` | 跳过该条记录，同上告警 | WARNING | 无 |
| `piexif.helper.UserComment.load` 解码异常 | 该字段落 `null`，其余字段照记 | DEBUG | 无 |
| `Path.resolve()` `OSError` | 回落原始 `path` 字符串 | 无 | 无 |
| EXIF 部分/全部写入失败 | ERROR 记失败张数；导出/清单照常产出（结果可观测优先于提前中止） | ERROR | `EXIF_ERROR(7)` |
| `piexif` 未安装 | 维持既有行为 | ERROR | `CONFIG_ERROR(6)` |
| 导出 / JSON / CSV / XLSX 失败 | 维持既有映射，各自提前返回 | ERROR | `EXPORT_ERROR(5)` / `CONFIG_ERROR(6)` |

**设计取舍**：撤销日志是「无备份时的 best-effort 补偿」，用户已用 `--force` 接受无回滚点，故其失败**不阻断写入**；字节级回滚仍只能靠 `.flashgaze_backup`，此语义必须写在 `exif_writer` 模块 docstring 中，不得把撤销日志包装成等价回滚点。

## 4. 参数校验

| 入参 | 类型 | 必填 | 边界与非法值处理 |
|---|---|---|---|
| `ExifWriter(preserve_original, undo_log)` | `bool` / `Path \| None` | 否（默认 `True` / `None`） | `undo_log=None` = 关闭撤销日志（默认）；非 `Path` 由 mypy 拦截 |
| 撤销记录字段 `path` | `str` | 是 | `resolve()` 失败回落原字符串；不存在的文件在上游已由 `piexif.load` 判失败 |
| `sha256_before` | `str`(hex64) | 是 | 读文件失败 → 该条记录整体跳过 |
| `user_comment_before` | `str \| None` | 否 | 无 UserComment → `null`；解码异常 → `null` |
| CLI `--force`（score 新增） | `store_true`，`default=False` | 否 | 非 `Config` 字段，不进配置层；cleanup 的 `--force` 语义独立不变 |
| CLI `--no-exif-backup` | `store_true`，`default=None` | 否 | 经 `build_config` 归一化为 `exif_backup=False`；配置文件 `exif_backup: false` 与 CLI 旗同源触发门禁 |
| `ExitCode.EXIF_ERROR` | `IntEnum = 7` | 是 | 纯增量，既有 0–6 数值不变 |

## 5. 基础测试用例

覆盖正常 / 异常 / 边界三类，全部先写红灯、后转绿。

| # | 文件 | 用例名 | 类别 | 修复前红灯原因 |
|---|---|---|---|---|
| 1 | `tests/test_exif_writer.py` | `test_undo_log_records_pre_write_state` | 正常 | `ExifWriter` 不接受 `undo_log` 参数 → `TypeError` |
| 2 | `tests/test_exif_writer.py` | `test_undo_log_failure_warns_and_still_writes` | 异常 | 无撤销日志逻辑，无 WARNING |
| 3 | `tests/test_exif_writer.py` | `test_no_undo_log_without_undo_log_path` | 边界 | 同上（断言默认路径不产生 `.flashgaze_undo`） |
| 4 | `tests/test_cli_main.py` | `test_no_exif_backup_without_force_returns_param_error` | 异常 | 当前返回 `SUCCESS` |
| 5 | `tests/test_cli_main.py` | `test_no_exif_backup_with_force_proceeds_and_passes_undo_log` | 正常 | 无 `undo_log` 参数 |
| 6 | `tests/test_cli_main.py` | `test_exif_failure_returns_exif_error` | 异常 | 当前返回 `SUCCESS` |
| 7 | `tests/test_cli_main.py` | `test_no_exif_backup_force_writes_real_undo_log` | 正常（真机 piexif） | 撤销日志文件不存在 |
| 8 | `tests/test_exporter.py` | `test_build_report_exif_failed_top_level` | 正常/边界 | 无 `summary["exif_failed"]` 键 |

**既有契约用例改造**：`tests/test_cli_main.py:434 test_main_score_exif_no_backup_flag_disables_preserve`
现断言 `--exif --no-exif-backup` 返回 `SUCCESS`，按新契约必红，改写为「无 `--force` → `PARAM_ERROR`；加 `--force` → `SUCCESS` 且 `preserve_original=False`」。属契约变更，不是弱化失败。

## 6. 子任务分解

### 子任务 A：`ExitCode.EXIF_ERROR`

- **文件**：`flashgaze/models/schemas.py`
- **输入**：无；**输出**：`ExitCode.EXIF_ERROR = 7`
- **验收**：`python -c "from flashgaze.models.schemas import ExitCode; print(int(ExitCode.EXIF_ERROR))"` 输出 `7`；`tests/test_exporter.py` 用例 8 转绿

### 子任务 B：`build_report` 顶层 `exif_failed`

- **文件**：`flashgaze/core/exporter.py`
- **输入**：`exif_results`（含 `.ok` 的对象列表）；**输出**：`summary["exif_failed"]`（`exif_results is not None` 时才有该键）
- **验收**：用例 8 三条断言全绿；MCP/WebUI 不传 `exif_results` 时报告结构零变化（`python -m pytest tests/test_mcp_server.py tests/test_webui.py -q` 无新增失败）

### 子任务 C：`ExifWriter` 差异撤销日志

- **文件**：`flashgaze/core/exif_writer.py`
- **输入**：`undo_log: Path | None`；**输出**：JSONL 行 `{ts, pid, path, sha256_before, user_comment_before}`
- **验收**：用例 1/2/3 全绿；`tests/test_exif_writer.py` 既有用例零回归

### 子任务 D：CLI 门禁 + 撤销日志路径 + 失败退出码

- **文件**：`flashgaze/cli/parser.py`、`flashgaze/cli/entry.py`
- **输入**：CLI 命名空间与 `Config`；**输出**：退出码、stderr 日志、撤销日志文件
- **验收**：用例 4/5/6/7 全绿；`tests/test_cli_parser.py`、`tests/test_entry_contract.py` 结构护栏用例零回归

### 子任务 E：文档同步

- **文件**：`README.md`（EN/ZH 各两处）、`SKILL.md`、`CHANGELOG.md`
- **验收**：grep 校验退出码 7 与 `--force` 说明齐备；全量测试无因文档变更引起的失败

### 子任务 F：全量回归

- **验收**：`PYTHONIOENCODING=utf-8 python -m pytest tests/ -q` 无新增失败；`ruff check .` 无新增（`--diff` 核对）、`ruff format --check .` 通过、`mypy` 0 错误
