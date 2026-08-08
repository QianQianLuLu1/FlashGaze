<div align="center">

# FlashGaze

**瞬选灵眸 — AI-Assisted Local Image Scoring CLI**

Hybrid CV + VLM engine for scoring and filtering photos on your machine, designed for stable invocation by AI agents.

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-241%20passed-brightgreen.svg)](#testing)
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
| GUI | [Web GUI](#web-gui) | [Web GUI](#web-gui-1) |
| Skill | [AI Agent Skill](#ai-agent-skill) | [AI Agent Skill](#ai-agent-skill-1) |
| Config | [Configuration](#configuration) | [配置](#配置) |
| Codes | [Exit Codes](#exit-codes) | [返回码](#返回码) |
| Test | [Testing](#testing) | [测试](#测试) |
| Optional | [Optional Features](#optional-features) | [可选功能](#可选功能) |
| Stack | [Tech Stack](#tech-stack) | [技术栈](#技术栈) |

---

<!-- ==================== ENGLISH ==================== -->

# English

## Why FlashGaze

Picking the best shots from a folder of hundreds is tedious. FlashGaze automates it: a CV engine measures sharpness and exposure objectively, an optional VLM layer compensates for artistic intent (background blur, silhouette, low-key mood), and the result is a ranked, structured report you can pipe into any workflow.

## Key Features

- **Hybrid scoring engine** — CV objective score (Laplacian variance + histogram exposure) as the backbone, VLM scene-aware adjustment capped at ±10 points
- **Multi-VLM provider support** — Qwen-VL by default (zero new dependencies, 100% backward compatible); GPT-4o / Claude 3 / Ollama via LiteLLM unified layer, with no per-vendor adapter code
- **Score explainability** — every VLM adjustment carries a ≤20-character `vlm_reason` and a `vlm_provider` tag in CSV/JSON output
- **Scene-based scoring** — `--scene auto/portrait/landscape/still_life` applies differentiated prompts for each scene type
- **Reproducible** — same image, same score, every run in `--no-vlm` mode (10/10 consistency verified)
- **Agent-friendly** — stdout carries clean JSON, stderr carries logs, standard exit codes, safe to call via `subprocess`
- **Zero-cost mode** — `--no-vlm` runs entirely offline with no API key required
- **MCP Server built-in** — callable directly from Claude Code, TRAE, Cursor, Codex, and any MCP-compatible tool
- **Graceful degradation** — a corrupted image gets `score=0` with an `error` field; VLM failure falls back to CV-only; neither interrupts the batch
- **Workspace cleanup** — in-place deletion of low-score images with path-traversal protection and `dry_run` safety default
- **Optional CV enhancements** — four opt-in dimensions (noise / color / portrait / dedup) that default off and degrade gracefully when their dependencies are missing
- **EXIF write-back** — `--exif` writes the final score into image EXIF metadata (JPEG/TIFF only); install with `pip install -e ".[exif]"`
- **Excel export** — `--xlsx` emits a `.xlsx` scoring sheet (openpyxl) alongside JSON/CSV; install with `pip install -e ".[xlsx]"`
- **Plugin system** — `--enable-plugins` runs a discoverable plugin scoring stage (`flashgaze/plugins/builtin/` + `~/.flashgaze/plugins/` + `--plugin-dir`); no extra install required

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
                    │ GPT-4o /      │     │ · CSV manifest   │
                    │ Claude 3 /    │     │ · vlm_reason     │
                    │ Ollama        │     │ · vlm_provider   │
                    └──────────────┘     └─────────────────┘
```

**CV scoring dimensions:**

| Dimension | Method | Range | Default |
|---|---|---|---|
| Sharpness | Laplacian variance, linear-mapped and capped at 500 | 0–100 | on |
| Exposure | Histogram mid-tone ratio (penalizes extreme dark/bright) | 0–100 | on |
| Composition | Rule of thirds via Otsu foreground centroid *(experimental)* | 0–100 | off (`--enable-composition`) |
| Noise | BRISQUE no-reference IQA *(opencv-contrib-python)* | 0–100 | off (`--enable-noise`) |
| Color | HSV histogram entropy + saturation mean | 0–100 | off (`--enable-color`) |
| Portrait | face_recognition face count + face-region sharpness, +3~5 bonus | 0–5 bonus | off (`--enable-portrait`) |
| Dedup | PHash perceptual hash, keep highest-score per group | flag only | off (`--enable-dedup`) |

Default weights: sharpness 50%, exposure 50%. Composition is opt-in via `--enable-composition`. When optional dimensions are enabled without a user-supplied `--weights`, reasonable defaults are injected automatically (see `Optional CV Enhancements` below).

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

For optional CV enhancement dimensions (install only the ones you need):

```bash
pip install -e ".[cv-enhanced]"   # BRISQUE noise scoring (opencv-contrib-python)
pip install -e ".[portrait]"      # Portrait scoring (face_recognition)
pip install -e ".[dedup]"         # PHash deduplication (imagededup)
pip install -e ".[vlm-multi]"     # Multi-VLM providers via LiteLLM (GPT-4o / Claude 3 / Ollama)
pip install -e ".[gui]"           # Web GUI (Gradio) — run `flashgaze-webui` after install
pip install -e ".[all]"           # All of the above
pip install -e ".[exif]"   # EXIF write-back (piexif)
pip install -e ".[xlsx]"   # Excel export (openpyxl)
# Plugin support is built in — enable at runtime with --enable-plugins, no extra install needed
```

> Requires Python 3.10+. Missing optional dependencies degrade gracefully — the corresponding dimension returns `null`/`0`/`false` instead of erroring. `provider=qwen` (default) does NOT require LiteLLM.

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
      "error": null,
      "vlm_reason": "背景虚化突出主体",
      "vlm_provider": "qwen"
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
| `--exif` | Write final score back to image EXIF metadata (JPEG/TIFF only; requires `pip install -e ".[exif]"`) |
| `--no-exif-backup` | Skip creating the `.flashgaze_backup` original before writing EXIF |
| `--xlsx` | Also emit a `.xlsx` scoring sheet (requires `pip install -e ".[xlsx]"`) |
| `--xlsx-output PATH` | `.xlsx` output path (default `flashgaze_result.xlsx`) |
| `--enable-plugins` | Enable the plugin scoring stage (auto-discovers builtin + user plugin dirs) |
| `--plugin-dir PATH` | Additional plugin directory merged with builtin and user dirs |
| `--no-vlm` | Disable VLM, CV-only mode (zero API cost) |
| `--vlm-provider PROVIDER` | VLM provider: `qwen` (default) / `openai` / `anthropic` / `ollama`. Non-`qwen` requires `pip install -e ".[vlm-multi]"` |
| `--scene SCENE` | Scene-based scoring mode: `auto` (default) / `portrait` / `landscape` / `still_life` |
| `--enable-composition` | Enable rule-of-thirds scoring *(experimental)* |
| `--enable-noise` | Enable BRISQUE no-reference noise scoring *(requires opencv-contrib-python + model files)* |
| `--enable-color` | Enable HSV color richness scoring |
| `--enable-portrait` | Enable portrait scoring (face count + face-region sharpness, +3~5 bonus) *(requires face_recognition)* |
| `--enable-dedup` | Enable PHash deduplication (similar images keep only the highest score) *(requires imagededup)* |
| `--dedup-threshold N` | PHash hamming distance threshold (default 8, lower is stricter) |
| `--weights JSON` | Custom weight JSON, e.g. `'{"sharpness":0.5,"exposure":0.3,"composition":0.2}'`; optional keys: `composition`/`noise`/`color` |
| `--workers N` | Concurrent threads (default 4) |
| `--config-file PATH` | Path to JSON config file |
| `--verbose` | Verbose logging to stderr |
| `--no-downscale` | Disable downscaling of large images; process at original resolution (default: downscale when long edge > 2048px) |
| `--api-key KEY` | VLM API key (overrides env var) |
| `--api-base URL` | VLM API base endpoint (overrides env var) |
| `--model NAME` | VLM model name (overrides env var) |
| `--version` | Show program version and exit |

## VLM Providers

FlashGaze supports four VLM providers through a unified LiteLLM layer — **no per-vendor adapter code**. `qwen` (default) uses the original `requests.post` path with zero new dependencies; the other three go through LiteLLM (`pip install -e ".[vlm-multi]"`).

| Provider | Model example | API base | Requires LiteLLM |
|---|---|---|---|
| `qwen` (default) | `qwen-vl-max` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | No |
| `openai` | `gpt-4o` | `https://api.openai.com/v1` | Yes |
| `anthropic` | `claude-3-5-sonnet-20241022` | *(leave empty for LiteLLM default)* | Yes |
| `ollama` | `llama3.2-vision` | `http://localhost:11434` | Yes |

**Configuration examples:**

```bash
# 1. Qwen-VL (default, 100% backward compatible — no LiteLLM needed)
export FLASHGAZE_VLM_PROVIDER=qwen
export FLASHGAZE_API_KEY=sk-xxxxxxxx
export FLASHGAZE_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
export FLASHGAZE_MODEL=qwen-vl-max

# 2. OpenAI GPT-4o (requires LiteLLM)
export FLASHGAZE_VLM_PROVIDER=openai
export FLASHGAZE_API_KEY=sk-xxxxxxxx
export FLASHGAZE_API_BASE=https://api.openai.com/v1
export FLASHGAZE_MODEL=gpt-4o

# 3. Anthropic Claude 3 (requires LiteLLM, leave api_base empty for LiteLLM default)
export FLASHGAZE_VLM_PROVIDER=anthropic
export FLASHGAZE_API_KEY=sk-ant-xxxxxxxx
export FLASHGAZE_API_BASE=
export FLASHGAZE_MODEL=claude-3-5-sonnet-20241022

# 4. Ollama local VLM (requires LiteLLM, no real key needed)
export FLASHGAZE_VLM_PROVIDER=ollama
export FLASHGAZE_API_KEY=ollama
export FLASHGAZE_API_BASE=http://localhost:11434
export FLASHGAZE_MODEL=llama3.2-vision
```

**Graceful degradation:** If LiteLLM is not installed but `provider != qwen`, the VLM call returns `ok=False` with `error="litellm_not_installed"` and the batch continues in CV-only mode. Invalid `provider`/`scene` values fall back to defaults with a warning.

## Scene-based Scoring

The `--scene` flag switches the VLM prompt to focus on scene-specific artistic techniques. `auto` (default) lets the VLM judge the scene itself, matching the original single-prompt behavior.

| Scene | When to use | What the prompt emphasizes |
|---|---|---|
| `auto` (default) | Mixed folder, unknown content | VLM judges the scene itself; identical semantics to the original single prompt |
| `portrait` | People / headshots / street portraits | Background blur as artistic choice; face-region sharpness |
| `landscape` | Scenery / nature / architecture | Long-exposure water/clouds; silhouette; low-key mood |
| `still_life` | Product / food / flat-lay | Depth-of-field control; lighting mood; dark-textured quality |

```bash
# Score a portrait folder with scene-aware prompts
flashgaze ./portraits --scene portrait --top 20 --json

# Score a landscape folder
flashgaze ./landscapes --scene landscape --top 30 --json
```

## Explainability

Every VLM-adjusted image carries two extra fields in both JSON and CSV output:

- `vlm_reason` — a ≤20-character Chinese reason from the VLM (e.g. `背景虚化`, `逆光剪影`, `技术失误`). Empty string when `--no-vlm` or VLM failure.
- `vlm_provider` — the provider that produced the adjustment (e.g. `qwen`, `openai`). Empty string when `--no-vlm` or VLM failure.

```json
{
  "file": "DSC_0042.jpg",
  "score": 92.75,
  "vlm_adjustment": 5.0,
  "vlm_reason": "背景虚化突出主体",
  "vlm_provider": "qwen"
}
```

The reason is hard-clamped to 20 characters (by character count, not byte count) and the adjustment is clamped to ±`vlm_max_adjustment` (default ±10). Malformed VLM responses degrade to `vlm_adjustment=0.0` with empty reason/provider, never raising an exception.

## Optional CV Enhancements

All four enhancement dimensions are **off by default** and degrade gracefully when their dependencies are missing — no error is raised, the corresponding field simply returns `null`/`0`/`false`. Install only what you need:

| Dimension | Install | Use Case |
|---|---|---|
| Noise (BRISQUE) | `pip install -e ".[cv-enhanced]"` + download BRISQUE model files into `flashgaze/models/brisque/` (see `flashgaze/models/brisque/README.md`) | Penalize noisy/compressed images |
| Color richness | Built-in (OpenCV) | Reward diverse, saturated color palettes |
| Portrait | `pip install -e ".[portrait]"` | Boost images containing faces; verify face-region sharpness |
| Dedup | `pip install -e ".[dedup]"` | Collapse near-duplicate bursts, keep only the highest score |

**Weight auto-injection:** When you enable any of `composition`/`noise`/`color` without supplying `--weights`, FlashGaze automatically injects a reasonable default weighting (e.g. full-enable → `sharpness 0.35 / exposure 0.25 / composition 0.20 / noise 0.10 / color 0.10`). Supply `--weights` to override.

## Optional Features

Every optional capability is off by default and degrades gracefully when its dependency is missing. Install only what you need:

| Extra | Install | Enable | What it adds | Details |
|---|---|---|---|---|
| `mcp` | `pip install -e ".[mcp]"` | built-in after install | MCP Server for AI tools | [MCP Server](#mcp-server) |
| `cv-enhanced` | `pip install -e ".[cv-enhanced]"` | `--enable-noise` | BRISQUE noise scoring | [Optional CV Enhancements](#optional-cv-enhancements) |
| `portrait` | `pip install -e ".[portrait]"` | `--enable-portrait` | Face-based portrait bonus | same as above |
| `dedup` | `pip install -e ".[dedup]"` | `--enable-dedup` | PHash deduplication | same as above |
| `vlm-multi` | `pip install -e ".[vlm-multi]"` | `--vlm-provider` non-`qwen` | GPT-4o / Claude 3 / Ollama | [VLM Providers](#vlm-providers) |
| `gui` | `pip install -e ".[gui]"` | `flashgaze-webui` | Browser-based GUI | [Web GUI](#web-gui) |
| `exif` | `pip install -e ".[exif]"` | `--exif` (`--no-exif-backup`) | Write score into image EXIF (JPEG/TIFF) | [CLI Options](#cli-options) |
| `xlsx` | `pip install -e ".[xlsx]"` | `--xlsx` (`--xlsx-output`) | Emit `.xlsx` scoring sheet | [CLI Options](#cli-options) |
| _plugins_ | built-in, no extra | `--enable-plugins` (`--plugin-dir`) | Discoverable plugin scoring stage | [CLI Options](#cli-options) |
| `all` | `pip install -e ".[all]"` | all of the above | Install everything | — |

**EXIF write-back** (`pip install -e ".[exif]"`): `--exif` stores the final 0–100 score (and selected flag) into the image's EXIF `UserComment`/rating tags. JPEG/TIFF only; pass `--no-exif-backup` to skip the `.flashgaze_backup` copy.

**Excel export** (`pip install -e ".[xlsx]"`): `--xlsx` produces `flashgaze_result.xlsx` (override path with `--xlsx-output`) with the same columns as the CSV report.

**Plugin system** (built in): `--enable-plugins` runs a scoring stage that auto-discovers `flashgaze/plugins/builtin/` and `~/.flashgaze/plugins/`; `--plugin-dir` adds an extra directory. No `pip` extra required.

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

## Web GUI

FlashGaze ships with an optional browser-based GUI built on Gradio. It mirrors every CLI parameter in the interface and reuses the same `HybridScorer` scoring path — no separate scoring logic is introduced.

**Install and launch:**

```bash
pip install -e ".[gui]"
flashgaze-webui
```

Open `http://127.0.0.1:7860` in your browser. The GUI defaults to localhost-only; pass `--host 0.0.0.0` for LAN access.

**CLI flags:**

| Flag | Description |
|---|---|
| `--host HOST` | Listen address (default `127.0.0.1`; use `0.0.0.0` for LAN) |
| `--port PORT` | Listen port (default `7860`) |
| `--dir PATH` | Pre-fill the directory input (does not auto-start scoring) |
| `--share` | Enable Gradio temporary public link |
| `--version` | Print version and exit |

```bash
# Pre-fill a directory and listen on port 8080
flashgaze-webui --dir ./photos --port 8080

# LAN access
flashgaze-webui --host 0.0.0.0 --port 8080
```

**Interface layout:**

1. **Directory & basic params** — directory, `--top`, `--threshold`, `--scene`, `--no-vlm`
2. **CV enhancement dimensions** — composition / noise / color / portrait / dedup / `--no-downscale`
3. **Weights** — five sliders (sharpness / exposure / composition / noise / color); auto-normalized by `build_config`
4. **VLM config** — `--vlm-provider`, API key, `--api-base`, `--model`, `--workers` (disabled when `--no-vlm` is checked)
5. **Scoring results** — summary JSON + sortable dataframe (same columns as CSV)
6. **High-score gallery** — thumbnails sorted by score, with captions showing score / selected mark / VLM reason
7. **Filter** — filter table & gallery by selected / min score / keyword (does not affect export)
8. **Export** — copy/move to directory (`--export`), download JSON (`--json`), download CSV (`--csv`)

**Offline mode:** checking "禁用 VLM (纯离线 CV 评分)" runs the entire scoring pipeline with no API key required — identical to `flashgaze --no-vlm`. VLM config inputs are disabled in this mode to avoid invalid configurations.

**Determinism:** the GUI calls the same `build_config` → `HybridScorer.score_paths` chain as the CLI, so the same directory with the same parameters produces byte-identical scores.

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
| `FLASHGAZE_VLM_PROVIDER` | VLM provider: `qwen`/`openai`/`anthropic`/`ollama` | `qwen` |
| `FLASHGAZE_SCENE` | Scene mode: `auto`/`portrait`/`landscape`/`still_life` | `auto` |
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

241 passed / 21 skipped (262 total) covering CV engine, VLM client, hybrid scorer, exporter, CLI parser, end-to-end flows, reproducibility, and config layers.

## Tech Stack

| Dependency | Role |
|---|---|
| Python 3.10+ | Runtime |
| OpenCV 4.x | CV scoring (Laplacian variance, histogram, Otsu thresholding) |
| Pillow | Image decoding fallback (WebP, corrupted JPEG) |
| NumPy | Array operations |
| requests | VLM API calls (Qwen-VL / OpenAI-compatible endpoints) |
| litellm | Multi-VLM unified layer (GPT-4o / Claude 3 / Ollama) *(optional install)* |
| mcp | MCP Server *(optional install)* |

---

<!-- ==================== CHINESE ==================== -->

# 中文

## 项目简介

从几百张照片里挑出最好的几张，这件事既费时又主观。FlashGaze 把它自动化：CV 引擎客观测量清晰度和曝光度，可选的 VLM 层判断模糊或偏暗是否属于艺术手法（背景虚化、逆光剪影、暗调氛围），最终输出一份排序好的结构化报告，可以直接接入任何工作流。

## 核心特性

- **混合评分引擎** — CV 客观分（拉普拉斯方差 + 直方图曝光度）主导，VLM 场景补偿上限 ±10 分
- **多 VLM 提供商支持** — 默认通义千问 Qwen-VL（零新依赖，100% 向后兼容）；GPT-4o / Claude 3 / Ollama 通过 LiteLLM 统一调用层，无任何厂商专属适配代码
- **评分可解释性** — 每次 VLM 补偿都附带 ≤20 字的 `vlm_reason` 与 `vlm_provider` 标识，写入 CSV/JSON 输出
- **场景化评分** — `--scene auto/portrait/landscape/still_life` 针对不同场景使用差异化提示词
- **可复现** — `--no-vlm` 模式下同一张图连续运行 10 次分数完全一致
- **Agent 友好** — stdout 输出干净 JSON，stderr 输出日志，标准返回码，可通过 `subprocess` 稳定调用
- **零成本模式** — `--no-vlm` 完全离线运行，无需 API Key
- **内置 MCP Server** — 可被 Claude Code、TRAE、Cursor、Codex 等所有支持 MCP 的工具直接调用
- **优雅降级** — 损坏图片标记 `score=0` 并附带 `error` 字段；VLM 调用失败回退为纯 CV；两者均不中断批处理
- **工作空间清理** — 原地删除低分图片，含路径穿越防护和 `dry_run` 安全默认
- **可选 CV 增强维度** — 噪点 / 色彩 / 人像 / 去重四类可选维度，默认全部关闭，依赖缺失时优雅降级
- **EXIF 写回** — `--exif` 将最终评分写回图片 EXIF 元数据（仅 JPEG/TIFF），需 `pip install -e ".[exif]"`
- **Excel 清单导出** — `--xlsx` 额外生成 `.xlsx` 评分表（openpyxl），需 `pip install -e ".[xlsx]"`
- **插件系统** — `--enable-plugins` 启用可发现式插件评分阶段（`flashgaze/plugins/builtin/` + `~/.flashgaze/plugins/` + `--plugin-dir`），无需额外安装

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
                    │ GPT-4o /      │     │ · CSV 清单       │
                    │ Claude 3 /    │     │ · vlm_reason     │
                    │ Ollama        │     │ · vlm_provider   │
                    └──────────────┘     └─────────────────┘
```

**CV 评分维度：**

| 维度 | 方法 | 范围 | 默认 |
|---|---|---|---|
| 清晰度 | 拉普拉斯方差，线性映射，上限 500 封顶 | 0–100 | 开 |
| 曝光度 | 直方图中间调占比（惩罚极端暗/亮像素） | 0–100 | 开 |
| 构图 | 三分法，Otsu 阈值分割前景质心 *（实验性）* | 0–100 | 关（`--enable-composition`） |
| 噪点 | BRISQUE 无参考 IQA *（opencv-contrib-python）* | 0–100 | 关（`--enable-noise`） |
| 色彩 | HSV 直方图熵 + 饱和度均值 | 0–100 | 关（`--enable-color`） |
| 人像 | face_recognition 人脸数 + 人脸区域清晰度，加分 +3~5 | 0–5 加分 | 关（`--enable-portrait`） |
| 去重 | PHash 感知哈希，每组保留最高分 | 仅标记 | 关（`--enable-dedup`） |

默认权重：清晰度 50%，曝光度 50%。构图通过 `--enable-composition` 启用。当启用可选维度但未提供 `--weights` 时，会自动注入合理默认权重（详见下方"可选 CV 增强维度"章节）。

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

如需可选 CV 增强维度（按需安装）：

```bash
pip install -e ".[cv-enhanced]"   # BRISQUE 噪点评分（opencv-contrib-python）
pip install -e ".[portrait]"      # 人像评分（face_recognition）
pip install -e ".[dedup]"         # PHash 去重（imagededup）
pip install -e ".[vlm-multi]"     # 多 VLM 提供商（LiteLLM，支持 GPT-4o / Claude 3 / Ollama）
pip install -e ".[gui]"           # Web GUI（基于 Gradio），安装后运行 flashgaze-webui
pip install -e ".[all]"           # 一次性安装以上全部
pip install -e ".[exif]"   # EXIF 写回（piexif）
pip install -e ".[xlsx]"   # Excel 清单导出（openpyxl）
# 插件系统为内置功能，无需 extra，运行时加 --enable-plugins 即可
```

> 要求 Python 3.10+。可选依赖缺失时不会报错，对应维度返回 `null`/`0`/`false`。`provider=qwen`（默认）不需要安装 LiteLLM。

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
      "error": null,
      "vlm_reason": "背景虚化突出主体",
      "vlm_provider": "qwen"
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
| `--exif` | 将最终评分写回图片 EXIF 元数据（仅 JPEG/TIFF；需 `pip install -e ".[exif]"`） |
| `--no-exif-backup` | 写 EXIF 时不创建 `.flashgaze_backup` 原文件备份 |
| `--xlsx` | 额外生成 `.xlsx` 评分表（需 `pip install -e ".[xlsx]"`） |
| `--xlsx-output PATH` | `.xlsx` 输出路径（默认 `flashgaze_result.xlsx`） |
| `--enable-plugins` | 启用插件评分阶段（自动发现内置与用户插件目录） |
| `--plugin-dir PATH` | 额外插件目录，与内置及用户目录合并发现 |
| `--no-vlm` | 禁用 VLM，仅用 CV（零 API 成本） |
| `--vlm-provider 提供商` | VLM 提供商：`qwen`（默认）/ `openai` / `anthropic` / `ollama`。非 qwen 需 `pip install -e ".[vlm-multi]"` |
| `--scene 场景` | 场景化评分模式：`auto`（默认）/ `portrait` / `landscape` / `still_life` |
| `--enable-composition` | 启用构图评分 *（实验性）* |
| `--enable-noise` | 启用 BRISQUE 无参考噪点评分 *（需 opencv-contrib-python + 模型文件）* |
| `--enable-color` | 启用色彩丰富度评分 |
| `--enable-portrait` | 启用人像专项评分（人脸数 + 区域清晰度，加分 +3~5） *（需 face_recognition）* |
| `--enable-dedup` | 启用 PHash 图片去重（相似图保留最高分） *（需 imagededup）* |
| `--dedup-threshold N` | PHash 汉明距离阈值（默认 8，越小越严格） |
| `--weights JSON` | 自定义权重 JSON，如 `'{"sharpness":0.5,"exposure":0.3,"composition":0.2}'`，可选 key：`composition`/`noise`/`color` |
| `--workers N` | 并发线程数（默认 4） |
| `--config-file PATH` | JSON 配置文件路径 |
| `--verbose` | 详细日志（stderr） |
| `--no-downscale` | 禁用大图降采样，使用原始分辨率处理（默认长边超 2048px 时降采样以降低内存占用） |
| `--api-key KEY` | VLM API Key（覆盖环境变量） |
| `--api-base URL` | VLM 端点（覆盖环境变量） |
| `--model NAME` | VLM 模型名称（覆盖环境变量） |
| `--version` | 显示版本号并退出 |

## VLM 提供商

FlashGaze 通过 LiteLLM 统一层支持四个 VLM 提供商——**无任何厂商专属适配代码**。`qwen`（默认）走原 `requests.post` 路径，零新依赖；其他三个走 LiteLLM（`pip install -e ".[vlm-multi]"`）。

| 提供商 | 模型示例 | API 端点 | 是否需要 LiteLLM |
|---|---|---|---|
| `qwen`（默认） | `qwen-vl-max` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 否 |
| `openai` | `gpt-4o` | `https://api.openai.com/v1` | 是 |
| `anthropic` | `claude-3-5-sonnet-20241022` | *（留空走 LiteLLM 默认端点）* | 是 |
| `ollama` | `llama3.2-vision` | `http://localhost:11434` | 是 |

**配置示例：**

```bash
# 1. 通义千问（默认，100% 向后兼容——无需 LiteLLM）
export FLASHGAZE_VLM_PROVIDER=qwen
export FLASHGAZE_API_KEY=sk-xxxxxxxx
export FLASHGAZE_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
export FLASHGAZE_MODEL=qwen-vl-max

# 2. OpenAI GPT-4o（需安装 LiteLLM）
export FLASHGAZE_VLM_PROVIDER=openai
export FLASHGAZE_API_KEY=sk-xxxxxxxx
export FLASHGAZE_API_BASE=https://api.openai.com/v1
export FLASHGAZE_MODEL=gpt-4o

# 3. Anthropic Claude 3（需安装 LiteLLM，api_base 留空走 LiteLLM 默认端点）
export FLASHGAZE_VLM_PROVIDER=anthropic
export FLASHGAZE_API_KEY=sk-ant-xxxxxxxx
export FLASHGAZE_API_BASE=
export FLASHGAZE_MODEL=claude-3-5-sonnet-20241022

# 4. Ollama 本地 VLM（需安装 LiteLLM，无需真实 key）
export FLASHGAZE_VLM_PROVIDER=ollama
export FLASHGAZE_API_KEY=ollama
export FLASHGAZE_API_BASE=http://localhost:11434
export FLASHGAZE_MODEL=llama3.2-vision
```

**优雅降级：** 若未安装 LiteLLM 但 `provider != qwen`，VLM 调用返回 `ok=False`（`error="litellm_not_installed"`），批处理继续以纯 CV 模式完成。非法 `provider`/`scene` 值回退到默认值并记 warning。

## 场景化评分

`--scene` 参数切换 VLM 提示词，聚焦不同场景的艺术手法。`auto`（默认）由 VLM 自行判断场景，与原版单一提示词语义一致。

| 场景 | 适用场景 | 提示词侧重点 |
|---|---|---|
| `auto`（默认） | 混合目录、内容未知 | VLM 自行判断场景；与原版单一提示词语义一致 |
| `portrait` | 人像 / 头像 / 街拍人像 | 背景虚化作为艺术手法；人脸区域清晰度 |
| `landscape` | 风光 / 自然 / 建筑 | 长曝光流水/云层；剪影；暗调氛围 |
| `still_life` | 产品 / 美食 / 静物摆拍 | 景深控制；布光氛围；暗调质感 |

```bash
# 用场景化提示词评分人像目录
flashgaze ./portraits --scene portrait --top 20 --json

# 评分风光目录
flashgaze ./landscapes --scene landscape --top 30 --json
```

## 评分可解释性

每张经 VLM 补偿的图片在 JSON 与 CSV 输出中都会附带两个新字段：

- `vlm_reason` — VLM 返回的 ≤20 字中文理由（如 `背景虚化`、`逆光剪影`、`技术失误`）。`--no-vlm` 模式或 VLM 失败时为空串。
- `vlm_provider` — 产生该补偿的提供商标识（如 `qwen`、`openai`）。`--no-vlm` 模式或 VLM 失败时为空串。

```json
{
  "file": "DSC_0042.jpg",
  "score": 92.75,
  "vlm_adjustment": 5.0,
  "vlm_reason": "背景虚化突出主体",
  "vlm_provider": "qwen"
}
```

理由按字符数硬截断到 20 字（不按字节），补偿值 clamp 到 ±`vlm_max_adjustment`（默认 ±10）。VLM 返回格式异常时降级为 `vlm_adjustment=0.0`、reason/provider 为空串，绝不抛异常。

## 可选 CV 增强维度

四个增强维度**默认全部关闭**，依赖缺失时优雅降级——不报错，对应字段返回 `null`/`0`/`false`。按需安装：

| 维度 | 安装命令 | 适用场景 |
|---|---|---|
| 噪点（BRISQUE） | `pip install -e ".[cv-enhanced]"` + 下载 BRISQUE 模型文件至 `flashgaze/models/brisque/`（详见 `flashgaze/models/brisque/README.md`） | 惩罚噪点多/压缩重的图片 |
| 色彩丰富度 | 内置（OpenCV） | 奖励色彩多样、饱和度高的图片 |
| 人像 | `pip install -e ".[portrait]"` | 加分含人脸的图，并校验人脸区域清晰度 |
| 去重 | `pip install -e ".[dedup]"` | 合并连拍相似图，仅保留最高分 |

**权重自动注入：** 当启用 `composition`/`noise`/`color` 任意维度但未提供 `--weights` 时，FlashGaze 会自动注入合理默认权重（如全启用 → `sharpness 0.35 / exposure 0.25 / composition 0.20 / noise 0.10 / color 0.10`）。可通过 `--weights` 覆盖。

## 可选功能

所有可选能力默认关闭，依赖缺失时优雅降级。按需安装：

| Extra | 安装 | 启用 | 新增能力 | 详见 |
|---|---|---|---|---|
| `mcp` | `pip install -e ".[mcp]"` | 安装后即内置 | 面向 AI 工具的 MCP Server | [MCP Server](#mcp-server) |
| `cv-enhanced` | `pip install -e ".[cv-enhanced]"` | `--enable-noise` | BRISQUE 噪点评分 | [可选 CV 增强维度](#可选-cv-增强维度) |
| `portrait` | `pip install -e ".[portrait]"` | `--enable-portrait` | 人脸人像加分 | 同上 |
| `dedup` | `pip install -e ".[dedup]"` | `--enable-dedup` | PHash 去重 | 同上 |
| `vlm-multi` | `pip install -e ".[vlm-multi]"` | `--vlm-provider` 非 `qwen` | GPT-4o / Claude 3 / Ollama | [VLM 提供商](#vlm-提供商) |
| `gui` | `pip install -e ".[gui]"` | `flashgaze-webui` | 浏览器 GUI | [Web GUI](#web-gui) |
| `exif` | `pip install -e ".[exif]"` | `--exif`（`--no-exif-backup`） | 评分写回图片 EXIF（JPEG/TIFF） | [CLI 选项](#cli-选项) |
| `xlsx` | `pip install -e ".[xlsx]"` | `--xlsx`（`--xlsx-output`） | 生成 `.xlsx` 评分表 | [CLI 选项](#cli-选项) |
| _插件_ | 内置，无 extra | `--enable-plugins`（`--plugin-dir`） | 可发现式插件评分阶段 | [CLI 选项](#cli-选项) |
| `all` | `pip install -e ".[all]"` | 以上全部 | 一次性全装 | — |

**EXIF 写回**（`pip install -e ".[exif]"`）：`--exif` 将最终 0–100 分（及入选标记）写入图片 EXIF 的 `UserComment`/评分标签。仅 JPEG/TIFF；加 `--no-exif-backup` 可跳过 `.flashgaze_backup` 原文件备份。

**Excel 导出**（`pip install -e ".[xlsx]"`）：`--xlsx` 生成 `flashgaze_result.xlsx`（用 `--xlsx-output` 改路径），列与 CSV 报告一致。

**插件系统**（内置）：`--enable-plugins` 启用插件评分阶段，自动发现 `flashgaze/plugins/builtin/` 与 `~/.flashgaze/plugins/`；`--plugin-dir` 追加额外目录。无需 `pip` extra。

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

## Web GUI

FlashGaze 提供基于 Gradio 的可选 Web GUI，把 CLI 的全部参数映射到界面控件，评分调用复用同一套 `HybridScorer`，不引入任何新的评分代码路径。

**安装与启动：**

```bash
pip install -e ".[gui]"
flashgaze-webui
```

浏览器访问 `http://127.0.0.1:7860`。默认仅本机可访问，局域网访问需显式传 `--host 0.0.0.0`。

**启动参数：**

| 参数 | 说明 |
|---|---|
| `--host HOST` | 监听地址（默认 `127.0.0.1`；局域网访问用 `0.0.0.0`） |
| `--port PORT` | 监听端口（默认 `7860`） |
| `--dir PATH` | 预填图片目录（仅填入输入框，不自动开始评分） |
| `--share` | 启用 Gradio 临时公网链接 |
| `--version` | 打印版本号并退出 |

```bash
# 预填目录并使用 8080 端口
flashgaze-webui --dir ./photos --port 8080

# 局域网访问
flashgaze-webui --host 0.0.0.0 --port 8080
```

**界面区块：**

1. **目录与基础参数** — 目录、`--top`、`--threshold`、`--scene`、`--no-vlm`
2. **CV 增强维度** — 构图 / 噪点 / 色彩 / 人像 / 去重 / `--no-downscale`
3. **权重** — 五维滑块（清晰度 / 曝光 / 构图 / 噪点 / 色彩），由 `build_config` 自动归一化
4. **VLM 配置** — `--vlm-provider`、API Key、`--api-base`、`--model`、`--workers`（勾选「禁用 VLM」后此区域禁用）
5. **评分结果** — JSON 摘要 + 可排序表格（列与 CSV 完全一致）
6. **高分图预览** — 按分数降序的缩略图画廊，含分数 / 入选标记 / VLM 理由
7. **筛选** — 按入选 / 最低分数 / 关键字筛选表格与画廊（不影响导出）
8. **导出** — 复制/移动到目录（`--export`）、下载 JSON（`--json`）、下载 CSV（`--csv`）

**离线模式：** 勾选「禁用 VLM（纯离线 CV 评分）」即可在无 API Key 环境下完成全流程评分，与 `flashgaze --no-vlm` 完全一致；此时 VLM 配置区禁用，避免无效配置。

**评分一致性：** GUI 调用的是与 CLI 完全相同的 `build_config` → `HybridScorer.score_paths` 装配链，同目录同参数下评分结果与 CLI 字节级一致。

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
| `FLASHGAZE_VLM_PROVIDER` | VLM 提供商：`qwen`/`openai`/`anthropic`/`ollama` | `qwen` |
| `FLASHGAZE_SCENE` | 场景模式：`auto`/`portrait`/`landscape`/`still_life` | `auto` |
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

241 项测试（241 通过 / 21 跳过，共 262），覆盖 CV 引擎、VLM 客户端、混合评分器、导出器、CLI 解析器、端到端流程、可复现性和配置层。

## 技术栈

| 依赖 | 用途 |
|---|---|
| Python 3.10+ | 运行时 |
| OpenCV 4.x | CV 评分（拉普拉斯方差、直方图、Otsu 阈值分割） |
| Pillow | 图片解码兜底（WebP、损坏 JPEG） |
| NumPy | 数组运算 |
| requests | VLM API 调用（Qwen-VL / OpenAI 兼容端点） |
| litellm | 多 VLM 统一调用层（GPT-4o / Claude 3 / Ollama） *（可选安装）* |
| mcp | MCP Server *（可选安装）* |

---

<div align="center">

**MIT License**

</div>
