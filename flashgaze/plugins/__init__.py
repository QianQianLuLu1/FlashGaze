"""插件自动发现。标准库 importlib + pkgutil，无第三方依赖。"""

from __future__ import annotations

import importlib
import importlib.util
import pkgutil
from pathlib import Path
from typing import List, Optional

from flashgaze.plugins.base import PluginScore, ScoringPlugin
from flashgaze.utils.logging import get_logger

_USER_PLUGIN_DIR = Path.home() / ".flashgaze" / "plugins"
_BUILTIN_PKG = "flashgaze.plugins.builtin"


def discover_plugins(plugin_dir: Optional[str] = None) -> List[ScoringPlugin]:
    """扫描并返回所有 ScoringPlugin 实例。

    搜索顺序：内置 builtin/ → 自定义 plugin_dir（若存在）→ 用户目录
    ~/.flashgaze/plugins/（若存在）。
    加载失败的插件只记 warning，不阻塞、不抛异常。
    """
    logger = get_logger()
    plugins: List[ScoringPlugin] = []
    seen_names: set[str] = set()

    # 1) 内置插件（包内模块，import_module 导入）
    builtin_dir = Path(__file__).parent / "builtin"
    if builtin_dir.is_dir():
        for _finder, mod_name, _ispkg in pkgutil.iter_modules([str(builtin_dir)]):
            full = f"{_BUILTIN_PKG}.{mod_name}"
            try:
                mod = importlib.import_module(full)
            except Exception as e:
                logger.warning("内置插件 %s 加载失败，已跳过: %s", mod_name, e)
                continue
            plugins += _collect(mod, mod_name, logger, seen_names)

    # 2) 自定义目录（文件级加载，若存在）
    if plugin_dir:
        plugins += _load_dir(Path(plugin_dir), "flashgaze_extra_plugin", logger, seen_names)

    # 3) 用户目录（非包，文件级加载，若存在）
    if _USER_PLUGIN_DIR.is_dir():
        plugins += _load_dir(_USER_PLUGIN_DIR, "flashgaze_user_plugin", logger, seen_names)

    return plugins


def _load_dir(
    directory: Path,
    prefix: str,
    logger,
    seen_names: set[str],
) -> List[ScoringPlugin]:
    """扫描目录下的 *.py（排除 __init__.py），文件级加载并收集插件实例。"""
    found: List[ScoringPlugin] = []
    for py in sorted(directory.glob("*.py")):
        if py.name == "__init__.py":
            continue
        mod_name = f"{prefix}_{py.stem}"
        try:
            spec = importlib.util.spec_from_file_location(mod_name, py)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception as e:
            logger.warning("插件 %s 加载失败，已跳过: %s", py.name, e)
            continue
        found += _collect(mod, py.name, logger, seen_names)
    return found


def _collect(mod, label: str, logger, seen_names: set[str]) -> List[ScoringPlugin]:
    """从模块里挑出 ScoringPlugin 子类并实例化（跳过基类本身与重名）。"""
    found: List[ScoringPlugin] = []
    for attr in vars(mod).values():
        if (
            isinstance(attr, type)
            and issubclass(attr, ScoringPlugin)
            and attr is not ScoringPlugin
        ):
            try:
                inst = attr()
            except Exception as e:
                logger.warning("插件 %s 实例化失败，已跳过: %s", label, e)
                continue
            if inst.name in seen_names:
                logger.warning("插件名重复，已跳过: %s", inst.name)
                continue
            seen_names.add(inst.name)
            found.append(inst)
    return found
