"""FlashGaze Web GUI E2E 测试夹具。

在空闲端口上启动真实 Gradio 服务（``prevent_thread_lock=True``，不阻塞测试进程），
供 pytest-playwright 的 ``page`` 夹具访问。gradio 或 pytest-playwright 缺失时，
本目录整体优雅跳过。
"""

from __future__ import annotations

import shutil
import socket
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("gradio")
pytest.importorskip("pytest_playwright")  # 提供 page / browser 夹具

from flashgaze.webui.app import build_app

if TYPE_CHECKING:
    # 仅类型检查期导入：运行时由上方 importorskip 守卫优雅跳过
    from playwright.sync_api import Page

# build_app 装配时会读取这些环境变量预填默认值，E2E 需要确定性的初始表单
_PREFILL_ENV_VARS = [
    "FLASHGAZE_API_KEY",
    "FLASHGAZE_API_BASE",
    "FLASHGAZE_MODEL",
    "FLASHGAZE_VLM_PROVIDER",
    "FLASHGAZE_SCENE",
    "FLASHGAZE_WORKERS",
]

# 评分目标：3 张有效图 + 1 张损坏图（总分 4、入选 3、画廊 3）
_E2E_PHOTOS = ("sharp.jpg", "blurry.jpg", "dark.jpg", "corrupted.jpg")


def _free_port() -> int:
    """让 OS 分配一个空闲端口。

    gradio 的 server_port=0 不可用（其内部会把健康检查 URL 拼成 :0 导致连接被拒）。
    """
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        # getsockname() 的联合地址类型经索引后退化为 Any，int() 收敛回 int
        return int(s.getsockname()[1])


@pytest.fixture(scope="session")
def e2e_photo_dir(fixtures_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """E2E 评分目标目录（session 级，避免每个用例重复评分准备）。"""
    target = tmp_path_factory.mktemp("e2e_photos")
    for name in _E2E_PHOTOS:
        shutil.copy(fixtures_dir / name, target / name)
    return target


@pytest.fixture(scope="session")
def webui_url(e2e_photo_dir: Path) -> Iterator[str]:
    """启动 WebUI 并返回本地 URL；测试结束后关闭服务释放端口。"""
    mp = pytest.MonkeyPatch()
    for var in _PREFILL_ENV_VARS:
        mp.delenv(var, raising=False)
    demo = build_app()
    demo.launch(
        server_name="127.0.0.1",
        server_port=_free_port(),
        prevent_thread_lock=True,
        quiet=True,
        show_error=True,
    )
    # launch() 同步返回后 local_url 已就位。gradio 对 local_url 只做了
    # `= None` 初始化而无类型注解（mypy 推断为 None），用 `or ""` 归一成 str；
    # 服务未起来时 url 为空串，由下方断言立即失败
    url = demo.local_url or ""
    assert url
    yield url
    demo.close()
    mp.undo()


@pytest.fixture()
def scored_page(page: Page, webui_url: str, e2e_photo_dir: Path) -> Page:
    """导航到 WebUI 并完成一次离线评分（状态出现 ✅），供筛选/导出/下载用例复用。"""
    from tests.e2e.test_webui_e2e import run_offline_scoring

    page.goto(webui_url)
    run_offline_scoring(page, str(e2e_photo_dir))
    return page
