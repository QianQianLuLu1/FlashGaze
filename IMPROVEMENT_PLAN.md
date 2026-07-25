# FlashGaze 工程改进计划

## 审查基线

- 审查日期: 2026-07-15
- 测试基线: 91 项原有测试 + 22 项边界测试 + 39 项新功能测试 = 152 项全部通过
- 审查范围: 全部 Python 源码、CLI、MCP Server、测试、文档

## 问题清单与进度

### 严重问题（影响评分正确性）

| # | 问题 | 文件 | 状态 |
|---|---|---|---|
| 1 | CV 评分对大图缩放不一致（拉普拉斯方差与尺寸正相关） | `cv_engine.py` → `compute_sharpness()` | ✅ 已修复 |
| 2 | `iter_images` 非递归，子目录图片被忽略 | `image_io.py` → `iter_images()` | ✅ 已修复 |
| 3 | 导出无文件名冲突处理，同名文件覆盖/丢失 | `exporter.py` → `export_images()` | ✅ 已修复 |
| 4 | VLM 429 限流不重试，直接放弃 | `vlm_client.py` → `_post_with_retry()` | ✅ 已修复 |
| 5 | 评分权重不可通过 CLI/环境变量调整 | `parser.py` / `defaults.py` | ✅ 已修复 |

### 中等问题（影响体验和一致性）

| # | 问题 | 文件 | 状态 |
|---|---|---|---|
| 6 | MCP 工具手动拼 JSON，未复用 `Exporter.build_report` | `mcp_server.py` | ✅ 已修复 |
| 7 | cleanup 同样受非递归限制 | `mcp_server.py` → `cleanup_workspace_images()` | ✅ 已修复 |
| 8 | 无 .HEIC / .tiff / .bmp 支持 | `defaults.py` → `SUPPORTED_EXTENSIONS` | ✅ 已修复 |
| 9 | `no_vlm` 默认值不一致（MCP=True, CLI=False） | `mcp_server.py` vs `parser.py` | ✅ 已修复 |
| 10 | 无进度反馈，大批量评分时无法判断状态 | `hybrid_scorer.py` → `score_paths()` | ✅ 2026-07-16 重新落地验证（A-04） |
| 11 | 曝光度算法过于简化（仅中间灰度占比） | `cv_engine.py` → `compute_exposure()` | ✅ 已修复 |
| 12 | Config 运行时被直接篡改（`config.export = True`） | `mcp_server.py` L271-272 | ✅ 2026-07-16 重新落地验证（A-05，改用 dataclasses.replace + Config frozen=True） |

## 开发记录

### 2026-07-15 #1 + #11: CV 引擎尺寸归一化 + 曝光度算法优化

- `cv_engine.py` 新增 `_normalize_size()` 方法，拉普拉斯方差前将图片长边归一化到 1024px
- `defaults.py` 新增 `SHARPNESS_NORMALIZE_SIZE = 1024` 常量
- `compute_exposure()` 新增均值偏差维度：中间灰度占比(0.6) + 均值偏离 127.5 程度(0.4)
- 测试: 11/11 通过（含确定性测试）

### 2026-07-15 #2 + #8: iter_images 递归扫描 + 扩展图片格式

- `image_io.py` → `iter_images()` 新增 `recursive` 参数，默认 True 递归扫描子目录
- `defaults.py` → `SUPPORTED_EXTENSIONS` 扩展为 9 种格式：jpg/jpeg/png/webp/bmp/tiff/tif/heic/heif
- 测试: 35/35 通过（CV + Hybrid + CLI E2E）

### 2026-07-15 #3 + #4 + #5: 导出冲突处理 + VLM 429 重试 + 权重可配置

- `exporter.py` 新增 `_resolve_conflict()` 方法，同名文件自动追加序号后缀（如 `IMG_001_1.jpg`）
- `exporter.py` 新增 `build_report()` 方法，统一 JSON 报告构造逻辑
- `vlm_client.py` 重写 `_post_with_retry()`，429 时解析 `Retry-After` header 退避重试
- `vlm_client.py` 新增 `_parse_retry_after()` 支持秒数和 HTTP 日期格式
- `defaults.py` 新增 `ENV_WEIGHTS` 环境变量名
- `config.py` `merge_env()` 支持 `FLASHGAZE_WEIGHTS` 环境变量（JSON 格式）
- `parser.py` 新增 `--weights` CLI 参数（JSON 字符串）
- `test_vlm_client.py` 全部 mock 补充 `status_code` 和 `headers`，新增 2 个 429 测试
- 测试: 91/91 通过（新增 3 个：429 重试成功、429 耗尽、权重参数）

### 2026-07-15 #6 + #7 + #9 + #10 + #12: MCP JSON 复用 + cleanup 递归 + no_vlm 统一 + 进度反馈 + Config 安全

- `mcp_server.py` 改用 `Exporter.build_report()` 替代手动 JSON 拼接
- `mcp_server.py` → `cleanup_workspace_images()` 支持递归清理子目录
- `mcp_server.py` 与 `parser.py` 的 `no_vlm` 默认值统一为 False
- `hybrid_scorer.py` → `score_paths()` 新增进度回调，大批量评分时输出进度
- `mcp_server.py` 修复 Config 运行时篡改，改用局部副本替代直接修改
- 测试: 152/152 通过（91 原有 + 22 边界 + 39 新功能）

