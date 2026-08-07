"""FlashGaze Web GUI（基于 Gradio）。

作为可选功能模块，需通过 `pip install -e ".[gui]"` 安装 gradio 依赖后使用。
启动命令：`flashgaze-webui`。

设计原则：
- 评分逻辑单一来源：复用 `build_config` / `HybridScorer` / `Exporter`，不复制评分代码
- 与 CLI 完全对齐：所有 CLI 参数都可在界面上配置
- 离线模式可用：`--no-vlm` 模式下整条评分链与 CLI 完全一致
- 优雅降级：gradio 缺失时给出明确提示，不阻塞 CLI / MCP 主流程
"""

from __future__ import annotations

try:
    import gradio  # noqa: F401  仅供缺失检测
    _GRADIO_AVAILABLE = True
except ImportError:
    _GRADIO_AVAILABLE = False


def is_available() -> bool:
    """返回 gradio 依赖是否已安装。"""
    return _GRADIO_AVAILABLE
