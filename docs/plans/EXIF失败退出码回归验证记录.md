# EXIF 批量写入失败退出码映射（M-15/H-2）回归验证记录

- 日期：2026-09-06
- 类型：验证型任务（无代码改动）
- 来源条目：`docs/review/代码质量与架构审查报告.md` M-15「EXIF 批量写入失败不映射退出码，仅以 INFO 记录成功率」
  - 来源标注：该审查报告是本地一次性产物，被 `.gitignore` 的 `/docs/review/` 规则忽略、**不随仓库分发**；此处仅作 M- 编号溯源，仓库内可见的落地证据以本文件与 `CHANGELOG.md` 对应条目为准。
- 结论：**该条目已于 2026-08-31 修复落地（H-2/M-15，见 CHANGELOG.md），本次回归验证全部通过，无需任何代码改动。**

## 1. 背景与证据行号漂移说明

审查条目引用的证据为 `flashgaze/cli/entry.py:116-128`，与当前文件不符——该区间现为
`--move` / `--export-dir` 参数校验（entry.py:115-127）。`write_batch` 调用点现为
entry.py:211。审查基于旧版本快照，修复在快照之后已落地。

## 2. 现状证据（三条修复方向均已实现）

| 修复方向 | 现状 | 位置 |
|---|---|---|
| 失败数>0 映射独立退出码 | `ExitCode.EXIF_ERROR = 7`；`if exif_failed: return ExitCode.EXIF_ERROR` | `flashgaze/models/schemas.py:64`；`flashgaze/cli/entry.py:340-341`（与导出码 5 同时成立时 5 优先，entry.py:332-337） |
| summary 顶层暴露 exif_failed | `summary["exif_failed"] = len(exif_results) - ok`；既有 `summary.exif.failures` 明细保留；未传 `exif_results` 时不产出该键（MCP/WebUI 零变化） | `flashgaze/core/exporter.py:197-210` |
| 不再仅 INFO 记录 | 失败时 `logger.error("EXIF 写入失败 %d/%d 张（详见 JSON summary.exif.failures 与 summary.exif_failed）")` | `flashgaze/cli/entry.py:215-222` |

配套（均已存在）：

- 回归测试：`tests/test_cli_main.py::test_exif_failure_returns_exif_error`（:806-828，
  部分失败 → 退出码 7 + ERROR 日志）、`tests/test_exporter.py::test_build_report_exif_failed_top_level`
  （:546-574，顶层计数 / 显式 0 / 未传无键三断言）
- 文档同步：README.md「Exit Codes」码 7 行（EN :541 / ZH :1196，与码 5 优先级声明 :539）、
  SKILL.md 返回码表（:312）、CHANGELOG.md H-2/M-15 条目（:40）
- MCP 侧：`flashgaze/mcp_server.py` 全文无 exif 引用，EXIF 写入为 CLI 专属链路，无残留缺口

## 3. 验证执行记录（实际运行输出）

环境：Windows / Python 3.12 / 仓库根执行，无需隐式注入的环境变量（仅全量套件按既有约定加 `PYTHONIOENCODING=utf-8`）。

### 3.1 目标回归用例

```
$ python -m pytest "tests/test_cli_main.py::test_exif_failure_returns_exif_error" \
                   "tests/test_exporter.py::test_build_report_exif_failed_top_level" -q
2 passed in 0.46s        （exit 0）
```

### 3.2 相关测试文件（CLI / 导出 / EXIF 写入）

```
$ python -m pytest tests/test_cli_main.py tests/test_exporter.py tests/test_exif_writer.py -q
155 passed, 1 skipped in 7.75s   （exit 0；skip 为平台条件跳过，非 EXIF 相关）
```

### 3.3 全量回归

```
$ PYTHONIOENCODING=utf-8 python -m pytest tests/ -q
1054 passed, 28 skipped, 68 warnings in 475.28s   （exit 0，0 failed）
```

（2026-08-31 基线为 819 passed/28 skipped；基线之后仓库新增用例，本次以 0 failed 为验收口径。）

### 3.4 静态检查

```
$ python -m mypy
Success: no issues found in 77 source files      （exit 0）

$ python -m ruff check .
All checks passed!                                （exit 0）

$ python -m ruff format --check .                 （ruff 0.16.4）
44 files would be reformatted, 298 files already formatted   （exit 1）
```

`format --check` 的 44 个文件均为**既有历史漂移**（ruff 0.16.x 对中文注释对齐与
markdown 代码块的格式化口径与存量代码不一致），2026-08-31 落地记录已注明该现象
（当时 16 个，本地 ruff 0.16.4 下扩大到 44 个，新增部分主要是 .md 计划文档与
.qoder/.zcode 草稿脚本）。本次任务零代码改动，按「最小化改动」原则**不重排任何
无关文件**，仅记录清单：`.codebuddy/plans/*.md`（13）、`.zcode/plans/*.md`（3）、
`.qoder/better-harness/**/_validate.py`（2）、`SKILL.md`、`docs/plans/删除不可逆修复计划.md`、
`docs/review/代码质量与架构审查报告.md`、`benchmarks/conftest.py`、
`flashgaze/{cli/entry,cli/parser,core/cleanup,core/exif_writer,core/vlm_client,mcp_server,utils/config,webui/app,webui/runner}.py`、
`tests/{e2e/test_webui_e2e,test_atomic_write,test_cleanup,test_cli_parser,test_config,
test_exif_writer,test_exporter,test_factory,test_mcp_server,test_vlm_client,test_webui,
test_webui_components}.py`、`tools/extras_health.py`。

## 4. 测试用例覆盖映射（复用既有用例，未新增）

- 正常：`tests/test_cli_main.py:794-796` — `--exif` 全部成功 → `ExitCode.SUCCESS(0)`
- 异常：`tests/test_cli_main.py:806-828` — 部分失败（2 成功其余失败）→ `ExitCode.EXIF_ERROR(7)` + ERROR 日志
- 边界：`tests/test_exporter.py:546-574` — 全部成功 → `summary.exif_failed == 0`（显式 0 非缺键）；未传 `exif_results` → 键不出现（MCP/WebUI 报告结构零变化）
- 反例：导出与 EXIF 同时失败时码 5 优先于 7（`tests/test_cli_main.py` 导出优先级用例，CHANGELOG.md:36 所列）；未启用 `--exif` 时不产生 `exif_failed` 键

## 5. 验收结论

| 验收项 | 结果 |
|---|---|
| 文档能力描述与实现一致（README/SKILL.md 码 7 语义 = 实现行为） | 一致（§2 核对原文） |
| 反例不被误命中、既有场景未失效 | 通过（§4 反例用例在全量回归中通过） |
| 验证命令可独立执行（仓库根，无隐式注入） | 通过（§3 实际运行） |
| 示例命令可原样复现 | 通过（§3 命令与输出逐字一致） |
| 目标回归 / 相关文件 / 全量回归 | 2 passed / 155 passed 1 skipped / 1054 passed 28 skipped，0 failed |
| mypy / ruff check | 0 错误 / 全过 |
| ruff format --check | 44 文件既有历史漂移，已记录、未修改（非本次引入） |

遗留事项：无（本条目无待办代码改动；format 历史漂移为独立的全局治理事项，不在本条目范围内）。
