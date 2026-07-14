# 瞬选灵眸（FlashGaze）

AI 辅助图片评分 CLI 工具。对本地图片（JPG/PNG/WebP）进行混合评分，筛选高质量照片，供 AI Agent 稳定调用。

## 核心特性

- **混合评分引擎**：CV 客观分（拉普拉斯方差 + 直方图）主导，VLM 场景补偿 ±10 分微调
- **Agent 友好**：标准返回码、JSON 输出、可被 `subprocess` 稳定调用
- **可复现**：同一张图连续运行 10 次分数完全一致（`--no-vlm` 模式）
- **成本可控**：`--no-vlm` 零 API 成本，`--workers` 控制并发
- **MCP Server**：可作为 MCP 工具被 Claude Code / TRAE / Cursor / Codex 直接调用

## 快速开始

```bash
# 安装
pip install -e .

# 配置 API Key（可选，--no-vlm 模式不需要）
export FLASHGAZE_API_KEY="sk-your-key"

# 评分
flashgaze ./photos --top 30 --json --export

# 零成本快速初筛（仅 CV）
flashgaze ./photos --top 30 --no-vlm --csv
```

## 作为 AI Agent Skill 使用

本项目包含 `SKILL.md`，兼容 TRAE、Claude Code、Cursor 等支持 `agentskills.io` 标准的 AI 编程工具。

### TRAE 安装

```bash
# 方式一：命令行安装
npx skills add <github-username>/flashgaze

# 方式二：在 TRAE 的 SOLO 模式中说
# "安装 flashgaze skill"

# 方式三：手动复制 SKILL.md 到 .trae/skills/flashgaze/
```

### Claude Code 安装

```bash
# 命令行安装
npx skills add <github-username>/flashgaze

# 或手动放置到 .claude/skills/flashgaze/SKILL.md
```

### Cursor 安装

```bash
# 命令行安装
npx skills add <github-username>/flashgaze

# 或手动放置到 .cursor/skills/flashgaze/SKILL.md
```

### Codex 安装

本项目包含 `.codex-plugin/plugin.json`，可作为 Codex 插件使用。在 Codex CLI 中输入 `/plugins` 搜索安装。

## 作为 MCP Server 使用

FlashGaze 内置 MCP Server，可被 Claude Code、TRAE、Cursor、Codex、Windsurf 等所有支持 MCP 的工具直接调用。

### 安装 MCP 依赖

```bash
pip install -e ".[mcp]"
```

### 配置 MCP Server

在 AI 工具的 MCP 配置文件中添加：

**Claude Code / Cursor / Windsurf**（`~/.config/claude/mcp.json` 或项目级配置）：
```json
{
  "mcpServers": {
    "flashgaze": {
      "command": "python",
      "args": ["-m", "flashgaze.mcp_server"],
      "env": {}
    }
  }
}
```

**TRAE**（设置 → MCP → 添加）：
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

> Windows 用户：如果 `python` 命令找不到，请用 `python` 的完整路径，如 `C:\\Python312\\python.exe`。

### MCP 工具列表

| 工具名 | 功能 |
|---|---|
| `score_images` | 批量评分目录下所有图片，返回 JSON 评分报告 |
| `score_single_image` | 评分单张图片，返回该图详细数据 |
| `score_uploaded_images` | 对指定图片路径列表评分（不依赖目录结构） |
| `export_selected_images` | 评分后自动复制/移动高分图到目标目录 |
| `cleanup_workspace_images` | 评分后原地删除低分图（含 dry_run 安全模式） |

> **单图模式说明**：`score_single_image` 返回的 `selected` 字段恒为 False（单图无相对排序概念），判断单图是否达标请用 `score` 与自定义阈值比较。
>
> **清理模式说明**：`cleanup_workspace_images` 对损坏图（error 非空）既不删除也不入选，会保留在工作空间由用户手动处理；所有删除操作严格限制在 workspace 目录内，含路径穿越检查与 dry_run 默认开启。

### MCP 调用示例

安装配置后，在 AI 工具中直接对话即可触发：
- "帮我评估这批图片的质量"
- "选出这个目录里最好的 30 张照片"
- "给这些图片打分，把高分的复制到精选文件夹"

AI Agent 会自动调用 flashgaze 的 MCP 工具完成评分和筛选。

## CLI 选项

| 选项 | 说明 |
|---|---|
| `--top N` | 选取前 N 张高分图（默认 30） |
| `--threshold SCORE` | 分数阈值（替代 --top） |
| `--export` | 复制高分图至导出目录 |
| `--export-dir PATH` | 导出目标目录（默认 ./精选） |
| `--move` | 移动而非复制（需配合 --export） |
| `--json` | 输出 JSON 清单（stdout） |
| `--csv` | 输出 CSV 清单 |
| `--output PATH` | JSON 清单输出路径 |
| `--csv-output PATH` | CSV 清单输出路径（默认 flashgaze_result.csv） |
| `--no-vlm` | 禁用 VLM，仅用 CV |
| `--enable-composition` | 启用构图评分（实验性） |
| `--workers N` | 并发线程数（默认 4） |
| `--config-file PATH` | JSON 配置文件 |
| `--verbose` | 详细日志（stderr） |

## 返回码

| 码 | 含义 | 当前版本是否返回 |
|---|---|---|
| 0 | 成功 | 是 |
| 1 | 参数错误 | 是 |
| 2 | API 调用失败 | 否（保留码，VLM 失败已降级为 0 补偿） |
| 3 | 目录无效或无图片 | 是 |
| 4 | 图片处理错误 | 否（保留码，单图损坏已降级为 error 字段） |
| 5 | 导出失败 | 是 |
| 6 | 配置错误（缺 API Key 等） | 是 |

> 码 2 与 4 为保留码，当前版本不返回：VLM 调用失败降级为 CV-only（补偿 0），单图损坏降级为该图 error 字段且 score=0，均不中断流程。

## Agent 调用示例

```python
import subprocess, json

result = subprocess.run(
    ["flashgaze", "./photos", "--top", "30", "--json"],
    capture_output=True, text=True, timeout=600
)
if result.returncode == 0:
    report = json.loads(result.stdout)
    for img in report["images"]:
        if img["selected"]:
            print(f"入选: {img['file']} 分数={img['score']}")
```

## 配置优先级

CLI 参数 > 环境变量 > 配置文件 > 默认值

环境变量：`FLASHGAZE_API_KEY` / `FLASHGAZE_API_BASE` / `FLASHGAZE_MODEL` / `FLASHGAZE_TIMEOUT` / `FLASHGAZE_WORKERS` / `FLASHGAZE_MAX_RETRIES` / `FLASHGAZE_VLM_MAX_ADJUSTMENT`

> `weights` 仅支持配置文件设置（不支持环境变量）。

## 技术栈

- Python 3.10+
- OpenCV 4.x（CV 评分）
- Pillow（图片解码兜底）
- requests（VLM API 调用）
- mcp（MCP Server，可选安装）

## 测试

```bash
pip install -r requirements-dev.txt
pytest -v
```
