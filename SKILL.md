---
name: flashgaze
description: >-
  AI 辅助图片评分与筛选工具。当用户需要评估本地图片质量、批量打分、
  筛选高质量照片、从图片目录中选出最佳图片时使用此技能。
  支持四种工作模式：目录批量评分（CLI/MCP）、上传图片列表评分（MCP）、
  工作空间原地清理（MCP `cleanup_workspace_images`）、CLI 工作空间清理（`flashgaze cleanup`）。
  CV 客观评分（清晰度+曝光度）与 VLM 场景补偿混合评分，
  支持可选 CV 增强维度：噪点（BRISQUE）、色彩丰富度、人像专项、PHash 去重，
  全部默认关闭，按需通过 --enable-noise / --enable-color / --enable-portrait / --enable-dedup 启用。
  VLM 层默认经内置 pin-IP 直连层接入多提供商（qwen / openai / anthropic / ollama），无厂商专属适配代码，litellm 仅为可选 opt-in 后端；
  支持场景化评分（--scene auto/portrait/landscape/still_life）与评分可解释性（vlm_reason / vlm_provider 字段）。
  输出结构化 JSON/CSV 结果。工作空间清理模式有严格路径安全护栏，绝不影响目录外文件。
  适用于摄影师选片、AI Agent 图片筛选、批量图片质量评估、工作空间图片清理等场景。
metadata:
  author: FlashGaze Team
  version: "0.1.2"
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

## 四种工作模式

| 模式 | 适用场景 | 操作方式 |
|---|---|---|
| **目录评分** | 对某个目录下所有图片评分 | CLI 或 MCP `score_images` |
| **上传评分** | 对指定路径列表的图片评分（不依赖目录结构） | MCP `score_uploaded_images` |
| **工作空间清理（MCP）** | 评分后原地删除低分图，仅限工作空间内 | MCP `cleanup_workspace_images` |
| **工作空间清理（CLI）** | 纯命令行场景：评分后原地删除低分图，默认 dry-run | `flashgaze cleanup <目录>` |

## 前置安装

```bash
pip install -e .
# 如需 MCP Server 功能
pip install -e ".[mcp]"
# 仅当使用可选 LiteLLM 后端（编程接口 VLMClient(use_litellm=True)，特殊端点/代理场景）
pip install -e ".[vlm-multi]"
```

> **零依赖兼容**：全部 4 个 provider（qwen / openai / anthropic / ollama）默认走内置 pin-IP 直连层（构造期 DNS pin），**均无需安装 litellm**，老用户配置零修改。
> 仅当使用可选 LiteLLM 后端（编程接口 `VLMClient(use_litellm=True)`，用于特殊端点/代理场景）时才需要 `pip install -e ".[vlm-multi]"`。

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

### 路径边界（安全护栏）

- **仅允许读取「允许扫描根」内的图片**：通过环境变量 `FLASHGAZE_MCP_ALLOWED_ROOTS` 配置（逗号分隔多个根目录）
- **未配置时默认仅限服务器启动目录**：MCP 服务器进程的工作目录充当默认允许根
- 越界路径不会被读取、解码或送往 VLM：`score_uploaded_images` 将其列入返回 JSON 的 `details.skipped`（附「位于允许扫描根之外」原因），`score_single_image` 直接拒绝（code 1）

### 调用示例

```python
# MCP 工具调用示例（假设已配置 FLASHGAZE_MCP_ALLOWED_ROOTS=C:/photos）
score_uploaded_images(image_paths=["C:/photos/img1.jpg", "C:/photos/img2.jpg"], top=5, no_vlm=True)
score_single_image(image_path="C:/photos/img1.jpg", no_vlm=True)
```

返回 JSON 包含 `details.skipped` 字段，列出允许扫描根之外、不存在或不支持格式的路径。

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
    dry_run=True,  # 默认值，只报告不删除
)

# 第二步：确认后实际删除
cleanup_workspace_images(
    workspace="C:/my-photos",
    top=30,
    no_vlm=True,
    dry_run=False,  # 真正删除低分图
)
```

### 阈值模式

```python
cleanup_workspace_images(
    workspace="C:/my-photos",
    threshold=75.0,  # 分数低于 75 的图片将被删除
    no_vlm=True,
    dry_run=False,
)
```

### 预评分复用（scored）与来源可信度（C-09）

`cleanup_workspace_images` 接受可选的 `scored` 参数（ImageScore 列表，通常来自先前的 `score_images` 调用），但其分数**默认不被信任**：仅复用损坏标记（error 非 None 的图归入 unevaluated、不重解码），分数一律重算——防止被注入提示词的 Agent 伪造预评分（想保留的打高分、想删的打低分）逐图指定删除集合。

```python
# 默认（安全）：传入 scored 仅复用损坏标记，分数重算
# → summary.scored_source == "engine_with_caller_errors"
cleanup_workspace_images(workspace="C:/my-photos", top=30, scored=prior_scores)

# 显式信任复用（需要与先前评分报告保持决策一致时）：
# → summary.scored_source == "caller"；scored 中分数须为有限值且落在 [0, 100]，
#   任一违反整体拒绝执行（code=4），不会静默钳制
cleanup_workspace_images(workspace="C:/my-photos", top=30, scored=prior_scores, trust_scored=True)
```

实际口径始终以 `summary.scored_source` 透明标注：`engine`（全量重算）/ `caller`（信任复用）/ `engine_with_caller_errors`（仅复用损坏标记）。

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
    "delete_failures": 0,
    "mode": "actual_delete",
    "scored_source": "engine",
    "elapsed_ms": 15420
  },
  "kept_images": [...],
  "deleted_files": ["img_001.jpg", "img_002.jpg", ...],
  "blocked_files": []
}
```

`blocked_files` 列出因安全检查被拦截的文件（路径在工作空间外等）。

**删除失败（非成功收场）**：个别图片删除失败（文件被其它程序占用、只读属性、与回收站
跨卷）时，返回 `status="partial"`、`code=5`，`summary.delete_failures` 给出未删除张数、
`details.delete_failures` 给出逐项 `{path, reason}`；其余图片照常处理，删除失败的低分图
仍留在磁盘上。全部删除成功时 `status="success"`、`code=0`，且 `summary.delete_failures`
显式为 `0`——两种 status 可统一读取同一键。等价 CLI `flashgaze cleanup` 用进程退出码 `5`
表达同一状态。

## 模式四：工作空间清理（CLI）

纯命令行用户也能用：把工作空间清理能力暴露为 `flashgaze cleanup` 子命令，
复用与 MCP 完全相同的评分 + 删除 + 安全校验逻辑（代码唯一来源 `flashgaze/core/cleanup.py`）。

> 兼容垫片：`flashgaze <目录> [flags]` 等价 `flashgaze score <目录> [flags]`，
> 原有目录评分入口零改动；显式 `flashgaze cleanup <目录>` 才进入清理模式。

### 安全保证（与 MCP 一致）

- **仅删除 workspace 目录内的文件**，绝不影响目录外任何资料
- **双重路径穿越检查**：解析真实路径后用 `relative_to` 校验，防止 `../` 或符号链接逃逸
- **默认 `--dry-run`**：只报告待删文件列表，**绝不默认删除**；显式 `--apply` 才真正 `unlink`
- **删除前再次校验**：每个文件删除前都重新 `stat`，拒绝符号链接/设备文件/目录（TOCTOU）

### 使用流程

```bash
# 第一步：试运行（默认），查看将要删除哪些文件，文件数 0 变化
flashgaze cleanup <图片目录路径> --top 30 --no-vlm --dry-run

# 第二步：确认后实际删除低分图（删除前会打印待删数量）
flashgaze cleanup <图片目录路径> --top 30 --no-vlm --apply
```

### 阈值模式

```bash
flashgaze cleanup <图片目录路径> --threshold 75 --no-vlm --dry-run
```

### 结构化输出（`--json`）

```bash
flashgaze cleanup <图片目录路径> --top 30 --no-vlm --json
```

返回 dict 含五段：`summary`（total/selected/to_delete/deleted/pending/blocked/unevaluated/mode/elapsed_ms）、
`pending_delete`（待删）、`deleted`（已删）、`blocked`（拦截：越界/非普通文件/stat失败/删除失败）、`unevaluated`（损坏图）。
`pending_delete` / `deleted` / `blocked` 每条记录含 `resolved_path`（检查点解析后的真实路径，即实际删除/回收的对象，
可用于区分 `..` 穿越与链接解析后逃逸）；批级拦截（guard / confirm_required）与 symlink_path（不解析）该字段为 `null`。

### CLI 子命令速查

| 子命令 | 说明 |
|---|---|
| `flashgaze <目录>` / `flashgaze score <目录>` | 目录评分（默认模式） |
| `flashgaze cleanup <目录>` | 工作空间清理（默认 `--dry-run`） |
| `--dry-run` / `--apply`（cleanup） | 互斥：试运行（默认） vs 实际删除 |
| `--json`（cleanup） | 结构化结果输出到 stdout |
| `--output PATH`（cleanup） | 报告写入文件（需搭配 --json） |

## MCP Server 配置

在 AI 工具的 MCP 配置中添加：

```json
{
  "mcpServers": {
    "flashgaze": {
      "command": "python",
      "args": ["-m", "flashgaze.mcp_server"],
      "env": {
        "FLASHGAZE_MCP_ALLOWED_ROOTS": "C:/photos,D:/uploads"
      }
    }
  }
}
```

`env` 字段可选：`FLASHGAZE_MCP_ALLOWED_ROOTS` 为逗号分隔的允许扫描根（上传/单图评分可读取的目录白名单）；未配置时默认仅限服务器启动目录内的图片。

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
| 1 | 参数错误（含 `--exif --no-exif-backup` 未加 `--force` 的护栏拦截） |
| 2 | API 调用失败（保留码：非致命时降级为 0——VLM 失败回退纯 CV） |
| 3 | 目录无效或无图片 |
| 4 | 图片处理错误（单图损坏/不支持等评分阶段失败，降级为 `error` 字段；BRISQUE 模型完整性校验失败终止整批时也返回本码） |
| 5 | 导出/删除失败（含部分失败：① 存在未能导出的入选图，CLI 退出码 5 / MCP `status="partial"`，见 `summary.export_failed` 与 `details.failures`；② 实际删除时存在删除失败的低分图，CLI 退出码 5 / MCP `status="partial"`，见 `summary.delete_failures` 与 `details.delete_failures`） |
| 6 | 配置错误（缺 API Key 且未 --no-vlm） |
| 7 | EXIF 写入失败（见 `summary.exif_failed`） |
| 8 | 未预期的内部错误（`main` 兜底：stderr 单行「未预期的内部错误（类型）: 信息」，无 traceback；堆栈需 `--verbose`） |

## Agent 调用要点

1. **stdout 取 JSON，stderr 取日志**：两个流互不污染，Agent 可靠解析
2. **先判返回码**：`returncode == 0` 才解析 stdout
3. **设超时**：大批量建议 `timeout=600` 秒
4. **可复现**：`--no-vlm` 模式下同一张图多次评分完全一致
5. **降级健壮**：单张图片损坏不中断，该图 `error` 字段记录原因，整体仍返回 0
6. **清理模式先 dry_run**：MCP 设 `dry_run=True` 确认待删文件列表，再 `dry_run=False` 执行；
   CLI 等价写法是 `flashgaze cleanup <目录> --dry-run` 先确认、`--apply` 再删除（CLI 默认即 dry-run，绝不默认删除）
7. **VLM 字段可能为空**：`vlm_reason` / `vlm_provider` 在 `--no-vlm` 或 VLM 失败时为空串，解析时需容错
8. **多 VLM 提供商路由**：全部 provider 默认走内置 pin-IP 直连层，无需额外依赖，litellm 缺失不影响默认路径；仅 opt-in LiteLLM 后端需要 `pip install -e ".[vlm-multi]"`

## CLI 选项速查

| 选项 | 说明 |
|---|---|
| `--top N` | 选前 N 张（默认 30） |
| `--threshold SCORE` | 分数阈值（替代 --top） |
| `--export` | 复制高分图到 ./精选/ |
| `--export-dir PATH` | 导出目标目录（默认 ./精选；需搭配 --export） |
| `--move` | 移动而非复制（需搭配 --export） |
| `--json` | JSON 输出到 stdout |
| `--csv` | CSV 输出 |
| `--no-vlm` | 纯 CV 模式（零成本） |
| `--vlm-provider PROVIDER` | VLM 提供商：`qwen`（默认）/ `openai` / `anthropic` / `ollama`。全部走内置 pin 直连层（无需 LiteLLM）；`.[vlm-multi]` 仅用于可选的 LiteLLM 后端 |
| `--scene SCENE` | 场景化评分模式：`auto`（默认）/ `portrait` / `landscape` / `still_life` |
| `--workers N` | 并发数（默认 4） |
| `--enable-composition` | 启用构图评分（实验性） |
| `--enable-noise` | 启用 BRISQUE 噪点评分（需 opencv-contrib-python；模型文件已随包分发） |
| `--enable-color` | 启用色彩丰富度评分（HSV 直方图分布） |
| `--enable-portrait` | 启用人像专项评分（需 face_recognition） |
| `cleanup <目录>` | CLI 工作空间清理子命令，默认 `--dry-run`；`--apply` 才删除 |
| `--dry-run` / `--apply` | cleanup 专用：试运行（默认） vs 实际删除 |
| `--enable-dedup` | 启用 PHash 图片去重（需 imagededup） |
| `--dedup-threshold N` | PHash 汉明距离阈值（默认 8，越小越严格） |
| `--weights JSON` | 自定义权重 JSON，可选 key：composition/noise/color |
| `--config-file PATH` | JSON 配置文件路径（与 `FLASHGAZE_CONFIG_FILE` 同层，显式传入的键优先） |
| `--api-key KEY` / `--api-key-file PATH` | VLM 密钥；文件版更安全（`-` 表示读 stdin），两者互斥（同传退出码 1） |
| `--api-base URL` / `--model NAME` | 覆盖 VLM 端点 / 模型名（优先级高于环境变量） |
| `--exif` | 将评分写回图片 EXIF（仅 JPEG/WebP，需 `.[exif]`） |
| `--no-exif-backup` | 跳过 `.flashgaze_backup` 原文件备份（危险，须配合 `--force`） |
| `--xlsx` / `--xlsx-output PATH` | 额外生成 `.xlsx` 评分表（需 `.[xlsx]`） |
| `--output PATH` / `--csv-output PATH` | JSON / CSV 清单写入文件（需分别搭配 `--json` / `--csv`） |
| `--enable-plugins` / `--plugin-dir PATH` | 启用插件评分阶段 / 追加插件目录（内置功能，无需 extra） |
| `--no-downscale` | 禁用大图降采样（默认长边超 2048px 时降采样） |

> 以上为高频选项速查；完整列表见 README 的「CLI 选项」章节。

## VLM 提供商

FlashGaze 通过**同一套自管 pin-IP 直连层**支持四个 VLM 提供商——**无任何厂商专属适配代码，且默认无需 LiteLLM**。所有 provider（qwen / openai / anthropic / ollama）在构造期解析并 **pin 单一 IP**，随后直连该 IP（固定 `Host` 头 + HTTPS SNI pin + `allow_redirects=False`），彻底消除 DNS 重绑定 TOCTOU 绕过面（含云元数据 `169.254.169.254` / 私网）。LiteLLM 仅作为**可选 opt-in 后端**（`VLMClient(use_litellm=True)`）用于特殊兼容场景。

| Provider | 模型示例 | API base | 是否需要 LiteLLM |
|---|---|---|---|
| `qwen`（默认） | `qwen-vl-max` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 否 |
| `openai` | `gpt-4o` | `https://api.openai.com/v1` | 否（内置 pin 直连层） |
| `anthropic` | `claude-3-5-sonnet-20241022` | `https://api.anthropic.com` | 否（内置 pin 直连层） |
| `ollama` | `llama3.2-vision` | `http://localhost:11434` | 否（内置 pin 直连层） |

> 直连层 Session 置 `trust_env=False`：`HTTP_PROXY` / `HTTPS_PROXY` 等代理变量不生效（构造期检测到时打一次 WARNING）。确需经代理访问 VLM 端点时，改用 opt-in 的 LiteLLM 后端（`VLMClient(use_litellm=True)`）。

### 环境变量配置示例

```bash
# 1. 通义千问（默认，100% 向后兼容——无需 LiteLLM）
export FLASHGAZE_VLM_PROVIDER=qwen
export FLASHGAZE_API_KEY=sk-xxxxxxxx
export FLASHGAZE_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
export FLASHGAZE_MODEL=qwen-vl-max

# 2. OpenAI GPT-4o（内置 pin 直连层，无需 LiteLLM）
export FLASHGAZE_VLM_PROVIDER=openai
export FLASHGAZE_API_KEY=sk-xxxxxxxx
export FLASHGAZE_API_BASE=https://api.openai.com/v1
export FLASHGAZE_MODEL=gpt-4o

# 3. Anthropic Claude 3（内置 pin 直连层；需显式提供 api_base）
export FLASHGAZE_VLM_PROVIDER=anthropic
export FLASHGAZE_API_KEY=sk-ant-xxxxxxxx
export FLASHGAZE_API_BASE=https://api.anthropic.com
export FLASHGAZE_MODEL=claude-3-5-sonnet-20241022

# 4. Ollama 本地 VLM（内置 pin 直连层，无需真实 key）
export FLASHGAZE_VLM_PROVIDER=ollama
export FLASHGAZE_API_KEY=ollama
export FLASHGAZE_API_BASE=http://localhost:11434
export FLASHGAZE_MODEL=llama3.2-vision

# 5. 配置文件（三入口一致生效）：指向 JSON 配置文件，CLI / MCP / Web GUI 均读取；
#    优先级低于上述各环境变量，与 CLI --config-file 同层（同时设置时 --config-file 的键优先）。
#    无默认路径探测，未设置即不加载；文件缺失/损坏记 WARNING 并回退默认值。
export FLASHGAZE_CONFIG_FILE=/path/to/config.json
```

### 端点白名单与密钥来源（H-6 / M-26）

- `api_base` 有四条互不校验的来源（环境变量 / JSON 配置文件 / CLI `--api-base` / WebUI 文本框），而 API Key 与全部图片内容都会被 POST 到它指向的主机。`build_config` 按白名单校验端点，**未覆盖时仅打 WARNING、不阻断运行**（警告含主机名、判定原因与处置建议），自托管场景不受影响。
- `FLASHGAZE_API_BASE_ALLOWLIST`：逗号分隔的主机后缀，用于追加内置官方域名（`dashscope.aliyuncs.com`、`dashscope-intl.aliyuncs.com`、`api.openai.com`、`api.anthropic.com`、`localhost`、`host.docker.internal`）。匹配口径为「主机相等，或以 `.条目` 结尾」，因此 `dashscope.aliyuncs.com.evil.com` **不会**误命中。
- `FLASHGAZE_ALLOW_UNTRUSTED_API_BASE=1`：声明当前端点已确认为可信，非白名单端点不再告警（自托管 / 自建网关场景）。
- 私网/回环主机在 `provider=ollama` 或 `FLASHGAZE_ALLOW_PRIVATE_TARGETS=true` 下免白名单校验（仍走 pin-IP 直连与 SSRF 防护）。
- Agent 调用 CLI 传密钥时优先用 `--api-key-file PATH`（`-` 表示从 stdin 读取），避免密钥进入进程命令行；它与 `--api-key` 互斥（同时提供时退出码 1）。

### 降级行为

- 未安装 `litellm`：默认 pin-IP 直连路径**不受影响**（litellm 非必需，任何 provider 均可正常调用）。仅当以 `VLMClient(use_litellm=True)` 显式启用 LiteLLM 后端且 litellm 未安装 / 调用失败时，VLM 调用返回 `ok=False`，`error="retry_exhausted"`，主流程自动回退纯 CV
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
| 噪点（BRISQUE） | `pip install -e ".[cv-enhanced]"`（模型文件已随包分发，缺失时才需手动放置或开启 `FLASHGAZE_BRISQUE_ALLOW_DOWNLOAD` 下载） | `--enable-noise` | 惩罚噪点多/压缩重的图片 |
| 色彩丰富度 | 内置（OpenCV） | `--enable-color` | 奖励色彩多样、饱和度高的图片 |
| 人像 | `pip install -e ".[portrait]"` | `--enable-portrait` | 加分含人脸的图，并校验人脸区域清晰度 |
| 去重 | `pip install -e ".[dedup]"` | `--enable-dedup` | 合并连拍相似图，仅保留最高分 |

启用 composition/noise/color 任一维度但未提供 `--weights` 时，会自动注入合理默认权重（如全启用 → sharpness 0.35 / exposure 0.25 / composition 0.20 / noise 0.10 / color 0.10）。
