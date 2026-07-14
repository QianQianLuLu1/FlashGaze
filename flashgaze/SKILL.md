---
name: flashgaze
description: >-
  AI 辅助图片评分与筛选工具。当用户需要评估本地图片质量、批量打分、
  筛选高质量照片、从图片目录中选出最佳图片时使用此技能。
  支持三种工作模式：目录批量评分、上传图片列表评分、工作空间原地清理（删除低分图）。
  CV 客观评分（清晰度+曝光度）与 VLM 场景补偿混合评分，
  输出结构化 JSON/CSV 结果。工作空间清理模式有严格路径安全护栏，绝不影响目录外文件。
  适用于摄影师选片、AI Agent 图片筛选、批量图片质量评估、工作空间图片清理等场景。
metadata:
  author: FlashGaze Team
  version: "0.1.0"
  category: image-processing
  tags:
    - cv
    - scoring
    - image
    - selection
    - photography
    - cleanup
  requires:
    - python>=3.10
---

# FlashGaze 图片评分技能

## 触发场景

当用户表达以下意图时激活此技能：
- "帮我筛选/选出好的照片"
- "评估这批图片的质量"
- "给这些图片打分"
- "哪些照片质量比较高"
- "批量评价图片"
- "清理这个目录里质量差的图片"
- "删除评分低的图片"

## 三种工作模式

| 模式 | 适用场景 | 操作方式 |
|---|---|---|
| **目录评分** | 对某个目录下所有图片评分 | CLI 或 MCP `score_images` |
| **上传评分** | 对指定路径列表的图片评分（不依赖目录结构） | MCP `score_uploaded_images` |
| **工作空间清理** | 评分后原地删除低分图，仅限工作空间内 | MCP `cleanup_workspace_images` |

## 前置安装

```bash
pip install -e .
# 如需 MCP Server 功能
pip install -e ".[mcp]"
```

VLM API Key（可选，`--no-vlm` 模式不需要）：
```bash
# Windows PowerShell
$env:FLASHGAZE_API_KEY="sk-your-key"
# Linux / macOS
export FLASHGAZE_API_KEY="sk-your-key"
```

## 模式一：目录评分（CLI）

### 零成本快速初筛（推荐首选）

```bash
flashgaze <图片目录路径> --top 30 --json --no-vlm
```

### VLM 精筛（需要 API Key）

```bash
flashgaze <图片目录路径> --top 30 --json
```

### 筛选并复制到新目录

```bash
flashgaze <图片目录路径> --top 30 --json --export
```

### 阈值模式（分数 >= 75 入选）

```bash
flashgaze <图片目录路径> --threshold 75 --json
```

## 模式二：上传图片评分（MCP）

AI Agent 收到用户上传的图片后，传入路径列表进行评分：

```python
# MCP 工具调用示例
score_uploaded_images(
    image_paths=["C:/photos/img1.jpg", "C:/photos/img2.jpg"],
    top=5,
    no_vlm=True
)
```

返回 JSON 包含 `summary.skipped` 字段，列出不存在或不支持格式的路径。

## 模式三：工作空间清理（MCP）

对工作空间目录下的图片评分，原地删除低分图：

### 安全保证

- **仅删除 workspace 目录内的文件**，绝不影响目录外任何资料
- **双重路径穿越检查**：解析真实路径后用 `relative_to` 校验，防止 `../` 或符号链接逃逸
- **默认 dry_run=True**：先试运行确认要删除哪些文件，确认后设 `dry_run=False` 才真正删除
- **删除前再次校验**：每个文件删除前都重新检查路径边界

### 使用流程

```python
# 第一步：试运行，查看将要删除哪些文件
cleanup_workspace_images(
    workspace="C:/my-photos",
    top=30,
    no_vlm=True,
    dry_run=True  # 默认值，只报告不删除
)

# 第二步：确认后实际删除
cleanup_workspace_images(
    workspace="C:/my-photos",
    top=30,
    no_vlm=True,
    dry_run=False  # 真正删除低分图
)
```

### 阈值模式

```python
cleanup_workspace_images(
    workspace="C:/my-photos",
    threshold=75.0,  # 分数低于 75 的图片将被删除
    no_vlm=True,
    dry_run=False
)
```

### 返回结构

```json
{
  "status": "success",
  "code": 0,
  "summary": {
    "workspace": "C:/my-photos",
    "total": 120,
    "selected": 30,
    "to_delete": 90,
    "deleted": 90,
    "mode": "actual_delete",
    "elapsed_ms": 15420
  },
  "kept_images": [...],
  "deleted_files": ["img_001.jpg", "img_002.jpg", ...],
  "blocked_files": []
}
```

`blocked_files` 列出因安全检查被拦截的文件（路径在工作空间外等）。

## MCP Server 配置

在 AI 工具的 MCP 配置中添加：

```json
{
  "mcpServers": {
    "flashgaze": {
      "command": "python",
      "args": ["-m", "flashgaze.mcp_server"]
    }
  }
}
```

### MCP 工具列表

| 工具 | 功能 |
|---|---|
| `score_images` | 对目录下所有图片批量评分 |
| `score_single_image` | 评分单张图片 |
| `score_uploaded_images` | 对上传的图片路径列表评分 |
| `export_selected_images` | 评分后复制/移动高分图到目标目录 |
| `cleanup_workspace_images` | 工作空间原地清理：删除低分图，保留高分图 |

## 返回码

| 码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 参数错误 |
| 3 | 目录无效或无图片 |
| 4 | 评分过程异常 |
| 5 | 导出/删除失败 |
| 6 | 配置错误（缺 API Key 且未 --no-vlm） |

## Agent 调用要点

1. **stdout 取 JSON，stderr 取日志**：两个流互不污染，Agent 可靠解析
2. **先判返回码**：`returncode == 0` 才解析 stdout
3. **设超时**：大批量建议 `timeout=600` 秒
4. **可复现**：`--no-vlm` 模式下同一张图多次评分完全一致
5. **降级健壮**：单张图片损坏不中断，该图 `error` 字段记录原因，整体仍返回 0
6. **清理模式先 dry_run**：先 `dry_run=True` 确认待删文件列表，再 `dry_run=False` 执行

## CLI 选项速查

| 选项 | 说明 |
|---|---|
| `--top N` | 选前 N 张（默认 30） |
| `--threshold SCORE` | 分数阈值（替代 --top） |
| `--export` | 复制高分图到 ./精选/ |
| `--move` | 移动而非复制 |
| `--json` | JSON 输出到 stdout |
| `--csv` | CSV 输出 |
| `--no-vlm` | 纯 CV 模式（零成本） |
| `--workers N` | 并发数（默认 4） |
