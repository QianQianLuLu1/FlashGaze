[README.md](https://github.com/user-attachments/files/30011187/README.md)
<div align="center">

# FlashGaze

**瞬选灵眸 — AI-Assisted Local Image Scoring CLI**

Hybrid CV + VLM engine for scoring and filtering photos on your machine, designed for stable invocation by AI agents.

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-88%20passed-brightgreen.svg)](#testing)
[![Version](https://img.shields.io/badge/version-0.1.0-orange.svg)](#)

**[English](#english) · [中文](#中文)**

</div>

---

<!-- TOC -->
## Table of Contents

| | English | 中文 |
|---|---|---|
| Overview | [Why FlashGaze](#why-flashgaze) | [项目简介](#项目简介) |
| Features | [Key Features](#key-features) | [核心特性](#核心特性) |
| Architecture | [How It Works](#how-it-works) | [工作原理](#工作原理) |
| Install | [Installation](#installation) | [安装](#安装) |
| Usage | [Quick Start](#quick-start) | [快速开始](#快速开始) |
| CLI | [CLI Options](#cli-options) | [CLI 选项](#cli-选项) |
| MCP | [MCP Server](#mcp-server) | [MCP Server](#mcp-server-1) |
| Skill | [AI Agent Skill](#ai-agent-skill) | [AI Agent Skill](#ai-agent-skill-1) |
| Config | [Configuration](#configuration) | [配置](#配置) |
| Codes | [Exit Codes](#exit-codes) | [返回码](#返回码) |
| Test | [Testing](#testing) | [测试](#测试) |
| Stack | [Tech Stack](#tech-stack) | [技术栈](#技术栈) |

---

<!-- ==================== ENGLISH ==================== -->

# English

## Why FlashGaze

Picking the best shots from a folder of hundreds is tedious. FlashGaze automates it: a CV engine measures sharpness and exposure objectively, an optional VLM layer compensates for artistic intent (background blur, silhouette, low-key mood), and the result is a ranked, structured report you can pipe into any workflow.

## Key Features

- **Hybrid scoring engine** — CV objective score (Laplacian variance + histogram exposure) as the backbone, VLM scene-aware adjustment capped at ±10 points
- **Reproducible** — same image, same score, every run in `--no-vlm` mode (10/10 consistency verified)
- **Agent-friendly** — stdout carries clean JSON, stderr carries logs, standard exit codes, safe to call via `subprocess`
- **Zero-cost mode** — `--no-vlm` runs entirely offline with no API key required
- **MCP Server built-in** — callable directly from Claude Code, TRAE, Cursor, Codex, and any MCP-compatible tool
- **Graceful degradation** — a corrupted image gets `score=0` with an `error` field; VLM failure falls back to CV-only; neither interrupts the batch
- **Workspace cleanup** — in-place deletion of low-score images with path-traversal protection and `dry_run` safety default

## How It Works

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  Image Dir   │────▶│  CVEngine     │────▶│  HybridScorer    │
│ JPG/PNG/WebP │     │ · Sharpness   │     │  CV_score × w    │
└─────────────┘     │ · Exposure    │     │  + VLM ±adjust   │
                    │ · Composition  │     │  = Final 0-100   │
                    └──────┬───────┘     └────────┬────────┘
                           │                      │
                    ┌──────▼───────┐     ┌────────▼────────┐
                    │  VLMClient    │     │  Exporter        │
                    │ (optional)    │     │ · Copy / Move    │
                    │ Qwen-VL /     │     │ · JSON manifest  │
                    │ GPT-4o-mini   │     │ · CSV manifest   │
                    └──────────────┘     └─────────────────┘
```

**CV scoring dimensions:**

| Dimension | Method | Range |
|---|---|---|
| Sharpness | Laplacian variance, linear-mapped and capped at 500 | 0–100 |
| Exposure | Histogram mid-tone ratio (penalizes extreme dark/bright) | 0–100 |
| Composition | Rule of thirds via Otsu foreground centroid *(experimental)* | 0–100 |

Default weights: sharpness 50%, exposure 50%. Composition is opt-in via `--enable-composition`.

> **VLM compensation:** The VLM receives the image plus CV metrics and judges whether blur/darkness is an artistic choice or a technical flaw. It returns a signed adjustment clamped to ±10, which is added to the weighted CV score and clamped to 0–100.

## Installation

```bash
git clone https://github.com/QianQianLuLu1/FlashGaze.git
cd FlashGaze/flashgaze
pip install -e .
```

For MCP Server support:

```bash
pip install -e ".[mcp]"
```

> Requires Python 3.10+

## Quick Start

```bash
# Zero-cost quick scan (CV only, no API key needed)
flashgaze ./photos --top 30 --json --no-vlm

# Full hybrid scoring with VLM
export FLASHGAZE_API_KEY="sk-your-key"
flashgaze ./photos --top 30 --json

# Score and copy best photos to a folder
flashgaze ./photos --top 30 --json --export

# Threshold mode (score >= 75 selected)
flashgaze ./photos --threshold 75 --json --csv
```

<details>
<summary><b>Sample JSON output</b></summary>

```json
{
  "status": "success",
  "code": 0,
  "summary": {
    "total": 120,
    "selected": 30,
    "avg_score": 68.45,
    "elapsed_ms": 15420
  },
  "images": [
    {
      "file": "DSC_0042.jpg",
      "path": "/photos/DSC_0042.jpg",
      "sharpness": 92.5,
      "exposure": 88.0,
      "composition": null,
      "vlm_adjustment": 5.0,
      "score": 92.75,
      "selected": true,
      "error": null
    }
  ]
}
```

</details>

## CLI Options

| Option | Description |
|---|---|
| `--top N` | Select top N images by score (default 30) |
| `--threshold SCORE` | Score threshold, overrides `--top` |
| `--export` | Copy selected images to export directory |
| `--export-dir PATH` | Export destination (default `./精选`) |
| `--move` | Move instead of copy (use with `--export`) |
| `--json` | Output JSON report to stdout |
| `--csv` | Output CSV report |
| `--output PATH` | Write JSON report to file |
| `--csv-output PATH` | Write CSV report to file (default `flashgaze_result.csv`) |
| `--no-vlm` | Disable VLM, CV-only mode (zero API cost) |
| `--enable-composition` | Enable rule-of-thirds scoring *(experimental)* |
| `--workers N` | Concurrent threads (default 4) |
| `--config-file PATH` | Path to JSON config file |
| `--verbose` | Verbose logging to stderr |

## MCP Server

FlashGaze ships with a built-in MCP Server. After installing with `pip install -e ".[mcp]"`, add it to your AI tool's MCP configuration:

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

**MCP Tools:**

| Tool | Description |
|---|---|
| `score_images` | Batch-score all images in a directory |
| `score_single_image` | Score a single image with detailed metrics |
| `score_uploaded_images` | Score a list of image paths (no directory structure needed) |
| `export_selected_images` | Score and copy/move high-score images to a target directory |
| `cleanup_workspace_images` | Score and delete low-score images in-place (with `dry_run` safety) |

Once configured, you can ask your AI assistant directly:

> "Score the images in this folder" · "Pick the best 30 photos from this directory" · "Clean up low-quality images from my workspace"

<details>
<summary><b>Workspace Cleanup Safety</b></summary>

The `cleanup_workspace_images` tool enforces strict safety boundaries:

- All deletions are confined to the `workspace` directory — files outside are never touched
- Double path-traversal checks: resolved path validated via `relative_to` against workspace root
- `dry_run=True` by default — reports what would be deleted without actually deleting
- Re-validates each file's path boundary before deletion

</details>

## AI Agent Skill

FlashGaze includes `SKILL.md`, compatible with TRAE, Claude Code, Cursor, and any tool supporting the `agentskills.io` standard.

```bash
# Install via skills CLI
npx skills add QianQianLuLu1/FlashGaze

# Or manually copy SKILL.md to your tool's skills directory
```

<details>
<summary><b>Calling FlashGaze from Python</b></summary>

```python
import subprocess, json

result = subprocess.run(
    ["flashgaze", "./photos", "--top", "30", "--json", "--no-vlm"],
    capture_output=True, text=True, timeout=600
)
if result.returncode == 0:
    report = json.loads(result.stdout)
    for img in report["images"]:
        if img["selected"]:
            print(f"Selected: {img['file']} score={img['score']}")
```

</details>

## Configuration

Priority order: **CLI args** > **environment variables** > **config file** > **defaults**

<details>
<summary><b>Environment Variables</b></summary>

| Variable | Description | Default |
|---|---|---|
| `FLASHGAZE_API_KEY` | VLM API key (required unless `--no-vlm`) | — |
| `FLASHGAZE_API_BASE` | API endpoint | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `FLASHGAZE_MODEL` | Model name | `qwen-vl-max` |
| `FLASHGAZE_TIMEOUT` | Request timeout (seconds) | `30` |
| `FLASHGAZE_WORKERS` | Concurrent threads | `4` |
| `FLASHGAZE_MAX_RETRIES` | VLM retry count (timeout/connection only) | `3` |
| `FLASHGAZE_VLM_MAX_ADJUSTMENT` | VLM adjustment cap | `10.0` |

See `config.example.json` for the file-based config format. The `weights` field is only configurable via config file.

</details>

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Argument error |
| `2` | API failure *(reserved — VLM failure degrades to CV-only)* |
| `3` | Invalid directory or no images found |
| `4` | Image processing error *(reserved — single-image failure degrades to `error` field)* |
| `5` | Export failure |
| `6` | Configuration error (missing API key, etc.) |

> Codes 2 and 4 are reserved: VLM call failure degrades to CV-only with zero adjustment, and single-image corruption degrades to `score=0` with an `error` field. Neither interrupts the batch.

## Testing

```bash
pip install -r requirements-dev.txt
pytest -v
```

88 tests covering CV engine, VLM client, hybrid scorer, exporter, CLI parser, end-to-end flows, reproducibility, and config layers.

## Tech Stack

| Dependency | Role |
|---|---|
| Python 3.10+ | Runtime |
| OpenCV 4.x | CV scoring (Laplacian variance, histogram, Otsu thresholding) |
| Pillow | Image decoding fallback (WebP, corrupted JPEG) |
| NumPy | Array operations |
| requests | VLM API calls |
| mcp | MCP Server *(optional install)* |

---

<!-- ==================== CHINESE ==================== -->

# 中文

## 项目简介

从几百张照片里挑出最好的几张，这件事既费时又主观。FlashGaze 把它自动化：CV 引擎客观测量清晰度和曝光度，可选的 VLM 层判断模糊或偏暗是否属于艺术手法（背景虚化、逆光剪影、暗调氛围），最终输出一份排序好的结构化报告，可以直接接入任何工作流。

## 核心特性

- **混合评分引擎** — CV 客观分（拉普拉斯方差 + 直方图曝光度）主导，VLM 场景补偿上限 ±10 分
- **可复现** — `--no-vlm` 模式下同一张图连续运行 10 次分数完全一致
- **Agent 友好** — stdout 输出干净 JSON，stderr 输出日志，标准返回码，可通过 `subprocess` 稳定调用
- **零成本模式** — `--no-vlm` 完全离线运行，无需 API Key
- **内置 MCP Server** — 可被 Claude Code、TRAE、Cursor、Codex 等所有支持 MCP 的工具直接调用
- **优雅降级** — 损坏图片标记 `score=0` 并附带 `error` 字段；VLM 调用失败回退为纯 CV；两者均不中断批处理
- **工作空间清理** — 原地删除低分图片，含路径穿越防护和 `dry_run` 安全默认

## 工作原理

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  图片目录    │────▶│  CVEngine     │────▶│  HybridScorer    │
│ JPG/PNG/WebP│     │ · 清晰度      │     │  CV 加权分       │
└─────────────┘     │ · 曝光度      │     │  + VLM ±补偿     │
                    │ · 构图(实验)   │     │  = 最终分 0-100  │
                    └──────┬───────┘     └────────┬────────┘
                           │                      │
                    ┌──────▼───────┐     ┌────────▼────────┐
                    │  VLMClient    │     │  Exporter        │
                    │ (可选)        │     │ · 复制 / 移动    │
                    │ Qwen-VL /     │     │ · JSON 清单      │
                    │ GPT-4o-mini   │     │ · CSV 清单       │
                    └──────────────┘     └─────────────────┘
```

**CV 评分维度：**

| 维度 | 方法 | 范围 |
|---|---|---|
| 清晰度 | 拉普拉斯方差，线性映射，上限 500 封顶 | 0–100 |
| 曝光度 | 直方图中间调占比（惩罚极端暗/亮像素） | 0–100 |
| 构图 | 三分法，Otsu 阈值分割前景质心 *（实验性）* | 0–100 |

默认权重：清晰度 50%，曝光度 50%。构图通过 `--enable-composition` 启用。

> **VLM 补偿机制：** VLM 接收图片和 CV 指标，判断模糊或偏暗是艺术手法还是技术失误，返回一个 clamp 到 ±10 的有符号补偿值，叠加到 CV 加权分上并 clamp 到 0–100。

## 安装

```bash
git clone https://github.com/QianQianLuLu1/FlashGaze.git
cd FlashGaze/flashgaze
pip install -e .
```

如需 MCP Server 功能：

```bash
pip install -e ".[mcp]"
```

> 要求 Python 3.10+

## 快速开始

```bash
# 零成本快速初筛（仅 CV，无需 API Key）
flashgaze ./photos --top 30 --json --no-vlm

# VLM 精筛（需要 API Key）
export FLASHGAZE_API_KEY="sk-your-key"
flashgaze ./photos --top 30 --json

# 评分并复制高分图到新目录
flashgaze ./photos --top 30 --json --export

# 阈值模式（分数 >= 75 入选）
flashgaze ./photos --threshold 75 --json --csv
```

<details>
<summary><b>JSON 输出示例</b></summary>

```json
{
  "status": "success",
  "code": 0,
  "summary": {
    "total": 120,
    "selected": 30,
    "avg_score": 68.45,
    "elapsed_ms": 15420
  },
  "images": [
    {
      "file": "DSC_0042.jpg",
      "path": "/photos/DSC_0042.jpg",
      "sharpness": 92.5,
      "exposure": 88.0,
      "composition": null,
      "vlm_adjustment": 5.0,
      "score": 92.75,
      "selected": true,
      "error": null
    }
  ]
}
```

</details>

## CLI 选项

| 选项 | 说明 |
|---|---|
| `--top N` | 选取前 N 张高分图（默认 30） |
| `--threshold SCORE` | 分数阈值（替代 `--top`） |
| `--export` | 复制高分图至导出目录 |
| `--export-dir PATH` | 导出目标目录（默认 `./精选`） |
| `--move` | 移动而非复制（需配合 `--export`） |
| `--json` | 输出 JSON 清单到 stdout |
| `--csv` | 输出 CSV 清单 |
| `--output PATH` | JSON 清单输出到文件 |
| `--csv-output PATH` | CSV 清单输出路径（默认 `flashgaze_result.csv`） |
| `--no-vlm` | 禁用 VLM，仅用 CV（零 API 成本） |
| `--enable-composition` | 启用构图评分 *（实验性）* |
| `--workers N` | 并发线程数（默认 4） |
| `--config-file PATH` | JSON 配置文件路径 |
| `--verbose` | 详细日志（stderr） |

## MCP Server

FlashGaze 内置 MCP Server。安装 `pip install -e ".[mcp]"` 后，在 AI 工具的 MCP 配置中添加：

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

**MCP 工具列表：**

| 工具 | 功能 |
|---|---|
| `score_images` | 对目录下所有图片批量评分 |
| `score_single_image` | 评分单张图片，返回详细指标 |
| `score_uploaded_images` | 对指定路径列表的图片评分（不依赖目录结构） |
| `export_selected_images` | 评分后复制/移动高分图到目标目录 |
| `cleanup_workspace_images` | 评分后原地删除低分图（含 `dry_run` 安全模式） |

配置完成后，直接对 AI 助手说：

> "帮我评估这个目录里图片的质量" · "选出最好的 30 张照片" · "清理工作空间里质量差的图片"

<details>
<summary><b>工作空间清理安全机制</b></summary>

`cleanup_workspace_images` 工具强制执行严格的安全边界：

- 所有删除操作限制在 `workspace` 目录内，目录外文件绝不受影响
- 双重路径穿越检查：解析真实路径后通过 `relative_to` 校验是否在工作空间内
- 默认 `dry_run=True`，只报告待删文件列表，不实际删除
- 每个文件删除前再次校验路径边界

</details>

## AI Agent Skill

本项目包含 `SKILL.md`，兼容 TRAE、Claude Code、Cursor 等支持 `agentskills.io` 标准的工具。

```bash
# 通过 skills CLI 安装
npx skills add QianQianLuLu1/FlashGaze

# 或手动复制 SKILL.md 到对应工具的 skills 目录
```

<details>
<summary><b>从 Python 调用 FlashGaze</b></summary>

```python
import subprocess, json

result = subprocess.run(
    ["flashgaze", "./photos", "--top", "30", "--json", "--no-vlm"],
    capture_output=True, text=True, timeout=600
)
if result.returncode == 0:
    report = json.loads(result.stdout)
    for img in report["images"]:
        if img["selected"]:
            print(f"入选: {img['file']} 分数={img['score']}")
```

</details>

## 配置

优先级：**CLI 参数** > **环境变量** > **配置文件** > **默认值**

<details>
<summary><b>环境变量</b></summary>

| 变量 | 说明 | 默认值 |
|---|---|---|
| `FLASHGAZE_API_KEY` | VLM API Key（`--no-vlm` 模式不需要） | — |
| `FLASHGAZE_API_BASE` | API 端点 | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `FLASHGAZE_MODEL` | 模型名称 | `qwen-vl-max` |
| `FLASHGAZE_TIMEOUT` | 请求超时（秒） | `30` |
| `FLASHGAZE_WORKERS` | 并发线程数 | `4` |
| `FLASHGAZE_MAX_RETRIES` | VLM 重试次数（仅超时/连接错误） | `3` |
| `FLASHGAZE_VLM_MAX_ADJUSTMENT` | VLM 补偿上限 | `10.0` |

文件配置格式见 `config.example.json`。`weights` 字段仅支持配置文件设置。

</details>

## 返回码

| 码 | 含义 |
|---|---|
| `0` | 成功 |
| `1` | 参数错误 |
| `2` | API 调用失败 *（保留码 — VLM 失败已降级为纯 CV）* |
| `3` | 目录无效或无图片 |
| `4` | 图片处理错误 *（保留码 — 单图损坏已降级为 `error` 字段）* |
| `5` | 导出失败 |
| `6` | 配置错误（缺 API Key 等） |

> 码 2 与 4 为保留码：VLM 调用失败降级为纯 CV（补偿 0），单图损坏降级为该图 `error` 字段且 `score=0`，均不中断流程。

## 测试

```bash
pip install -r requirements-dev.txt
pytest -v
```

88 项测试，覆盖 CV 引擎、VLM 客户端、混合评分器、导出器、CLI 解析器、端到端流程、可复现性和配置层。

## 技术栈

| 依赖 | 用途 |
|---|---|
| Python 3.10+ | 运行时 |
| OpenCV 4.x | CV 评分（拉普拉斯方差、直方图、Otsu 阈值分割） |
| Pillow | 图片解码兜底（WebP、损坏 JPEG） |
| NumPy | 数组运算 |
| requests | VLM API 调用 |
| mcp | MCP Server *（可选安装）* |

---

<div align="center">

**MIT License**

</div>
