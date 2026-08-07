---
name: flashgaze
description: >-
  AI 辅助图片评分与筛选工具。当用户需要评估本地图片质量、批量打分、
  筛选高质量照片、从图片目录中选出最佳图片时使用此技能。
  支持三种工作模式：目录批量评分、上传图片列表评分、工作空间原地清理（删除低分图）。
  CV 客观评分（清晰度+曝光度）与 VLM 场景补偿混合评分，
  支持可选 CV 增强维度：噪点（BRISQUE）、色彩丰富度、人像专项、PHash 去重，
  全部默认关闭，按需通过 --enable-noise / --enable-color / --enable-portrait / --enable-dedup 启用。
  VLM 层基于 LiteLLM 统一接入多提供商（qwen / openai / anthropic / ollama），无厂商专属适配代码；
  支持场景化评分（--scene auto/portrait/landscape/still_life）与评分可解释性（vlm_reason / vlm_provider 字段）。
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
    - noise
    - color
    - portrait
    - dedup
    - vlm
    - multi-vlm
    - scene
    - explainability
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
# 如需使用非 qwen 的 VLM 提供商（openai / anthropic / ollama）
pip install -e ".[vlm-multi]"
```

> **零依赖兼容**：默认 `qwen` 提供商走原有 `requests.post` 路径，**无需安装 litellm**，老用户配置零修改。
> 仅当显式指定 `--vlm-provider openai/anthropic/ollama` 时才需要 `pip install -e ".[vlm-multi]"`。

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
7. **VLM 字段可能为空**：`vlm_reason` / `vlm_provider` 在 `--no-vlm` 或 VLM 失败时为空串，解析时需容错
8. **多 VLM 提供商路由**：非 `qwen` 提供商需目标机器已 `pip install -e ".[vlm-multi]"`，否则自动降级为纯 CV，不报错

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
| `--vlm-provider PROVIDER` | VLM 提供商：`qwen`（默认）/ `openai` / `anthropic` / `ollama`。非 qwen 需 `pip install -e ".[vlm-multi]"` |
| `--scene SCENE` | 场景化评分模式：`auto`（默认）/ `portrait` / `landscape` / `still_life` |
| `--workers N` | 并发数（默认 4） |
| `--enable-composition` | 启用构图评分（实验性） |
| `--enable-noise` | 启用 BRISQUE 噪点评分（需 opencv-contrib-python + 模型文件） |
| `--enable-color` | 启用色彩丰富度评分（HSV 直方图分布） |
| `--enable-portrait` | 启用人像专项评分（需 face_recognition） |
| `--enable-dedup` | 启用 PHash 图片去重（需 imagededup） |
| `--dedup-threshold N` | PHash 汉明距离阈值（默认 8，越小越严格） |
| `--weights JSON` | 自定义权重 JSON，可选 key：composition/noise/color |

## VLM 提供商

通过 LiteLLM 统一调用层支持 4 个 VLM 提供商，**无任何厂商专属适配代码**。默认 `qwen` 走原有 `requests.post` 路径，零新依赖、100% 向后兼容；其他 3 个提供商经 LiteLLM 路由（需 `pip install -e ".[vlm-multi]"`）。

| Provider | 模型示例 | API base | 需要 LiteLLM |
|---|---|---|---|
| `qwen`（默认） | `qwen-vl-max` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 否 |
| `openai` | `gpt-4o` | `https://api.openai.com/v1` | 是 |
| `anthropic` | `claude-3-5-sonnet-20241022` | 留空走 LiteLLM 默认 | 是 |
| `ollama` | `llama3.2-vision` | `http://localhost:11434` | 是 |

### 环境变量配置示例

```bash
# 1. 通义千问（默认，100% 向后兼容，无需 litellm）
export FLASHGAZE_VLM_PROVIDER=qwen
export FLASHGAZE_API_KEY=sk-xxxxxxxx
export FLASHGAZE_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
export FLASHGAZE_MODEL=qwen-vl-max

# 2. OpenAI GPT-4o（需 litellm）
export FLASHGAZE_VLM_PROVIDER=openai
export FLASHGAZE_API_KEY=sk-xxxxxxxx
export FLASHGAZE_API_BASE=https://api.openai.com/v1
export FLASHGAZE_MODEL=gpt-4o

# 3. Anthropic Claude 3（需 litellm，api_base 留空走 LiteLLM 默认）
export FLASHGAZE_VLM_PROVIDER=anthropic
export FLASHGAZE_API_KEY=sk-ant-xxxxxxxx
export FLASHGAZE_API_BASE=
export FLASHGAZE_MODEL=claude-3-5-sonnet-20241022

# 4. Ollama 本地 VLM（需 litellm，无需真实 key）
export FLASHGAZE_VLM_PROVIDER=ollama
export FLASHGAZE_API_KEY=ollama
export FLASHGAZE_API_BASE=http://localhost:11434
export FLASHGAZE_MODEL=llama3.2-vision
```

### 降级行为

- 未安装 `litellm` 但 `provider != qwen`：VLM 调用返回 `ok=False`，`error="litellm_not_installed"`，主流程自动回退纯 CV
- 非法 `provider` / `scene` 值：在 `build_config` 阶段回退到默认值并记 warning，不抛异常
- VLM 网络错误 / 超时 / 解析失败：重试耗尽后返回 `ok=False`，`vlm_adjustment=0.0`，`vlm_reason=""`，批处理不中断

## 场景化评分

`--scene` 参数切换 VLM 提示词，针对不同场景使用差异化评分侧重点。`auto`（默认）由 VLM 自行判断场景，与原版单一提示词语义一致。

| Scene | 适用场景 | 提示词侧重点 |
|---|---|---|
| `auto`（默认） | 混合目录、内容未知 | VLM 自行判断场景；与原版单一提示词语义一致 |
| `portrait` | 人像 / 头像 / 街拍人像 | 背景虚化作为艺术手法；人脸区域清晰度 |
| `landscape` | 风光 / 自然 / 建筑 | 长曝光流水/云层；逆光剪影；暗调氛围 |
| `still_life` | 产品 / 美食 / 静物平铺 | 景深控制；布光氛围；暗调质感 |

```bash
# 人像目录使用场景化提示词
flashgaze ./portraits --scene portrait --top 20 --json

# 风光目录
flashgaze ./landscapes --scene landscape --top 30 --json
```

> `auto` 模式不会额外调用 VLM 做场景识别（避免双倍 token 消耗），而是把"请自行判断"写进提示词，由 VLM 一次完成。

## 评分可解释性

每张经过 VLM 调整的图片在 JSON / CSV 输出中携带两个新字段：

- `vlm_reason` — VLM 评分理由（≤20 字中文），如 `背景虚化` / `逆光剪影` / `技术失误`。`--no-vlm` 或 VLM 失败时为空串
- `vlm_provider` — 产生本次调整的 VLM 提供商标识，如 `qwen` / `openai`。`--no-vlm` 或 VLM 失败时为空串

```json
{
  "file": "DSC_0042.jpg",
  "score": 92.75,
  "vlm_adjustment": 5.0,
  "vlm_reason": "背景虚化突出主体",
  "vlm_provider": "qwen"
}
```

**硬上限约束**：
- `vlm_reason` 入库前裁剪到 20 字（按字符数计，不按字节）
- `vlm_adjustment` 始终 clamp 到 `[-vlm_max_adjustment, +vlm_max_adjustment]`（默认 ±10）
- VLM 响应格式异常时降级为 `vlm_adjustment=0.0` + 空理由，**不抛异常**

## 可选 CV 增强维度

四个增强维度默认全部关闭，依赖缺失时优雅降级（不报错，对应字段返回 null/0/false）。

| 维度 | 安装 | 启用方式 | 适用场景 |
|---|---|---|---|
| 噪点（BRISQUE） | `pip install -e ".[cv-enhanced]"` + 下载模型文件 | `--enable-noise` | 惩罚噪点多/压缩重的图片 |
| 色彩丰富度 | 内置（OpenCV） | `--enable-color` | 奖励色彩多样、饱和度高的图片 |
| 人像 | `pip install -e ".[portrait]"` | `--enable-portrait` | 加分含人脸的图，并校验人脸区域清晰度 |
| 去重 | `pip install -e ".[dedup]"` | `--enable-dedup` | 合并连拍相似图，仅保留最高分 |

启用 composition/noise/color 任一维度但未提供 `--weights` 时，会自动注入合理默认权重（如全启用 → sharpness 0.35 / exposure 0.25 / composition 0.20 / noise 0.10 / color 0.10）。
