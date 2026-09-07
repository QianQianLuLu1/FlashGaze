<div align="center">

# FlashGaze

**瞬选灵眸 — AI-Assisted Local Image Scoring CLI**

Hybrid CV + VLM engine for scoring and filtering photos on your machine, designed for stable invocation by AI agents.

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![CI](https://github.com/QianQianLuLu1/FlashGaze/actions/workflows/ci.yml/badge.svg)](https://github.com/QianQianLuLu1/FlashGaze/actions/workflows/ci.yml)
[![Codecov](https://codecov.io/gh/QianQianLuLu1/FlashGaze/badge.svg)](https://codecov.io/gh/QianQianLuLu1/FlashGaze)
[![Tests](https://img.shields.io/badge/tests-1052%20passed-brightgreen.svg)](#testing)
[![Version](https://img.shields.io/badge/version-0.1.2-orange.svg)](#)

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
| Bench | [Performance Benchmarks](#performance-benchmarks) | [性能基准](#性能基准) |
| Security | [Security Scanning](#security-scanning) | [安全扫描](#安全扫描) |
| Optional | [Optional Features](#optional-features) | [可选功能](#可选功能) |
| Stack | [Tech Stack](#tech-stack) | [技术栈](#技术栈) |
| Release | [Release Process](#release-process) | [发布流程](#发布流程) |

---

<!-- ==================== ENGLISH ==================== -->

# English

## Why FlashGaze

Picking the best shots from a folder of hundreds is tedious. FlashGaze automates it: a CV engine measures sharpness and exposure objectively, an optional VLM layer compensates for artistic intent (background blur, silhouette, low-key mood), and the result is a ranked, structured report you can pipe into any workflow.

## Key Features

- **Hybrid scoring engine** — CV objective score (Laplacian variance + histogram exposure) as the backbone, VLM scene-aware adjustment capped at ±10 points
- **Multi-VLM provider support** — Qwen-VL by default (zero new dependencies, 100% backward compatible); GPT-4o / Claude 3 / Ollama via the same self-managed pinned-requests layer (LiteLLM optional), with no per-vendor adapter code
- **Score explainability** — every VLM adjustment carries a ≤20-character `vlm_reason` and a `vlm_provider` tag in CSV/JSON output
- **Scene-based scoring** — `--scene auto/portrait/landscape/still_life` applies differentiated prompts for each scene type
- **Reproducible** — same image, same score, every run in `--no-vlm` mode (10/10 consistency verified); with VLM enabled, sampling is fixed by default (`temperature=0`, `seed=42` where the provider supports it) and echoed in `summary.vlm_sampling` — provider-side determinism at `temperature=0` is best-effort, not bit-for-bit guaranteed
- **Agent-friendly** — stdout carries clean JSON, stderr carries logs, standard exit codes, safe to call via `subprocess`
- **Zero-cost mode** — `--no-vlm` runs entirely offline with no API key required
- **MCP Server built-in** — callable directly from Claude Code, TRAE, Cursor, Codex, and any MCP-compatible tool
- **Graceful degradation** — a corrupted image gets `score=0` with an `error` field; VLM failure falls back to CV-only; neither interrupts the batch
- **Workspace cleanup** — in-place deletion of low-score images with path-traversal protection and `dry_run` safety default; available both as an MCP tool (`cleanup_workspace_images`) and as a CLI subcommand (`flashgaze cleanup`, default `--dry-run`)
- **Optional CV enhancements** — four opt-in dimensions (noise / color / portrait / dedup) that default off and degrade gracefully when their dependencies are missing
- **EXIF write-back** — `--exif` writes the final score into image EXIF metadata (JPEG/WebP only); install with `pip install -e ".[exif]"`
- **Excel export** — `--xlsx` emits a `.xlsx` scoring sheet (openpyxl) alongside JSON/CSV; install with `pip install -e ".[xlsx]"`
- **Plugin system** — `--enable-plugins` runs a discoverable plugin scoring stage (`flashgaze/plugins/builtin/` + `~/.flashgaze/plugins/` + `--plugin-dir`); no extra install required

## How It Works

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  Image Dir   │────▶│  CVEngine     │────▶│  HybridScorer    │
│ JPG/PNG/WebP │     │ · Sharpness   │     │  CV_score × w    │
│ BMP/TIFF/HEIC│     │ · Exposure    │     │  + VLM ±adjust   │
└─────────────┘     │ · Composition  │     │  = Final 0-100   │
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

> HEIC/HEIF decoding requires the optional `heic` extra; all other listed formats work out of the box.

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
cd FlashGaze
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
pip install -e ".[vlm-multi]"     # Optional LiteLLM backend (use_litellm=True) for VLM providers
pip install -e ".[gui]"           # Web GUI (Gradio) — run `flashgaze-webui` after install
pip install -e ".[heic]"          # HEIC/HEIF format support (pillow-heif)
pip install -e ".[all]"           # Everything except portrait & mcp (deliberate, see pyproject.toml)
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

# Workspace cleanup — dry-run first (reports only, deletes nothing)
flashgaze cleanup ./photos --top 30 --no-vlm --dry-run

# Workspace cleanup — actually delete low-score images (prints pending count first)
flashgaze cleanup ./photos --top 30 --no-vlm --apply
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
| `--export-dir PATH` | Export destination (default `./精选`; requires `--export`, rejected with exit code 1 otherwise; paths resolving outside the scanned directory are rejected, exit code 1) |
| `--move` | Move instead of copy (requires `--export`, rejected with exit code 1 otherwise) |
| `--json` | Output JSON report to stdout |
| `--csv` | Output CSV report |
| `--output PATH` | Write JSON report to file (requires `--json`; paths resolving outside the scanned directory are rejected, exit code 1) |
| `--csv-output PATH` | Write CSV report to file (requires `--csv`; default `flashgaze_result.csv`; paths resolving outside the scanned directory are rejected, exit code 1) |
| `--exif` | Write final score back to image EXIF metadata (JPEG/WebP only; requires `pip install -e ".[exif]"`) |
| `--no-exif-backup` | Skip creating the `.flashgaze_backup` original before writing EXIF (dangerous: in-place rewrite with no rollback point; requires `--force` to confirm) |
| `--force` | Dangerous-action confirmation switch: required by `--no-exif-backup` (same semantics as the cleanup guardrail flag) |
| `--xlsx` | Also emit a `.xlsx` scoring sheet (requires `pip install -e ".[xlsx]"`) |
| `--xlsx-output PATH` | `.xlsx` output path (requires `--xlsx`; default `flashgaze_result.xlsx`; paths resolving outside the scanned directory are rejected, exit code 1) |
| `--enable-plugins` | Enable the plugin scoring stage (auto-discovers builtin + user plugin dirs) |
| `--plugin-dir PATH` | Additional plugin directory merged with builtin and user dirs |
| `--no-vlm` | Disable VLM, CV-only mode (zero API cost) |
| `--vlm-provider PROVIDER` | VLM provider: `qwen` (default) / `openai` / `anthropic` / `ollama`. All use the built-in pinned layer (no LiteLLM required); `.[vlm-multi]` only needed for the optional LiteLLM backend |
| `--scene SCENE` | Scene-based scoring mode: `auto` (default) / `portrait` / `landscape` / `still_life` |
| `--enable-composition` | Enable rule-of-thirds scoring *(experimental)* |
| `--enable-noise` | Enable BRISQUE no-reference noise scoring *(requires opencv-contrib-python + model files)* |
| `--enable-color` | Enable HSV color richness scoring |
| `--enable-portrait` | Enable portrait scoring (face count + face-region sharpness, +3~5 bonus) *(requires face_recognition)* |
| `--enable-dedup` | Enable PHash deduplication (similar images keep only the highest score) *(requires imagededup)* |
| `--dedup-threshold N` | PHash hamming distance threshold (default 8, lower is stricter) |
| `--weights JSON` | Custom weight JSON, e.g. `'{"sharpness":0.5,"exposure":0.3,"composition":0.2}'`; optional keys: `composition`/`noise`/`color` |
| `--workers N` | Worker concurrency (default 4): a process pool scores CV dimensions, a thread pool fans out VLM calls |
| `--config-file PATH` | Path to JSON config file |
| `--verbose` | Verbose logging to stderr (replaces the terminal progress bar with one `进度 k/N` log line per image) |
| `--no-downscale` | Disable downscaling of large images; process at original resolution (default: downscale when long edge > 2048px) |
| `--api-key KEY` | VLM API key (overrides env var; visible in the process command line — prefer `--api-key-file`) |
| `--api-key-file PATH` | Read the VLM API key from a file (`-` reads stdin), keeping it out of the process command line. Mutually exclusive with `--api-key` (exit code 1) |
| `--api-base URL` | VLM API base endpoint (overrides env var) |
| `--model NAME` | VLM model name (overrides env var) |
| `--version` | Show program version and exit |

> **Oversized images** (more than **64 megapixels** by default) are rejected **before decoding**: they land in the report with a non-empty `error` (`图片尺寸超限：…`), score `0`, and are excluded from VLM scoring — the rest of the batch is scored normally and the exit code does not change. This is the decompression-bomb guard: a few-hundred-byte file can declare hundreds of millions of pixels and make the decoder allocate gigabytes. Raise the limit with `FLASHGAZE_MAX_IMAGE_PIXELS` (e.g. `200000000` for 100MP+ medium format), or set it to `0` to restore the previous unbounded behaviour.

Progress display: when stderr is a real terminal, a progress bar renders on stderr (stdout stays JSON-only); when piped/redirected (CI, agents), no progress output is produced at all; with `--verbose`, progress becomes plain log lines.

## VLM Providers

FlashGaze supports four VLM providers through a **single self-managed pinned-requests layer** — **no per-vendor adapter code, and no LiteLLM required by default**. Every provider (qwen / openai / anthropic / ollama) resolves and **pins a single IP at construction time**, then connects directly to that IP with a pinned `Host` header + TLS SNI pin (HTTPS) and `allow_redirects=False`, eliminating the DNS-rebinding TOCTOU window (incl. cloud metadata `169.254.169.254` / private ranges). LiteLLM remains an **optional opt-in backend** (`VLMClient(use_litellm=True)`) for advanced compatibility scenarios.

| Provider | Model example | API base | Requires LiteLLM |
|---|---|---|---|
| `qwen` (default) | `qwen-vl-max` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | No |
| `openai` | `gpt-4o` | `https://api.openai.com/v1` | No (built-in pinned layer) |
| `anthropic` | `claude-3-5-sonnet-20241022` | `https://api.anthropic.com` | No (built-in pinned layer) |
| `ollama` | `llama3.2-vision` | `http://localhost:11434` | No (built-in pinned layer) |

> **Self-hosted Ollama on a LAN / Docker:** the built-in SSRF guard rejects private/link-local addresses (e.g. `192.168.x`, `10.x`, `172.17.x`, docker gateway `169.254.x`) for public-cloud providers. **`ollama` is treated as self-hosted and auto-allows these targets** — just point `FLASHGAZE_API_BASE` at your LAN host (e.g. `http://192.168.1.10:11434`) and it works out of the box. The pin-IP direct-connect (no DNS-rebinding TOCTOU) is still applied. For **non-ollama** self-hosting (e.g. a qwen/openai-compatible endpoint behind a private IP), opt in explicitly with `FLASHGAZE_ALLOW_PRIVATE_TARGETS=true`.

> **Endpoint allowlist (warn-only):** `api_base` accepts four unvalidated sources (env var, JSON config file, CLI `--api-base`, WebUI text box) and your API key plus every image are POSTed to whatever host it points at. `build_config` therefore checks the endpoint against the allowlist and logs a **WARNING** (host + reason + remedy) when it is not covered — **it does not block the run**, so self-hosted setups keep working. Private/loopback hosts are exempt under `provider=ollama` or `FLASHGAZE_ALLOW_PRIVATE_TARGETS=true`. To silence the warning, add the host to `FLASHGAZE_API_BASE_ALLOWLIST` or set `FLASHGAZE_ALLOW_UNTRUSTED_API_BASE=1`. This matters most for config files: cloning a third-party repo that ships a config can otherwise silently redirect your key and images.

> **Proxy incompatibility (by design):** the pinned layer sets `trust_env=False`, so `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` / `NO_PROXY` and `REQUESTS_CA_BUNDLE` / `CURL_CA_BUNDLE` are **ignored** — a proxy would resolve the target hostname itself (and an injected CA would break certificate validation), silently bypassing the pin-IP / Host-pin / SNI-pin guarantees above. A one-time `WARNING` is logged at construction when any of these variables is set. If you must reach a VLM endpoint through a proxy, use the opt-in LiteLLM backend (`VLMClient(use_litellm=True)`) — it does not apply the pin-IP direct-connect, and whether it honours environment proxies is decided by LiteLLM itself (outside this module's control).

**Configuration examples:**

```bash
# 1. Qwen-VL (default, 100% backward compatible — no LiteLLM needed)
export FLASHGAZE_VLM_PROVIDER=qwen
export FLASHGAZE_API_KEY=sk-xxxxxxxx
export FLASHGAZE_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
export FLASHGAZE_MODEL=qwen-vl-max

# 2. OpenAI GPT-4o (built-in pinned layer, no LiteLLM needed)
export FLASHGAZE_VLM_PROVIDER=openai
export FLASHGAZE_API_KEY=sk-xxxxxxxx
export FLASHGAZE_API_BASE=https://api.openai.com/v1
export FLASHGAZE_MODEL=gpt-4o

# 3. Anthropic Claude 3 (built-in pinned layer; provide api_base explicitly)
export FLASHGAZE_VLM_PROVIDER=anthropic
export FLASHGAZE_API_KEY=sk-ant-xxxxxxxx
export FLASHGAZE_API_BASE=https://api.anthropic.com
export FLASHGAZE_MODEL=claude-3-5-sonnet-20241022

# 4. Ollama local VLM (built-in pinned layer, no real key needed)
export FLASHGAZE_VLM_PROVIDER=ollama
export FLASHGAZE_API_KEY=ollama
export FLASHGAZE_API_BASE=http://localhost:11434
export FLASHGAZE_MODEL=llama3.2-vision
```

> **Optional LiteLLM backend:** set `VLMClient(use_litellm=True)` (programmatic) to route through LiteLLM instead of the built-in pinned layer. This is only needed for exotic endpoints; the construction-time static SSRF guard still applies.

**Graceful degradation:** If a VLM call fails (network/timeout/invalid response), it returns `ok=False` and the batch continues in CV-only mode — never raising. Invalid `provider`/`scene` values fall back to defaults with a warning.

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
| Noise (BRISQUE) | `pip install -e ".[cv-enhanced]"` — BRISQUE model files ship inside the package (`flashgaze/models/brisque/`, see its README; locate the dir with `python -c "from importlib.resources import files; print(files('flashgaze.models') / 'brisque')"`). Manual placement or env-gated download (`FLASHGAZE_BRISQUE_ALLOW_DOWNLOAD=1`) is only needed if the bundled files are missing | Penalize noisy/compressed images |
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
| `vlm-multi` | `pip install -e ".[vlm-multi]"` | optional LiteLLM backend (`use_litellm=True`) | GPT-4o / Claude 3 / Ollama | [VLM Providers](#vlm-providers) |
| `gui` | `pip install -e ".[gui]"` | `flashgaze-webui` | Browser-based GUI | [Web GUI](#web-gui) |
| `heic` | `pip install -e ".[heic]"` | auto on HEIC/HEIF decode | HEIC/HEIF image format support (pillow-heif) | [Installation](#installation) |
| `exif` | `pip install -e ".[exif]"` | `--exif` (`--no-exif-backup`) | Write score into image EXIF (JPEG/WebP) | [CLI Options](#cli-options) |
| `xlsx` | `pip install -e ".[xlsx]"` | `--xlsx` (`--xlsx-output`) | Emit `.xlsx` scoring sheet | [CLI Options](#cli-options) |
| _plugins_ | built-in, no extra | `--enable-plugins` (`--plugin-dir`) | Discoverable plugin scoring stage | [CLI Options](#cli-options) |
| `all` | `pip install -e ".[all]"` | all of the above | Installs everything **except** `portrait` and `mcp` (deliberate, matches the legacy setup.py) | — |

**EXIF write-back** (`pip install -e ".[exif]"`): `--exif` stores the final 0–100 score (and selected flag) into the image's EXIF `UserComment` field, plus `ImageDescription` (ASCII reason) and `Software` (`FlashGaze/<provider>`). JPEG/WebP only; pass `--no-exif-backup` to skip the `.flashgaze_backup` copy.

**Excel export** (`pip install -e ".[xlsx]"`): `--xlsx` produces `flashgaze_result.xlsx` (override path with `--xlsx-output`) with the same columns as the CSV report.

**Plugin system** (built in): `--enable-plugins` runs a scoring stage that auto-discovers `flashgaze/plugins/builtin/` and `~/.flashgaze/plugins/`; `--plugin-dir` adds an extra directory. No `pip` extra required.

## MCP Server

FlashGaze ships with a built-in MCP Server. After installing with `pip install -e ".[mcp]"`, add it to your AI tool's MCP configuration:

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

> **Path boundary for upload/single-image scoring:** `score_uploaded_images` / `score_single_image` only read images inside the **allowed scan roots** configured via `FLASHGAZE_MCP_ALLOWED_ROOTS` (comma-separated directories). If unset, the boundary defaults to the MCP server's startup directory. Paths outside the roots are never read, decoded, or sent to the VLM endpoint — `score_uploaded_images` reports them in `details.skipped` (with a rejection reason), `score_single_image` rejects the call with code 1.

> **Config file support:** the MCP Server loads the JSON config file pointed to by `FLASHGAZE_CONFIG_FILE` exactly like the CLI's `--config-file` — add it to the `env` block above. Precedence inside MCP: tool parameters > environment variables > config file > defaults.

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
- Batch-deletion guardrail: if more than 95% of the scoreable images would be deleted (with at least 6 images scored in total), the whole batch is blocked — **nothing is deleted** and every candidate is listed in `details.blocked_files`. The ratio is computed over scoreable images only: corrupted images (evaluation errors) count toward neither numerator nor denominator, so they cannot dilute the ratio and slip past the guardrail

**Programmatic convention (guardrail blocked):** when the guardrail fires, the tool returns a non-zero result — `status="blocked"`, `code=1`, `summary.force_required=true`. The response keeps the standard six-field schema, so `summary` and `details.blocked_files` stay readable. Re-run with `force=True` once you have reviewed the list; that call returns `status="success"`, `code=0`. The CLI equivalent (`flashgaze cleanup`) signals the same condition with **exit code `1`** and an error log. In other words: CLI encodes it in the process exit code, MCP encodes it in `status`/`code` of the JSON payload.

**Programmatic convention (delete failures):** if an individual image cannot be deleted — it is open in another program, read-only, or on a different volume than the recycle bin — the tool returns `status="partial"`, `code=5`, with the count in `summary.delete_failures` and per-item `{path, reason}` in `details.delete_failures`. The remaining images are still processed normally, and the low-score images that failed to delete stay on disk (the recycle-bin move is never downgraded to a plain `unlink`). `summary.delete_failures` is explicitly `0` when every deletion succeeds. The CLI equivalent (`flashgaze cleanup`) signals the same condition with **exit code `5`**.

</details>

## Web GUI

FlashGaze ships with an optional browser-based GUI built on Gradio. It mirrors every CLI parameter in the interface and reuses the same `HybridScorer` scoring path — no separate scoring logic is introduced. Config files are honored here too: set `FLASHGAZE_CONFIG_FILE` in the server process environment and its values apply as the config-file layer for every scoring run (form inputs still override it, following CLI args > env > config file > defaults).

**Install and launch:**

```bash
pip install -e ".[gui]"
flashgaze-webui
```

> Verified with gradio 6.24.0.

Open `http://127.0.0.1:7860` in your browser. The GUI defaults to localhost-only; pass `--host 0.0.0.0` for LAN access.

> The browser-based GUI is also covered by Playwright E2E tests (`tests/e2e`, marker `e2e`). To run them you need the browser binaries: `python -m playwright install chromium firefox` (Chromium + Firefox, both required gates) or `python -m playwright install webkit` for the optional WebKit run; pass `--browser <name>` to `pytest tests/e2e -m "e2e"` (`-m "e2e"` overrides the built-in default filter, M-17).

**CLI flags:**

| Flag | Description |
|---|---|
| `--host HOST` | Listen address (default `127.0.0.1`; use `0.0.0.0` for LAN) |
| `--port PORT` | Listen port (default `7860`) |
| `--dir PATH` | Pre-fill the directory input (does not auto-start scoring) |
| `--share` | Enable Gradio temporary public link |
| `--auth user:pass` | Login credentials for public exposure (`user:password`); when binding publicly (`--host 0.0.0.0` or `--share`) auth is mandatory — omit it and a random token (username `admin`) is generated and printed to stderr |
| `--allow-root DIR` | Repeatable scoring-root whitelist; when provided, only these directories can be scanned |
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
8. **Export** — copy/move to directory (`--export`), download JSON (`--json`), download CSV (`--csv`), download XLSX (`--xlsx`)

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
    capture_output=True,
    text=True,
    timeout=600,
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
| `FLASHGAZE_CONFIG_FILE` | **Config file shared by all three entries**: path to a JSON config file, loaded as the file layer inside `build_config` — honored identically by CLI, MCP Server, and Web GUI. Same layer as CLI `--config-file` (merged per-key, `--config-file` keys win when both are set); still below the other environment variables. No default-path discovery: unset means no config file is loaded. A missing/corrupt file logs a WARNING and falls back to defaults. | unset |
| `FLASHGAZE_API_KEY` | VLM API key (required unless `--no-vlm`) | — |
| `FLASHGAZE_API_BASE` | API endpoint | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `FLASHGAZE_MODEL` | Model name | `qwen-vl-max` |
| `FLASHGAZE_VLM_PROVIDER` | VLM provider: `qwen`/`openai`/`anthropic`/`ollama` | `qwen` |
| `FLASHGAZE_SCENE` | Scene mode: `auto`/`portrait`/`landscape`/`still_life` | `auto` |
| `FLASHGAZE_WEIGHTS` | Scoring weights as JSON, e.g. `{"sharpness":0.5,"exposure":0.5}` — `sharpness`/`exposure` required, `composition`/`noise`/`color` optional, auto-normalized to sum 1 | built-in `sharpness 0.5 / exposure 0.5` |
| `FLASHGAZE_DEDUP_THRESHOLD` | PHash hamming-distance threshold for dedup (`--enable-dedup`); lower is stricter | `8` |
| `FLASHGAZE_ALLOW_PRIVATE_TARGETS` | **SSRF escape hatch**: set `true` to allow the VLM endpoint to resolve to a private/link-local/reserved/multicast address (e.g. self-hosted qwen/openai-compatible). Default `false` keeps the guard on for public-cloud providers. `ollama` auto-allows private targets, so this is only needed for non-ollama self-hosting. | `false` |
| `FLASHGAZE_API_BASE_ALLOWLIST` | **Endpoint allowlist**: comma-separated host suffixes appended to the built-in official domains (`dashscope.aliyuncs.com`, `dashscope-intl.aliyuncs.com`, `api.openai.com`, `api.anthropic.com`, `localhost`, `host.docker.internal`). Matching is exact-host or `.suffix`, so `dashscope.aliyuncs.com.evil.com` does **not** match. | built-in official domains |
| `FLASHGAZE_MCP_ALLOWED_ROOTS` | **Allowed scan roots for MCP upload/single-image scoring**: comma-separated directories whose images `score_uploaded_images` / `score_single_image` may read. Paths outside the roots are rejected before any file access; there is no switch to disable the boundary. | MCP server startup directory |
| `FLASHGAZE_ALLOW_UNTRUSTED_API_BASE` | Set `1`/`true`/`yes`/`on` to declare the current `api_base` trusted — silences the non-allowlist warning for self-hosted / custom gateways. | unset |
| `FLASHGAZE_TIMEOUT` | Request timeout (seconds) | `30` |
| `FLASHGAZE_WORKERS` | Worker concurrency (process pool for CV scoring, thread pool for VLM calls) | `4` |
| `FLASHGAZE_MAX_RETRIES` | VLM retry count (timeout/connection only) | `3` |
| `FLASHGAZE_VLM_MAX_ADJUSTMENT` | VLM adjustment cap | `10.0` |
| `FLASHGAZE_VLM_BREAKER_THRESHOLD` | Batch circuit breaker: trip after N consecutive VLM failures (or ≥80% failure rate over ≥20 samples); remaining images skip VLM (pure-CV caliber, marked in cleanup reports). `0` disables. | `5` |
| `FLASHGAZE_VLM_TEMPERATURE` | VLM sampling temperature, clamped to `[0, 2]` (further clamped per provider — Anthropic caps at `1.0`). Fixed by default to converge sampling randomness; set `null` in the config file to omit the parameter entirely (server default). | `0.0` |
| `FLASHGAZE_VLM_SEED` | Fixed VLM random seed, injected only for providers whose protocol supports it (`qwen`/`openai`; Anthropic has no `seed` field, Ollama's OpenAI-compat layer doesn't promise one). Must be a non-negative integer; `null` in the config file omits it. Effective parameters are echoed in the JSON report `summary.vlm_sampling`. | `42` |
| `FLASHGAZE_MAX_IMAGE_PIXELS` | **Decode pixel budget**: images whose header declares more pixels than this are rejected *before* any pixel buffer is allocated (decompression-bomb guard) and degrade to an `error` placeholder instead of OOM. Raise it for 100MP+ medium-format files; set `0` to disable the project limit and fall back to Pillow's own threshold (~89M warn / ~178M raise). | `64000000` |
| `FLASHGAZE_USER_PLUGINS` | Set `1` to enable scanning the user plugin directory `~/.flashgaze/plugins` (off by default as an RCE guard; an explicit `--plugin-dir` always works) | unset |
| `FLASHGAZE_BRISQUE_ALLOW_DOWNLOAD` | Set `1` to allow network download of missing BRISQUE model files (size-capped and SHA256-verified; off by default — missing files degrade gracefully instead) | unset |

See `config.example.json` for the file-based config format. The `weights` field can be set three ways: CLI `--weights` (JSON string), the `FLASHGAZE_WEIGHTS` environment variable, or the config file. The config file applies to **all three entries** the same way: `--config-file` on the CLI, or `FLASHGAZE_CONFIG_FILE` for CLI / MCP / Web GUI alike (per-key merge, `--config-file` wins when both are set). No default config-file name is auto-discovered from the working directory.

</details>

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | Argument error |
| `2` | API failure *(reserved — VLM failure degrades to CV-only)* |
| `3` | Invalid directory or no images found |
| `4` | Image processing error — scoring-stage failure; single-image failures degrade to an `error` field, and this code is also emitted when the BRISQUE model integrity check aborts the run (see notes below) |
| `5` | Export failure or partial export — some selected images could not be exported (disk full / permission denied / source deleted externally / export target is a regular file). Exports and manifests are still emitted; the `--json` report exposes `summary.export_failed` plus per-item `summary.export.failures`. Takes precedence over code `7` when both apply |
| `6` | Configuration error (missing API key, etc.) |
| `7` | EXIF write-back failure — at least one image failed to update; the run still emits exports/manifests, and the JSON report exposes `summary.exif_failed` plus per-item `summary.exif.failures` |
| `8` | Unexpected internal error — an exception escaped a subcommand's own handling. The error type and message are logged as a single line on stderr (`未预期的内部错误（<type>）: <msg>`); the process never prints a traceback (the stack trace is emitted at DEBUG level, i.e. only with `--verbose`) |

> Code 2 is reserved: VLM call failure degrades to CV-only with zero adjustment. Single-image corruption likewise degrades to `score=0` with an `error` field and never interrupts the batch — code `4` itself is emitted only for whole-run scoring failures such as the BRISQUE model integrity check (see below).
>
> `8` is produced by the last-resort handler in `main()`: any exception not already mapped by a subcommand is caught there instead of terminating the process with a bare traceback and Python's default exit status `1`. Scorer construction failures (`make_scorer`) are mapped before that — `BrisqueIntegrityError` (model hash mismatch) to `4` with a `模型完整性校验失败` log, other construction errors to `6` (configuration/environment unusable, e.g. an endpoint rejected by the SSRF guard). In multiprocess scoring (`--workers >1`) the signal is detected during process-pool warm-up: the initializer sets a shared flag and fails loudly, and the main loop terminates immediately with exit code `4` — no serial re-run, no per-image error placeholders.
>
> `1` is also returned when `--exif --no-exif-backup` is used without `--force`: an in-place rewrite of the originals with no rollback point is a dangerous operation and must be confirmed explicitly.
>
> `1` is also returned when `flashgaze cleanup` is blocked by the batch-deletion guardrail (nothing deleted; re-run with `--force`). The MCP equivalent reports `status="blocked"` / `code=1` — see [Workspace Cleanup Safety](#mcp-server).
>
> `5` is returned when `flashgaze score --export` could not export every selected image (previously such partial failures silently exited 0); the MCP equivalent (`export_selected_images`) reports `status="partial"` / `code=5`, with the failure count in `summary.export_failed` and per-item reasons in `details.failures`. With zero failures the CLI still returns `0`, and MCP keeps `status="success"` with an explicit `summary.export_failed=0`.
>
> `5` is also returned when `flashgaze cleanup` could not delete every low-score image (file in use, read-only, or cross-volume recycle); the MCP equivalent (`cleanup_workspace_images`) reports `status="partial"` / `code=5`, with the count in `summary.delete_failures` and per-item reasons in `details.delete_failures` — see [Workspace Cleanup Safety](#mcp-server).

## Testing

```bash
pip install -r requirements-dev.txt
pytest tests/ -v --cov=flashgaze --cov-report=term-missing
```

The default run carries a baked-in filter (`pyproject.toml` `[tool.pytest.ini_options]`, review item M-17): `addopts = '-m "not e2e"'` plus `testpaths = ["tests"]`, so a bare `pytest` / `pytest tests/` only collects `tests/` and never touches the browser-E2E suite or the top-level `benchmarks/` — one machine-executable definition of what a pass covers. An explicit `-m` on the command line overrides the default entirely (re-state all exclusions you need, e.g. `-m "not slow and not e2e"`); `-o addopts=` lifts the default; `make test` / `make test-all` are the one-click equivalents.

1080 tests collected by default (measured with all safe extras installed: 1052 passed / 28 skipped; the 10 browser-E2E tests are deselected by the default filter; WebUI layers auto-skip where gradio is absent) covering CV engine, VLM client, hybrid scorer, exporter, CLI parser, end-to-end flows, reproducibility, config layers, and the three-layer Web GUI coverage below.

Coverage gate: total coverage must stay ≥ 80% (configured in `.coveragerc`, enforced by the same `pytest --cov` run locally and in CI). `mcp_server` and `webui/app` are inside the gate — the main CI matrix installs the `mcp` extra so their tests run there. The three dependency-heavy optional modules (`xlsx_exporter`, `deduplicator`, `portrait_engine`) are excluded from the main gate and enforced by the CI `extras` job instead (`.coveragerc-extras`: unconditional hard floor of 50% overall plus per-module floors in `ci.yml`; see `docs/extras-governance.md`).

### Web GUI test layers

The Gradio Web GUI is covered by three layers beyond the pure-logic `tests/test_webui.py`; all skip gracefully when gradio is absent:

- **Smoke** (`tests/test_webui_smoke.py`): `build_app()` assembles a `gr.Blocks` under the installed gradio — no port, no browser.
- **Component-level** (`tests/test_webui_components.py`): component tree and defaults, event wiring via `demo.fns` (input/output order of every `click`/`change` binding), and direct invocation of the closures behind the buttons — form adaptation, error statuses, filtering, export and download handlers. Runs in the CI `extras` job.
- **E2E** (`tests/e2e/`, marker `e2e`): a real Gradio server on an ephemeral port driven by Playwright — form interactions (VLM toggle, `top` input), error messages, result rendering (status / JSON summary / table / gallery), filtering, export, and JSON download. Runs in the blocking CI `e2e` job against **Chromium and Firefox** (both required gates); WebKit is optional.

```bash
pip install -e ".[gui,xlsx]" -r requirements-dev.txt -r requirements-e2e.txt
# Install the browser binaries you want to run (omit --with-deps on Windows/macOS)
python -m playwright install chromium firefox          # required gates
python -m playwright install webkit                   # optional, if you want WebKit
pytest tests/test_webui_components.py -v     # component level (no browser)
pytest tests/e2e -m "e2e" -v --browser chromium       # E2E, Chromium (default)
pytest tests/e2e -m "e2e" -v --browser firefox        # E2E, Firefox (required gate)
pytest tests/e2e -m "e2e" -v --browser webkit         # E2E, WebKit (optional)
pytest tests/ -m "not e2e"                   # everything except browser tests (this is the built-in default; kept for older checkouts)
```

## Performance Benchmarks

```bash
pip install -r requirements-dev.txt        # includes pytest-benchmark
pytest benchmarks/ -m "not bench_full" --benchmark-autosave
```

Performance benchmarks live in the top-level `benchmarks/` directory (pytest-benchmark; `pytest tests/` never collects them). The `benchmark.yml` workflow gates every PR: the merge-base baseline and the PR head run back-to-back **on the same runner**, and a mean regression beyond **15%** fails CI with a comparison table written to the job summary. Pushes to `main` and the nightly run append results to the `gh-pages` branch, rendering trend charts at `https://<org>.github.io/FlashGaze/dev/bench/`. See [docs/bench/README.md](docs/bench/README.md) for the benchmark inventory, threshold tuning, and local usage.

## Type Checking

```bash
pip install -r requirements-dev.txt
python -m mypy
```

Static type checking with mypy runs in CI (`typecheck` job, blocking). The configuration lives in `pyproject.toml` (`[tool.mypy]`): fully **strict** (`strict = true`), covering the `flashgaze` package, `tests/`, and the benchmark helpers in `tools/bench/` — the staged tightening roadmap (per-module `disallow_untyped_defs` → global strictness flags → `strict = true`) has been completed. Optional extras (gradio / mcp / piexif, …) are handled via `ignore_missing_imports` overrides, so a minimal base install produces the same result as CI. The same check runs locally before commit via a pre-commit hook and the Makefile — see [Local Code Quality Guard](#local-code-quality-guard).

## Linting & Formatting

```bash
pip install -r requirements-dev.txt
python -m ruff format .        # format before committing
python -m ruff check .
```

Lint and format enforcement runs in CI (`lint` job, blocking). The configuration lives in `pyproject.toml` (`[tool.ruff]`): `target-version = "py310"`, `line-length = 100`, and the ruff 0.16 default rule set (413 rules) with RUF001–RUF003 disabled (false positives on Chinese comments). The ruff version is pinned to a minor range (`>=0.16,<0.17`) because ruff expands its default rule set across minor versions — upgrades arrive as reviewed Dependabot PRs. Broad `except Exception` blocks on fault-isolation paths (per-image / per-plugin degradation, entry-point error mapping) carry per-line `# noqa: BLE001` with the justification. The same checks run locally before commit via a pre-commit hook and the Makefile — see [Local Code Quality Guard](#local-code-quality-guard).

## Security Scanning

Dependency security scanning runs in the dedicated `security.yml` workflow, triggered on **every pull request** (vulnerabilities found fail the check), **daily** (scheduled), and **manually** (`workflow_dispatch`).

- **Tooling:** [pip-audit](https://github.com/pypa/pip-audit) audits the **installed environment** — the real transitive dependency tree resolved from `pyproject.toml` (the single source of truth) — against the OSV and PyPI advisory databases.
- **Failure policy:** a known CVE in a core (product-shipped) dependency fails the check. Whether a failed check actually blocks merging depends on the repository's branch protection rules — to enforce blocking, add this check (`Security`) as a required status check under *Settings → Branches*. `requirements-dev.txt` is scanned separately in **report-only** mode (`continue-on-error`) — dev tooling is never distributed with the product.
- **Exemptions:** an audited, temporarily unfixable vulnerability can be exempted via the `PIP_AUDIT_IGNORE` variable in `security.yml`, mapped to `--ignore-vuln`; every exemption must carry the vulnerability ID, the justification (e.g. "version cap pinned for compatibility, no fix released yet"), and a review date.
- **Division of labor with Dependabot:** pip-audit is the *detection* side (finds known vulnerabilities), while `dependabot.yml` is the *remediation* side (proposes version-bump PRs).

## Local Code Quality Guard

Today ruff and mypy run **only in CI**, so non-compliant code can still be committed. The repo ships two complementary local guards that reuse the *exact same* commands as the CI `lint` / `typecheck` jobs (so versions and rules stay in `pyproject.toml` — single source of truth, zero drift):

- **pre-commit hook** (`.pre-commit-config.yaml`): auto-runs `ruff check`, `ruff format --check`, and `mypy` on every `git commit`. Install once with:
  ```bash
  pip install -r requirements-dev.txt
  pre-commit install
  ```
  Each commit is then blocked until all three checks pass. Run them manually on every file with `pre-commit run --all-files`.

- **Makefile** (one-click manual checks, also useful for CI-local parity):
  ```bash
  make check        # lint + format-check + typecheck (full local guard)
  make lint         # python -m ruff check .
  make format       # python -m ruff format .
  make format-check # python -m ruff format --check .
  make typecheck    # python -m mypy
  make test         # python -m pytest tests/ -q (built-in default: e2e excluded)
  make test-all     # python -m pytest tests/ -q -o addopts= (full suite incl. e2e)
  make hooks        # pre-commit run --all-files
  make install      # pip install -r requirements-dev.txt && pre-commit install
  make dist         # build + verify release artifacts locally (same checks as the release pipeline's build job)
  ```
  On Windows without GNU make, run the equivalent `python -m …` commands directly (the Makefile lives at the repo root — the same directory as `pyproject.toml`).

Both guards intentionally **check only** (matching CI `--check`); they do not auto-fix, so a non-compliant commit is blocked rather than silently rewritten.

## Tech Stack

| Dependency | Role |
|---|---|
| Python 3.10+ | Runtime |
| OpenCV 4.x | CV scoring (Laplacian variance, histogram, Otsu thresholding) |
| Pillow | Primary image decoder (single decode pass → BGR with EXIF transpose; WebP/BMP/TIFF, optional HEIC) |
| NumPy | Array operations |
| json5 | Tolerant JSON parsing for VLM responses (code fences, trailing commas) |
| tqdm | Terminal progress bar (rendered to stderr only) |
| requests | VLM API calls (Qwen-VL / OpenAI-compatible endpoints) |
| litellm | Optional LiteLLM backend (escape hatch via `use_litellm=True`) *(optional install)* |
| mcp | MCP Server *(optional install)* |

## Release Process

Releases are fully automated by the `release.yml` workflow: pushing a version tag builds the sdist + wheel, verifies packaged data files, smoke-tests the wheel in a clean venv, publishes to PyPI, and creates a GitHub Release carrying the same artifacts.

**Cutting a release** (from a CI-green commit on `main`) takes three steps:

1. Bump `__version__` in `flashgaze/__init__.py` — the single source of truth for the version.
2. Rename the `[Unreleased]` heading in `CHANGELOG.md` to `[x.y.z] - YYYY-MM-DD`.
3. Tag and push:
   ```bash
   git tag vx.y.z
   git push origin vx.y.z
   ```

You can also trigger the workflow manually from the **Actions** tab (`Run workflow`), but a manual run is **always a rehearsal** — it only builds and verifies, never publishes. A real release must come from pushing a version tag (manual runs operate on a branch ref, so the publish path is deliberately excluded).

**Authentication (PyPI Trusted Publishing / OIDC):** no repository secret is required. Before the first release, register a *Trusted Publisher* on the PyPI project page (*Publishing* section) with:

- **Repository**: `https://github.com/<owner>/<repo>` (this repository)
- **Workflow name**: `release` (the filename of `.github/workflows/release.yml`, without `.yml`)
- **Environment**: leave blank

The `publish` job declares `permissions: id-token: write`, so the `pypa/gh-action-pypi-publish` action automatically exchanges the short-lived OIDC token for PyPI credentials — no long-lived API token is ever stored.

**Failure handling:**

| Failed stage | Side effect | Recovery |
|---|---|---|
| preflight / build / verify | none — nothing published | fix and re-run the workflow |
| PyPI upload | none (or partial) — the GitHub Release is not created | re-run the workflow; files of the same version cannot be re-uploaded, so first check on PyPI which files already exist |
| GitHub Release only | PyPI already published | re-run the failed `github-release` job alone |

**Local dry run** (same commands the workflow runs):

```bash
pip install build twine
python -m build
twine check --strict dist/*
```

---

<!-- ==================== CHINESE ==================== -->

# 中文

## 项目简介

从几百张照片里挑出最好的几张，这件事既费时又主观。FlashGaze 把它自动化：CV 引擎客观测量清晰度和曝光度，可选的 VLM 层判断模糊或偏暗是否属于艺术手法（背景虚化、逆光剪影、暗调氛围），最终输出一份排序好的结构化报告，可以直接接入任何工作流。

## 核心特性

- **混合评分引擎** — CV 客观分（拉普拉斯方差 + 直方图曝光度）主导，VLM 场景补偿上限 ±10 分
- **多 VLM 提供商支持** — 默认通义千问 Qwen-VL（零新依赖，100% 向后兼容）；GPT-4o / Claude 3 / Ollama 通过同一套自管 pin-IP 直连层（LiteLLM 可选），无任何厂商专属适配代码
- **评分可解释性** — 每次 VLM 补偿都附带 ≤20 字的 `vlm_reason` 与 `vlm_provider` 标识，写入 CSV/JSON 输出
- **场景化评分** — `--scene auto/portrait/landscape/still_life` 针对不同场景使用差异化提示词
- **可复现** — `--no-vlm` 模式下同一张图连续运行 10 次分数完全一致；启用 VLM 时默认固定采样参数（`temperature=0`，provider 协议支持时注入 `seed=42`）并回显在报告 `summary.vlm_sampling` 中——服务端在 temperature=0 下的确定性为 best-effort，不承诺逐位一致
- **Agent 友好** — stdout 输出干净 JSON，stderr 输出日志，标准返回码，可通过 `subprocess` 稳定调用
- **零成本模式** — `--no-vlm` 完全离线运行，无需 API Key
- **内置 MCP Server** — 可被 Claude Code、TRAE、Cursor、Codex 等所有支持 MCP 的工具直接调用
- **优雅降级** — 损坏图片标记 `score=0` 并附带 `error` 字段；VLM 调用失败回退为纯 CV；两者均不中断批处理
- **工作空间清理** — 原地删除低分图片，含路径穿越防护和 `dry_run` 安全默认；同时提供 MCP 工具 `cleanup_workspace_images` 与 CLI 子命令 `flashgaze cleanup`（默认 `--dry-run`）
- **可选 CV 增强维度** — 噪点 / 色彩 / 人像 / 去重四类可选维度，默认全部关闭，依赖缺失时优雅降级
- **EXIF 写回** — `--exif` 将最终评分写回图片 EXIF 元数据（仅 JPEG/WebP），需 `pip install -e ".[exif]"`
- **Excel 清单导出** — `--xlsx` 额外生成 `.xlsx` 评分表（openpyxl），需 `pip install -e ".[xlsx]"`
- **插件系统** — `--enable-plugins` 启用可发现式插件评分阶段（`flashgaze/plugins/builtin/` + `~/.flashgaze/plugins/` + `--plugin-dir`），无需额外安装

## 工作原理

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  图片目录    │────▶│  CVEngine     │────▶│  HybridScorer    │
│ JPG/PNG/WebP│     │ · 清晰度      │     │  CV 加权分       │
│BMP/TIFF/HEIC│     │ · 曝光度      │     │  + VLM ±补偿     │
└─────────────┘     │ · 构图(实验)   │     │  = 最终分 0-100  │
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

> HEIC/HEIF 解码需可选 `heic` extra（pillow-heif）；其余列出的格式开箱即支持。

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
cd FlashGaze
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
pip install -e ".[vlm-multi]"     # 可选 LiteLLM 后端（use_litellm=True，VLM 提供商）
pip install -e ".[gui]"           # Web GUI（基于 Gradio），安装后运行 flashgaze-webui
pip install -e ".[heic]"          # HEIC/HEIF 格式支持（pillow-heif）
pip install -e ".[all]"           # 除 portrait 与 mcp 外的全部（刻意为之，见 pyproject.toml）
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

# 工作空间清理 —— 先试运行（只报告，不删除任何文件）
flashgaze cleanup ./photos --top 30 --no-vlm --dry-run

# 确认无误后实际删除低分图（删除前会打印待删数量）
flashgaze cleanup ./photos --top 30 --no-vlm --apply
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
| `--export-dir PATH` | 导出目标目录（默认 `./精选`；需搭配 `--export`，单独提供会被拒绝、退出码 1；相对路径以被扫描目录为基准解析，越出被扫描目录的路径会被拒绝，退出码 1） |
| `--move` | 移动而非复制（需搭配 `--export`，单独提供会被拒绝、退出码 1） |
| `--json` | 输出 JSON 清单到 stdout |
| `--csv` | 输出 CSV 清单 |
| `--output PATH` | JSON 清单输出到文件（需搭配 `--json`；越出被扫描目录的路径会被拒绝，退出码 1） |
| `--csv-output PATH` | CSV 清单输出路径（需搭配 `--csv`；默认 `flashgaze_result.csv`；越出被扫描目录的路径会被拒绝，退出码 1） |
| `--exif` | 将最终评分写回图片 EXIF 元数据（仅 JPEG/WebP；需 `pip install -e ".[exif]"`） |
| `--no-exif-backup` | 写 EXIF 时不创建 `.flashgaze_backup` 原文件备份（危险：原地改写且无回滚点，须配合 `--force` 确认） |
| `--force` | 危险操作确认开关：`--no-exif-backup` 必须配合使用（与 cleanup 护栏旗同语义） |
| `--xlsx` | 额外生成 `.xlsx` 评分表（需 `pip install -e ".[xlsx]"`） |
| `--xlsx-output PATH` | `.xlsx` 输出路径（需搭配 `--xlsx`；默认 `flashgaze_result.xlsx`；越出被扫描目录的路径会被拒绝，退出码 1） |
| `--enable-plugins` | 启用插件评分阶段（自动发现内置与用户插件目录） |
| `--plugin-dir PATH` | 额外插件目录，与内置及用户目录合并发现 |
| `--no-vlm` | 禁用 VLM，仅用 CV（零 API 成本） |
| `--vlm-provider 提供商` | VLM 提供商：`qwen`（默认）/ `openai` / `anthropic` / `ollama`。全部走内置 pin 直连层（无需 LiteLLM）；`.[vlm-multi]` 仅用于可选的 LiteLLM 后端 |
| `--scene 场景` | 场景化评分模式：`auto`（默认）/ `portrait` / `landscape` / `still_life` |
| `--enable-composition` | 启用构图评分 *（实验性）* |
| `--enable-noise` | 启用 BRISQUE 无参考噪点评分 *（需 opencv-contrib-python + 模型文件）* |
| `--enable-color` | 启用色彩丰富度评分 |
| `--enable-portrait` | 启用人像专项评分（人脸数 + 区域清晰度，加分 +3~5） *（需 face_recognition）* |
| `--enable-dedup` | 启用 PHash 图片去重（相似图保留最高分） *（需 imagededup）* |
| `--dedup-threshold N` | PHash 汉明距离阈值（默认 8，越小越严格） |
| `--weights JSON` | 自定义权重 JSON，如 `'{"sharpness":0.5,"exposure":0.3,"composition":0.2}'`，可选 key：`composition`/`noise`/`color` |
| `--workers N` | 并发工作进程数（默认 4）：CV 评分走进程池，VLM 调用走线程池 |
| `--config-file PATH` | JSON 配置文件路径 |
| `--verbose` | 详细日志（stderr；逐行输出 `进度 k/N`，替代终端进度条） |
| `--no-downscale` | 禁用大图降采样，使用原始分辨率处理（默认长边超 2048px 时降采样以降低内存占用） |
| `--api-key KEY` | VLM API Key（覆盖环境变量；会进入进程命令行，建议改用 `--api-key-file`） |
| `--api-key-file PATH` | 从文件读取 VLM API Key（`-` 表示读 stdin），避免密钥进入进程命令行；与 `--api-key` 互斥（同传退出码 1） |
| `--api-base URL` | VLM 端点（覆盖环境变量） |
| `--model NAME` | VLM 模型名称（覆盖环境变量） |
| `--version` | 显示版本号并退出 |

> **超大图**（默认超过 **6400 万像素**）在**解码前**即被拒：报告中该图 `error` 非空（`图片尺寸超限：…`）、分数 0，且不参与 VLM 评分；同批其余图照常评分，退出码不变。这是解压炸弹防护——一个几百字节的文件可以声明上亿像素，令解码器分配数 GB 内存。用 `FLASHGAZE_MAX_IMAGE_PIXELS` 调高上限（如 100MP+ 中画幅设 `200000000`），或置 `0` 恢复此前的无上限行为。

进度显示约定：stderr 连接真实终端时在 stderr 渲染进度条（stdout 始终只输出 JSON）；管道/重定向（CI、Agent 调用）下不输出任何进度；`--verbose` 时进度改为逐行日志。

## VLM 提供商

FlashGaze 通过**同一套自管 pin-IP 直连层**支持四个 VLM 提供商——**无任何厂商专属适配代码，且默认无需 LiteLLM**。所有 provider（qwen / openai / anthropic / ollama）在构造期解析并 **pin 单一 IP**，随后直连该 IP（固定 `Host` 头 + HTTPS SNI pin + `allow_redirects=False`），彻底消除 DNS 重绑定 TOCTOU 绕过面（含云元数据 `169.254.169.254` / 私网）。LiteLLM 仅作为**可选 opt-in 后端**（`VLMClient(use_litellm=True)`）用于特殊兼容场景。

| 提供商 | 模型示例 | API 端点 | 是否需要 LiteLLM |
|---|---|---|---|
| `qwen`（默认） | `qwen-vl-max` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 否 |
| `openai` | `gpt-4o` | `https://api.openai.com/v1` | 否（内置 pin 直连层） |
| `anthropic` | `claude-3-5-sonnet-20241022` | `https://api.anthropic.com` | 否（内置 pin 直连层） |
| `ollama` | `llama3.2-vision` | `http://localhost:11434` | 否（内置 pin 直连层） |

> **局域网 / Docker 自托管 Ollama：** 内置 SSRF 防护会对公网云 provider 拒绝私网/链路本地地址（如 `192.168.x`、`10.x`、`172.17.x`、Docker 网关 `169.254.x`）。**`ollama` 被视为自托管 provider，默认即放行这些目标**——只需把 `FLASHGAZE_API_BASE` 指向局域网主机（如 `http://192.168.1.10:11434`）即可开箱即用。pin-IP 直连（无 DNS 重绑定 TOCTOU）仍然生效。若需**非 ollama** 的自托管（如私网内的 qwen/openai 兼容端点），显式设置 `FLASHGAZE_ALLOW_PRIVATE_TARGETS=true` 即可放行。

> **端点白名单（仅告警、不阻断）：** `api_base` 有四条互不校验的来源（环境变量、JSON 配置文件、CLI `--api-base`、WebUI 文本框），而 API Key 与全部图片内容都会被 POST 到它指向的主机。因此 `build_config` 会按白名单校验端点，未覆盖时打一条 **WARNING**（含主机、原因与处置建议）——**不阻断运行**，自托管场景不受影响。私网/回环主机在 `provider=ollama` 或 `FLASHGAZE_ALLOW_PRIVATE_TARGETS=true` 下免白名单。消除告警的两个办法：把主机加入 `FLASHGAZE_API_BASE_ALLOWLIST`，或设置 `FLASHGAZE_ALLOW_UNTRUSTED_API_BASE=1`。这项检查对配置文件来源尤其重要——clone 第三方仓库携带的配置可以在无声无息中把密钥与图片导向别处。

> **代理与 pin-IP 互斥（设计如此）：** 直连层 Session 置 `trust_env=False`，`HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` / `NO_PROXY` 与 `REQUESTS_CA_BUNDLE` / `CURL_CA_BUNDLE` **一律不生效**——代理会自行解析目标主机名（被替换的 CA 则会破坏证书校验），从而静默旁路上述 pin-IP / Host pin / SNI pin 保证。构造期检测到其中任一变量时会打一次 `WARNING`。确需经代理访问 VLM 端点时，可改用 opt-in 的 LiteLLM 后端（`VLMClient(use_litellm=True)`）——它不走 pin-IP 直连，是否遵循环境代理由 LiteLLM 自身决定（不在本模块控制范围内）。

**配置示例：**

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
```

> **可选 LiteLLM 后端：** 如需走 LiteLLM 而非内置 pin 直连层，可在编程接口传入 `VLMClient(use_litellm=True)`。该模式仅用于特殊端点；构造期静态 SSRF 校验仍然生效。

**优雅降级：** 若 VLM 调用失败（网络/超时/响应异常），返回 `ok=False`，批处理继续以纯 CV 模式完成——绝不抛异常。非法 `provider`/`scene` 值回退到默认值并记 warning。

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
| 噪点（BRISQUE） | `pip install -e ".[cv-enhanced]"`——BRISQUE 模型文件已随包分发于 `flashgaze/models/brisque/`（见该目录 README；用 `python -c "from importlib.resources import files; print(files('flashgaze.models') / 'brisque')"` 定位）。仅当随包文件缺失时才需手动放置或经 `FLASHGAZE_BRISQUE_ALLOW_DOWNLOAD=1` 联网下载 | 惩罚噪点多/压缩重的图片 |
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
| `vlm-multi` | `pip install -e ".[vlm-multi]"` | 可选 LiteLLM 后端（`use_litellm=True`） | GPT-4o / Claude 3 / Ollama | [VLM 提供商](#vlm-提供商) |
| `gui` | `pip install -e ".[gui]"` | `flashgaze-webui` | 浏览器 GUI | [Web GUI](#web-gui) |
| `heic` | `pip install -e ".[heic]"` | 解码 HEIC/HEIF 时自动启用 | HEIC/HEIF 格式支持（pillow-heif） | [安装](#安装) |
| `exif` | `pip install -e ".[exif]"` | `--exif`（`--no-exif-backup`） | 评分写回图片 EXIF（JPEG/WebP） | [CLI 选项](#cli-选项) |
| `xlsx` | `pip install -e ".[xlsx]"` | `--xlsx`（`--xlsx-output`） | 生成 `.xlsx` 评分表 | [CLI 选项](#cli-选项) |
| _插件_ | 内置，无 extra | `--enable-plugins`（`--plugin-dir`） | 可发现式插件评分阶段 | [CLI 选项](#cli-选项) |
| `all` | `pip install -e ".[all]"` | 以上全部 | 一次安装除 `portrait` 与 `mcp` 外的全部（刻意为之，与迁移前 setup.py 一致） | — |

**EXIF 写回**（`pip install -e ".[exif]"`）：`--exif` 将最终 0–100 分（及入选标记）写入图片 EXIF 的 `UserComment` 字段，另写 `ImageDescription`（ASCII 理由）与 `Software`（`FlashGaze/<provider>`）。仅 JPEG/WebP；加 `--no-exif-backup` 可跳过 `.flashgaze_backup` 原文件备份。

**Excel 导出**（`pip install -e ".[xlsx]"`）：`--xlsx` 生成 `flashgaze_result.xlsx`（用 `--xlsx-output` 改路径），列与 CSV 报告一致。

**插件系统**（内置）：`--enable-plugins` 启用插件评分阶段，自动发现 `flashgaze/plugins/builtin/` 与 `~/.flashgaze/plugins/`；`--plugin-dir` 追加额外目录。无需 `pip` extra。

## MCP Server

FlashGaze 内置 MCP Server。安装 `pip install -e ".[mcp]"` 后，在 AI 工具的 MCP 配置中添加：

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

> **上传/单图评分的路径边界：** `score_uploaded_images` / `score_single_image` 仅读取 `FLASHGAZE_MCP_ALLOWED_ROOTS`（逗号分隔目录）配置的**允许扫描根**内的图片；未配置时默认仅限 MCP 服务器的启动目录。越界路径不会被读取、解码或送往 VLM 端点——`score_uploaded_images` 将其列入 `details.skipped`（附拒绝原因），`score_single_image` 直接拒绝（code 1）。

> **配置文件支持**：MCP Server 会像 CLI 的 `--config-file` 一样加载 `FLASHGAZE_CONFIG_FILE` 指向的 JSON 配置文件——加到上方 `env` 块即可。MCP 内优先级：工具参数 > 环境变量 > 配置文件 > 默认值。

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

`cleanup_workspace_images` 工具（以及等价的 CLI 子命令 `flashgaze cleanup`）强制执行严格的安全边界：

- 所有删除操作限制在 `workspace` 目录内，目录外文件绝不受影响
- 双重路径穿越检查：解析真实路径后通过 `relative_to` 校验是否在工作空间内
- 默认 `dry_run=True`（CLI 为 `--dry-run`），只报告待删文件列表，不实际删除；CLI 需显式 `--apply` 才真正删除
- 每个文件删除前再次校验路径边界
- 批量删除比例护栏：待删比例超过可评分图的 95% 且已评分图总数不少于 6 时整批拦截——**一张不删**，全部候选进入 `details.blocked_files`。比例按可评分图口径计算：损坏图（评分失败，error 非 None）既不计入分子也不计入分母，不会稀释比例绕过护栏

**程序化约定（护栏拦截）**：护栏触发时工具返回非 0 结果——`status="blocked"`、`code=1`、`summary.force_required=true`；响应仍是标准六字段结构，`summary` 与 `details.blocked_files` 完整可读。核对清单后显式传 `force=True` 重跑即返回 `status="success"`、`code=0`。等价 CLI（`flashgaze cleanup`）用**进程退出码 `1`** 表达同一状态并打印错误日志。即：CLI 以退出码表达，MCP 以 JSON 的 `status`/`code` 表达。

**程序化约定（删除失败）**：个别图片删除失败（文件被其它程序占用、只读属性、与回收站跨卷）时，工具返回 `status="partial"`、`code=5`，`summary.delete_failures` 给出未删除张数、`details.delete_failures` 给出逐项 `{path, reason}`；其余图片照常处理，删除失败的低分图仍留在磁盘上（回收站移动绝不降级为直接 `unlink`）。全部删除成功时 `summary.delete_failures` 显式为 `0`。等价 CLI（`flashgaze cleanup`）用**进程退出码 `5`** 表达同一状态。

</details>

## Web GUI

FlashGaze 提供基于 Gradio 的可选 Web GUI，把 CLI 的全部参数映射到界面控件，评分调用复用同一套 `HybridScorer`，不引入任何新的评分代码路径。配置文件在此同样生效：在服务进程环境中设置 `FLASHGAZE_CONFIG_FILE`，其值会作为配置文件层应用于每次评分（表单输入仍优先于它，遵循 CLI 参数 > 环境变量 > 配置文件 > 默认值）。

**安装与启动：**

```bash
pip install -e ".[gui]"
flashgaze-webui
```

> 已验证 gradio 6.24.0。

浏览器访问 `http://127.0.0.1:7860`。默认仅本机可访问，局域网访问需显式传 `--host 0.0.0.0`。

**启动参数：**

| 参数 | 说明 |
|---|---|
| `--host HOST` | 监听地址（默认 `127.0.0.1`；局域网访问用 `0.0.0.0`） |
| `--port PORT` | 监听端口（默认 `7860`） |
| `--dir PATH` | 预填图片目录（仅填入输入框，不自动开始评分） |
| `--share` | 启用 Gradio 临时公网链接 |
| `--auth user:pass` | 对外暴露时的登录凭据（`user:password`）；公网绑定（`--host 0.0.0.0` 或 `--share`）时强制鉴权——省略则自动生成随机令牌（用户名 `admin`）打印到 stderr |
| `--allow-root DIR` | 允许评分的根目录白名单（可重复传入）；提供后仅这些目录内可被扫描 |
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
8. **导出** — 复制/移动到目录（`--export`）、下载 JSON（`--json`）、下载 CSV（`--csv`）、下载 XLSX（`--xlsx`）

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
    capture_output=True,
    text=True,
    timeout=600,
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
| `FLASHGAZE_CONFIG_FILE` | **三入口共用的配置文件**：指向 JSON 配置文件的路径，在 `build_config` 内部作为 file 层加载——CLI、MCP Server、Web GUI 行为完全一致。与 CLI `--config-file` 同层（逐键合并，同时设置时 `--config-file` 的键优先）；仍低于其它环境变量。无默认路径探测：未设置即不加载。文件缺失/损坏记 WARNING 并回退默认值。 | 未设置 |
| `FLASHGAZE_API_KEY` | VLM API Key（`--no-vlm` 模式不需要） | — |
| `FLASHGAZE_API_BASE` | API 端点 | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `FLASHGAZE_MODEL` | 模型名称 | `qwen-vl-max` |
| `FLASHGAZE_VLM_PROVIDER` | VLM 提供商：`qwen`/`openai`/`anthropic`/`ollama` | `qwen` |
| `FLASHGAZE_SCENE` | 场景模式：`auto`/`portrait`/`landscape`/`still_life` | `auto` |
| `FLASHGAZE_WEIGHTS` | 评分权重 JSON，如 `{"sharpness":0.5,"exposure":0.5}`——`sharpness`/`exposure` 必填，`composition`/`noise`/`color` 可选，自动归一化到总和 1 | 内置 `清晰度 0.5 / 曝光度 0.5` |
| `FLASHGAZE_DEDUP_THRESHOLD` | 去重（`--enable-dedup`）PHash 汉明距离阈值，越小越严格 | `8` |
| `FLASHGAZE_ALLOW_PRIVATE_TARGETS` | **SSRF 逃生通道**：设为 `true` 可放行 VLM 端点解析到私网/链路本地/保留/组播地址（如自托管的 qwen/openai 兼容端点）。默认 `false`，对公网云 provider 维持防护。`ollama` 已默认放行私网目标，故此变量仅用于非 ollama 的自托管场景。 | `false` |
| `FLASHGAZE_API_BASE_ALLOWLIST` | **端点白名单**：逗号分隔的主机后缀，用于追加内置官方域名（`dashscope.aliyuncs.com`、`dashscope-intl.aliyuncs.com`、`api.openai.com`、`api.anthropic.com`、`localhost`、`host.docker.internal`）。匹配口径为「主机相等或以 `.条目` 结尾」，故 `dashscope.aliyuncs.com.evil.com` **不会**误命中。 | 内置官方域名 |
| `FLASHGAZE_MCP_ALLOWED_ROOTS` | **MCP 上传/单图评分的允许扫描根**：逗号分隔的目录白名单，`score_uploaded_images` / `score_single_image` 仅允许读取这些目录内的图片，越界路径在做任何文件访问前即被拒绝；无关闭边界的开关。 | MCP 服务器启动目录 |
| `FLASHGAZE_ALLOW_UNTRUSTED_API_BASE` | 设为 `1`/`true`/`yes`/`on` 表示已确认当前 `api_base` 可信，非白名单端点不再告警（自托管 / 自建网关场景）。 | 未设置 |
| `FLASHGAZE_TIMEOUT` | 请求超时（秒） | `30` |
| `FLASHGAZE_WORKERS` | 并发工作进程数（CV 评分走进程池，VLM 调用走线程池） | `4` |
| `FLASHGAZE_MAX_RETRIES` | VLM 重试次数（仅超时/连接错误） | `3` |
| `FLASHGAZE_VLM_MAX_ADJUSTMENT` | VLM 补偿上限 | `10.0` |
| `FLASHGAZE_VLM_BREAKER_THRESHOLD` | 批量熔断：连续 N 张 VLM 调用失败（或样本 ≥20 张且失败率 ≥80%）即熔断，剩余图跳过 VLM、以纯 CV 口径出分并在 cleanup 报告中标记。`0` = 关闭熔断。 | `5` |
| `FLASHGAZE_VLM_TEMPERATURE` | VLM 采样温度，钳制到 `[0, 2]`（provider 层再钳制——Anthropic 上限 `1.0`）。默认固定为 0 以收敛采样随机性；配置文件置 `null` 表示完全不发送该参数（沿用服务端默认）。 | `0.0` |
| `FLASHGAZE_VLM_SEED` | VLM 固定随机种子，仅对协议支持的 provider 注入（`qwen`/`openai`；Anthropic 协议无 `seed` 字段，Ollama 的 OpenAI 兼容层未承诺支持）。必须为非负整数；配置文件置 `null` 表示不发送。实际生效参数回显在 JSON 报告 `summary.vlm_sampling`。 | `42` |
| `FLASHGAZE_MAX_IMAGE_PIXELS` | **解码像素预算**：头部声明的像素数超过此值的图片在**分配像素缓冲之前**即被拒（解压炸弹防护），降级为 `error` 占位而非 OOM。100MP+ 中画幅可调高；置 `0` 关闭本项目上限、沿用 Pillow 自带阈值（约 89M 告警 / 178M 抛错）。 | `64000000` |
| `FLASHGAZE_USER_PLUGINS` | 设为 `1` 启用扫描用户插件目录 `~/.flashgaze/plugins`（默认关闭，防 RCE；显式 `--plugin-dir` 始终可用） | 未设置 |
| `FLASHGAZE_BRISQUE_ALLOW_DOWNLOAD` | 设为 `1` 允许联网下载缺失的 BRISQUE 模型文件（限长并经 SHA256 校验；默认关闭——缺文件时优雅降级而非隐式联网） | 未设置 |

文件配置格式见 `config.example.json`。`weights` 字段有三种设置途径：CLI `--weights`（JSON 字符串）、环境变量 `FLASHGAZE_WEIGHTS`、配置文件。配置文件对**三个入口**一致生效：CLI 用 `--config-file`，CLI / MCP / Web GUI 均可设 `FLASHGAZE_CONFIG_FILE`（同层逐键合并，同时设置时 `--config-file` 的键优先）。不会从工作目录自动探测任何默认配置文件名。

</details>

## 返回码

| 码 | 含义 |
|---|---|
| `0` | 成功 |
| `1` | 参数错误 |
| `2` | API 调用失败 *（保留码 — VLM 失败已降级为纯 CV）* |
| `3` | 目录无效或无图片 |
| `4` | 图片处理错误——评分阶段失败；单图失败降级为 `error` 字段，BRISQUE 模型完整性校验失败终止整批时也返回本码（见下方说明） |
| `5` | 导出失败或部分失败——存在未能导出的入选图（磁盘满 / 权限不足 / 源文件被外部删除 / 导出目标是普通文件）。导出与清单照常产出，`--json` 报告暴露 `summary.export_failed` 与逐项 `summary.export.failures`；与码 `7` 同时成立时本码优先 |
| `6` | 配置错误（缺 API Key 等） |
| `7` | EXIF 写入失败——至少一张图未成功写入；导出/清单照常产出，JSON 报告暴露 `summary.exif_failed` 与逐项 `summary.exif.failures` |
| `8` | 未预期的内部错误——子命令抛出了未被自身收敛的异常。错误类型与信息以单行日志写入 stderr（`未预期的内部错误（<类型>）: <msg>`），进程绝不打印 traceback（堆栈仅在 DEBUG 级别输出，即需 `--verbose`） |

> 码 2 为保留码：VLM 调用失败降级为纯 CV（补偿 0）。单图损坏同样降级为该图 `error` 字段且 `score=0`，不中断流程；码 `4` 本身仅在整批评分失败（如 BRISQUE 模型完整性校验失败）时产生（见下方说明）。
>
> 码 `8` 由 `main()` 的最后防线兜底层产生：子命令未映射的异常在此被捕获，不再以裸 traceback 终结进程并返回 Python 默认的 1。评分器构造失败（`make_scorer`）在此之前已分流——`BrisqueIntegrityError`（模型哈希不符的供应链信号）记「模型完整性校验失败」并映射 `4`，其余构造异常映射 `6`（配置/环境不可用，如端点被 SSRF 防护拒绝）。多进程评分（`--workers >1`）下该信号在进程池预热阶段即被检出：initializer 置位共享标志后响亮失败，主循环立即以退出码 `4` 终止，不降级串行重跑、不产生逐图 error 占位。
>
> `--exif --no-exif-backup` 未加 `--force` 时同样返回 `1`：无回滚点的原地改写原图属危险操作，必须显式确认。
>
> `flashgaze cleanup` 被批量删除护栏拦截时同样返回 `1`（一张未删，确认后加 `--force` 重跑）；MCP 侧对应 `status="blocked"` / `code=1`，详见 [MCP Server](#mcp-server)。
>
> `flashgaze score --export` 存在未能导出的入选图时返回 `5`（此前此类部分失败静默返回 0）；MCP `export_selected_images` 对应 `status="partial"` / `code=5`，`summary.export_failed` 给出失败计数、`details.failures` 列出逐项原因。零失败时 CLI 仍为 0，MCP 仍为 `status="success"` 且显式 `summary.export_failed=0`。
>
> `flashgaze cleanup` 存在未能删除的低分图时（被占用 / 只读 / 跨卷）同样返回 `5`；MCP `cleanup_workspace_images` 对应 `status="partial"` / `code=5`，`summary.delete_failures` 给出失败计数、`details.delete_failures` 列出逐项原因，详见 [MCP Server](#mcp-server)。

## 测试

```bash
pip install -r requirements-dev.txt
pytest tests/ -v --cov=flashgaze --cov-report=term-missing
```

默认运行带内置过滤（`pyproject.toml` 的 `[tool.pytest.ini_options]`，审查项 M-17）：`addopts = '-m "not e2e"'` + `testpaths = ["tests"]`——裸跑 `pytest` / `pytest tests/` 只收集 `tests/`，不触及浏览器 E2E 与顶层 `benchmarks/`，「什么算一次通过」由此有机器可执行的单一定义。命令行显式 `-m` 会整体覆盖默认（自定义时须写全排除项，如 `-m "not slow and not e2e"`）；`-o addopts=` 整体解除默认过滤；一键入口为 `make test` / `make test-all`。

默认口径下共收集 1080 项测试（装齐安全 extras 时实测 1052 通过 / 28 跳过，10 项浏览器 E2E 被默认过滤取消选择；gradio 缺失的环境 WebUI 各层自动跳过），覆盖 CV 引擎、VLM 客户端、混合评分器、导出器、CLI 解析器、端到端流程、可复现性、配置层，以及下述 Web GUI 三层覆盖。

覆盖率门禁：总覆盖率须 ≥ 80%（配置在 `.coveragerc`，本地与 CI 的同一条 `pytest --cov` 命令都会强制执行）。`mcp_server` 与 `webui/app` 已纳入门槛——CI 主矩阵加装 `mcp` extra 使其测试在主矩阵激活。三个重依赖可选模块（`xlsx_exporter`、`deduplicator`、`portrait_engine`）不纳入主门槛，由 CI 的 `extras` job 硬门槛强制（`.coveragerc-extras`：无条件总下限 50% + `ci.yml` 逐模块下限；见 `docs/extras-governance.md`）。

### Web GUI 测试分层

Gradio Web GUI 在纯逻辑测试（`tests/test_webui.py`）之上分三层覆盖，gradio 缺失时均优雅跳过：

- **冒烟**（`tests/test_webui_smoke.py`）：`build_app()` 能在当前 gradio 下装配出 `Blocks`——不占端口、不开浏览器。
- **组件级**（`tests/test_webui_components.py`）：组件树与默认值、经 `demo.fns` 校验事件绑定（每个 `click`/`change` 的输入/输出顺序）、直接调用按钮背后的闭包处理器——表单装配、错误状态、筛选、导出与下载。随 CI `extras` job 运行。
- **E2E**（`tests/e2e/`，marker `e2e`）：在临时端口启动真实 Gradio 服务，用 Playwright 驱动浏览器——表单交互（VLM 开关、`top` 输入）、错误提示、结果渲染（状态/JSON 摘要/表格/画廊）、筛选、导出与 JSON 下载。由阻塞的 CI `e2e` job 运行，覆盖 **Chromium 与 Firefox**（均为必选门禁）；WebKit 为可选。

```bash
pip install -e ".[gui,xlsx]" -r requirements-dev.txt -r requirements-e2e.txt
# 安装所需浏览器二进制（Windows/macOS 去掉 --with-deps）
python -m playwright install chromium firefox          # 必选门禁
python -m playwright install webkit                   # 可选，如需 WebKit
pytest tests/test_webui_components.py -v     # 组件级（无需浏览器）
pytest tests/e2e -m "e2e" -v --browser chromium       # E2E，Chromium（默认）
pytest tests/e2e -m "e2e" -v --browser firefox        # E2E，Firefox（必选门禁）
pytest tests/e2e -m "e2e" -v --browser webkit         # E2E，WebKit（可选）
pytest tests/ -m "not e2e"                   # 除浏览器用例外的全部测试（与内置默认一致，兼容旧口径保留）
```

## 性能基准

```bash
pip install -r requirements-dev.txt        # 已含 pytest-benchmark
pytest benchmarks/ -m "not bench_full" --benchmark-autosave
```

性能基准位于顶层 `benchmarks/` 目录（pytest-benchmark；`pytest tests/` 不会收集它们）。`benchmark.yml` 工作流对每个 PR 做门禁：merge-base 基线与 PR head **在同一个 runner 上**先后运行，`mean` 回归超过 **15%** 即 CI 失败，并在 Job Summary 输出对比表。main 分支推送与 nightly 定时任务会把结果累积到 `gh-pages` 分支，在 `https://<org>.github.io/FlashGaze/dev/bench/` 渲染趋势图。基准清单、阈值调整与本地用法见 [docs/bench/README.md](docs/bench/README.md)。

## 类型检查

```bash
pip install -r requirements-dev.txt
python -m mypy
```

静态类型检查使用 mypy，CI 中由 `typecheck` job 执行（阻塞主流程）。配置位于 `pyproject.toml` 的 `[tool.mypy]`：已全面启用 **strict 严格模式**（`strict = true`），检查范围覆盖 `flashgaze` 包、`tests/` 与基准辅助脚本 `tools/bench/`——既定的逐阶段收紧路线图（按模块打开 `disallow_untyped_defs` → 全局加严 → 最终 `strict = true`）已全部完成。可选依赖（gradio / mcp / piexif 等）经 `ignore_missing_imports` overrides 处理，只装基础依赖即可得到与 CI 完全一致的结果。同样的检查在提交前也会由 pre-commit 钩子与 Makefile 在本地运行——见下方「本地代码质量守护」。

## 代码规范

```bash
pip install -r requirements-dev.txt
python -m ruff format .        # 提交前先格式化
python -m ruff check .
```

代码规范检查与格式化使用 ruff，CI 中由 `lint` job 执行（阻塞主流程）。配置位于 `pyproject.toml` 的 `[tool.ruff]`：`target-version = "py310"`、行宽 100，规则集跟随 ruff 0.16 默认（413 条），仅关闭对中文注释/字符串全量误报的 RUF001-003。ruff 版本钉在 minor 区间（`>=0.16,<0.17`）——ruff 0.x 的 minor 版本会扩充默认规则集，升级经 Dependabot 月度 PR 评审后进入。容错路径上刻意捕获 `Exception` 的位置（单图/单插件降级、入口错误码收敛）均带行级 `# noqa: BLE001` 及理由。同样的检查在提交前也会由 pre-commit 钩子与 Makefile 在本地运行——见下方「本地代码质量守护」。

## 安全扫描

依赖安全扫描由独立的 `security.yml` 工作流执行，触发方式：**每个 pull request**（发现漏洞时该检查失败）、**每日定时**与**手动触发**（`workflow_dispatch`）。

- **工具**：[pip-audit](https://github.com/pypa/pip-audit) 审计**已安装环境**——即 `pyproject.toml`（单一配置源）经 pip 解析后的真实传递依赖树——漏洞数据来自 OSV 与 PyPI advisory 数据库。
- **失败策略**：核心（随产品分发）依赖发现已知 CVE 即该检查失败；失败是否真正阻塞合并取决于仓库分支保护配置——如需强制阻塞，可在 *Settings → Branches* 中将本检查（`Security`）设为 required status check。`requirements-dev.txt` 单独以**仅观察**模式扫描（`continue-on-error`）——dev 工具链不随产品分发。
- **豁免机制**：确需临时豁免的漏洞在 `security.yml` 的 `PIP_AUDIT_IGNORE` 变量中集中声明并映射为 `--ignore-vuln`；每条豁免必须注明漏洞 ID、原因（如"版本上限为兼容刻意 pin，暂无修复版本"）与复审日期。
- **与 Dependabot 的分工**：pip-audit 负责**发现**已知漏洞，`dependabot.yml` 负责**修复**（提出版本升级 PR）。

## 本地代码质量守护

目前 ruff 与 mypy **仅在 CI 中运行**，不合规代码仍可能被提交。仓库内置两套互补的本地守护，复用与 CI `lint` / `typecheck` job **完全相同**的命令（版本与规则统一来自 `pyproject.toml`，单一配置源、零漂移）：

- **pre-commit 钩子**（`.pre-commit-config.yaml`）：每次 `git commit` 自动运行 `ruff check`、`ruff format --check` 与 `mypy`。只需安装一次：
  ```bash
  pip install -r requirements-dev.txt
  pre-commit install
  ```
  之后每个提交都会被拦截，直到三项检查全部通过。对所有文件手动运行：`pre-commit run --all-files`。

- **Makefile**（一键手动检查，也便于本地复刻 CI）：
  ```bash
  make check        # lint + format-check + typecheck（完整本地守护）
  make lint         # python -m ruff check .
  make format       # python -m ruff format .
  make format-check # python -m ruff format --check .
  make typecheck    # python -m mypy
  make test         # python -m pytest tests/ -q（内置默认口径，自动排除 e2e）
  make test-all     # python -m pytest tests/ -q -o addopts=（全量，含 e2e）
  make hooks        # pre-commit run --all-files
  make install      # pip install -r requirements-dev.txt && pre-commit install
  make dist         # 本地构建并校验发布产物（等价于发布流水线的构建验证）
  ```
  Windows 未装 GNU make 时，可直接运行等价的 `python -m …` 命令（Makefile 位于仓库根，即 `pyproject.toml` 所在目录）。

两套守护都**只检查不自动修复**（与 CI `--check` 一致），不合规的提交会被阻断，而不会被静默改写。

## 技术栈

| 依赖 | 用途 |
|---|---|
| Python 3.10+ | 运行时 |
| OpenCV 4.x | CV 评分（拉普拉斯方差、直方图、Otsu 阈值分割） |
| Pillow | 主图片解码器（单次解码 → BGR 并按 EXIF 转正；WebP/BMP/TIFF，HEIC 可选） |
| NumPy | 数组运算 |
| json5 | VLM 响应的宽松 JSON 解析（容忍代码围栏、尾逗号） |
| tqdm | 终端进度条（仅渲染到 stderr） |
| requests | VLM API 调用（Qwen-VL / OpenAI 兼容端点） |
| litellm | 可选 LiteLLM 后端（`use_litellm=True` 启用） *（可选安装）* |
| mcp | MCP Server *（可选安装）* |

## 发布流程

发布由 `release.yml` 工作流全自动完成：推送版本标签后，构建 sdist + wheel、校验随包数据文件、在干净 venv 中冒烟安装验证，随后发布到 PyPI 并创建携带同一套产物的 GitHub Release。

**发版三步**（在 CI 全绿的 main commit 上）：

1. 更新 `flashgaze/__init__.py` 的 `__version__`——版本号的唯一来源。
2. 把 `CHANGELOG.md` 的 `[未发布]` 标题改为 `[x.y.z] - YYYY-MM-DD`。
3. 打标签并推送：
   ```bash
   git tag vx.y.z
   git push origin vx.y.z
   ```

也可以在 **Actions** 页手动触发（`Run workflow`），但手动触发**恒为演练**——只构建与验证，不发布任何内容；真实发布必须打标签推送（手动触发时工作流运行在分支引用上，发布路径被刻意排除）。

**认证方式（PyPI Trusted Publishing / OIDC）**：无需任何仓库 Secret。首次发布前，须在本项目的 PyPI 页面（*Publishing* 区块）注册一个 *Trusted Publisher*（受信任发布者），填写：

- **Repository（仓库）**：`https://github.com/<owner>/<repo>`（即本仓库）
- **Workflow name（工作流名）**：`release`（`.github/workflows/release.yml` 的文件名，不含 `.yml`）
- **Environment（环境）**：留空

`publish` job 已声明 `permissions: id-token: write`，`pypa/gh-action-pypi-publish` action 会自动用该短期 OIDC 令牌换取 PyPI 凭据完成发布——全程不存储任何长期有效的 API Token。

**失败处理简表**：

| 失败阶段 | 副作用 | 恢复方式 |
|---|---|---|
| preflight / build / verify | 无——尚未发布 | 直接修复后重跑工作流 |
| PyPI 上传 | 无（或不完整）——Release 不会创建 | 重跑工作流；同版本文件不可重传，重试前先在 PyPI 核对已上传的文件 |
| 仅 GitHub Release | PyPI 已发布成功 | 单独重跑失败的 `github-release` job |

**本地预演**（与工作流等价命令）：

```bash
pip install build twine
python -m build
twine check --strict dist/*
```

---

<div align="center">

**MIT License**

</div>
