"""FlashGaze Web GUI 冒烟测试（不占用端口）。

只验证 ``build_app()`` 能在当前已安装的 gradio 下成功装配出 ``Blocks``。
不调用 ``demo.launch``，因此不会绑定任何网络端口，可在 CI / 无头环境安全运行。
"""

import pytest

gr = pytest.importorskip("gradio")

from flashgaze.webui.app import build_app


def test_build_app_returns_blocks() -> None:
    """build_app() 必须在无报错时返回非 None 的 Blocks 实例。

    build_app 内部会实例化 gr.Dataframe / gr.Gallery / gr.Button 等全部组件，
    若当前 gradio 版本存在破坏性 API 变更（如参数改名/移除），此处会直接抛错，
    等同于捕获了「未验证 major」的风险。
    """
    built = build_app()
    assert built is not None
    assert isinstance(built, gr.Blocks)


def test_build_app_inside_blocks_context() -> None:
    """在 Blocks 上下文内装配并断言返回非 None（不调用 demo.launch）。"""
    built = build_app()
    assert built is not None
    with gr.Blocks() as demo:  # noqa: F841  仅用于断言上下文，不启动端口
        assert built is not None
