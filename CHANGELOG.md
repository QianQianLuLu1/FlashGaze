# Changelog

本文件记录 FlashGaze 每次发布的 notable 变更。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.1.0] - 2026-08-05

### 功能
- AI 辅助本地图片评分与筛选：CV 客观评分（清晰度 / 曝光度 / 可选构图）+ VLM 场景补偿
- 混合评分引擎（HybridScorer）：CV 客观分与 VLM 场景补偿融合，`--no-vlm` 纯离线零成本模式
- 三大入口：CLI（`flashgaze`）、MCP Server（`flashgaze.mcp_server`）、Web GUI（`flashgaze-webui`，基于 Gradio）
- VLM 多提供商：默认 `qwen`（OpenAI 兼容路径，零新依赖），另支持 `openai` / `anthropic` / `ollama`（非 qwen 需安装 litellm）
- 可选 CV 增强维度（按 extras 按需安装、缺失时优雅降级）：
  - 噪点评估（BRISQUE，opencv-contrib）
  - 色彩丰富度
  - 人像专项（face_recognition）
  - PHash 去重（imagededup）
- EXIF 评分写回（仅 JPEG/TIFF，piexif）
- Excel 清单导出（openpyxl，带条件格式）
- 可扩展插件系统：标准库 `importlib` 自动发现，内置示例插件 `example_aesthetics`
- 工作空间清理安全护栏：默认 `dry_run=True` 只报告不删除；删除前做 TOCTOU 类型校验（拒绝符号链接 / 设备文件 / 目录），杜绝误删
- 优雅降级：可选依赖缺失时返回安全默认值（None / 0 / False）并告知用户，不崩溃
- 确定性可复现：`--no-vlm` 模式下同一张图片评分逐位不变
- 落盘统一使用原子写（`flashgaze.utils.atomic_write`）；stdout 输出 JSON，stderr 输出日志
- 308 项测试通过（另有 18 项跳过，合计 326 个测试函数）

### 技术约束（实现约定，非用户功能）
- Config 为 frozen dataclass，所有变更经 `dataclasses.replace` 生成新对象
- 外部输入默认不可信，错误显式处理，不静默吞掉
- 评分逻辑单一来源：`HybridScorer.score_paths()`
