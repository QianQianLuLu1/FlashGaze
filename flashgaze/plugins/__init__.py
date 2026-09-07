"""插件自动发现。标准库 importlib + pkgutil + ast，无第三方依赖。

安全模型（C-03）：自定义/用户插件目录下的 .py 必须先显式声明
``__flashgaze_plugin__ = True`` 才会被加载。未声明的随机脚本被视为不可信，
在**不执行其顶层代码**的前提下直接跳过（用 ast 静态检查声明），避免任意代码执行面。

> 注意：放入插件目录（自定义 ``plugin_dir`` 或 ``~/.flashgaze/plugins``）的
> ``.py`` 文件即被视为可信代码——请确保目录本身不被未授权写入。内置插件位于
> 包内（``flashgaze.plugins.builtin``），由 import_module 加载，不走此标记校验。
>
> 安全（#11-1）：用户目录 ``~/.flashgaze/plugins`` **默认不再自动扫描**（防 RCE：
> 目录一旦可写即等同执行任意代码）。仅当显式设置环境变量 ``FLASHGAZE_USER_PLUGINS=1``
> 或显式传入 ``--plugin-dir`` 时才加载用户目录插件。内置插件与显式 ``plugin_dir`` 不受影响。
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import logging
import os
import pkgutil
from pathlib import Path
from types import ModuleType

from flashgaze.plugins.base import ScoringPlugin
from flashgaze.utils.logging import get_logger

_USER_PLUGIN_DIR = Path.home() / ".flashgaze" / "plugins"
_BUILTIN_PKG = "flashgaze.plugins.builtin"


def _user_plugins_enabled() -> bool:
    """用户插件目录是否启用自动加载（#11-1 防 RCE 默认关闭）。

    仅当环境变量 FLASHGAZE_USER_PLUGINS 为真值（1/true/yes/on）时返回 True。
    显式传入的 --plugin-dir 不依赖此开关（属用户明确意图）。
    """
    raw = os.environ.get("FLASHGAZE_USER_PLUGINS", "")
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _is_truthy_marker(value: ast.expr) -> bool:
    """静态判断 __flashgaze_plugin__ 赋值右值是否为真值常量（不执行代码）。

    # FIX(#11-2): 仅接受 ast.literal_eval 可求值的字面量常量，非字面量表达式
    一律视为无效，避免 ``__flashgaze_plugin__ = <任意表达式>`` 被当作声明。
    """
    try:
        return bool(ast.literal_eval(value))
    except (ValueError, SyntaxError):
        return False


def discover_plugins(plugin_dir: str | None = None) -> list[ScoringPlugin]:
    """扫描并返回所有 ScoringPlugin 实例。

    搜索顺序：内置 builtin/ → 自定义 plugin_dir（若存在）→ 用户目录
    ~/.flashgaze/plugins/（若存在）。
    加载失败的插件只记 warning，不阻塞、不抛异常。
    """
    logger = get_logger()
    plugins: list[ScoringPlugin] = []
    seen_names: set[str] = set()

    # 1) 内置插件（包内模块，import_module 导入，无需标记声明）
    builtin_dir = Path(__file__).parent / "builtin"
    if builtin_dir.is_dir():
        for _finder, mod_name, _ispkg in pkgutil.iter_modules([str(builtin_dir)]):
            full = f"{_BUILTIN_PKG}.{mod_name}"
            try:
                mod = importlib.import_module(full)
            except Exception as e:  # noqa: BLE001 — 内置插件加载失败仅告警跳过（插件代码可抛任意异常）
                logger.warning("内置插件 %s 加载失败，已跳过: %s", mod_name, e)
                continue
            plugins += _collect(mod, mod_name, logger, seen_names)

    # 2) 自定义目录（文件级加载，若存在）
    if plugin_dir:
        plugins += _load_dir(Path(plugin_dir), "flashgaze_extra_plugin", logger, seen_names)

    # 3) 用户目录（非包，文件级加载）。# FIX(#11-1): 默认不再自动扫描用户插件目录，
    # 避免目录可写时的任意代码执行；仅显式 --plugin-dir 或 FLASHGAZE_USER_PLUGINS=1 时加载。
    if _USER_PLUGIN_DIR.is_dir():
        if _user_plugins_enabled():
            plugins += _load_dir(_USER_PLUGIN_DIR, "flashgaze_user_plugin", logger, seen_names)
        else:
            logger.debug(
                "用户插件目录 %s 存在但未启用自动加载（默认关闭以防 RCE）。"
                "如需加载，请设置环境变量 FLASHGAZE_USER_PLUGINS=1 或显式传入 --plugin-dir。",
                _USER_PLUGIN_DIR,
            )

    return plugins


def _declares_plugin_marker(py: Path, logger: logging.Logger) -> bool:
    """静态检查模块是否声明 ``__flashgaze_plugin__`` 标记（不执行代码）。

    C-03：未声明的 .py 视为随机脚本，拒绝加载并记 warning，
    避免落入"任意 .py 即插件"的任意代码执行面。
    """
    try:
        # FIX(#11-3): UnicodeDecodeError 是 ValueError 子类，须一并捕获，
        # 否则非 UTF-8 插件文件会让整个发现流程崩溃。
        tree = ast.parse(py.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError) as e:
        logger.warning("插件 %s 读取/解析失败，已跳过: %s", py.name, e)
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                # FIX(#11-2): 仅当取值为真（True/1/"x" 等）才视为有效声明；
                # __flashgaze_plugin__ = False/0/"" 等非真值不通过。
                if (
                    isinstance(target, ast.Name)
                    and target.id == "__flashgaze_plugin__"
                    and _is_truthy_marker(node.value)
                ):
                    return True
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "__flashgaze_plugin__"
            and node.value is not None
            and _is_truthy_marker(node.value)
        ):
            return True
    logger.warning(
        "插件 %s 未声明有效的 __flashgaze_plugin__=True，已跳过（自定义插件需显式声明）",
        py.name,
    )
    return False


def _load_dir(
    directory: Path,
    prefix: str,
    logger: logging.Logger,
    seen_names: set[str],
) -> list[ScoringPlugin]:
    """扫描目录下的 *.py（排除 __init__.py），文件级加载并收集插件实例。

    C-03：先经 ``_declares_plugin_marker`` 静态校验，未声明标记者不执行其代码即跳过。
    """
    found: list[ScoringPlugin] = []
    for py in sorted(directory.glob("*.py")):
        if py.name == "__init__.py":
            continue
        try:
            # FIX(#11-3): 单个文件校验异常不应中断整目录扫描，仅跳过该坏文件。
            if not _declares_plugin_marker(py, logger):
                continue
        except Exception as e:  # noqa: BLE001 — 单插件校验失败仅跳过，不中断目录扫描
            logger.warning("插件 %s 校验失败，已跳过: %s", py.name, e)
            continue
        mod_name = f"{prefix}_{py.stem}"
        try:
            spec = importlib.util.spec_from_file_location(mod_name, py)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception as e:  # noqa: BLE001 — 不可信插件代码任意异常仅告警跳过（安全模型 C-03）
            logger.warning("插件 %s 加载失败，已跳过: %s", py.name, e)
            continue
        found += _collect(mod, py.name, logger, seen_names)
    return found


def _collect(
    mod: ModuleType, label: str, logger: logging.Logger, seen_names: set[str]
) -> list[ScoringPlugin]:
    """从模块里挑出 ScoringPlugin 子类并实例化（跳过基类本身与重名）。"""
    found: list[ScoringPlugin] = []
    for attr in vars(mod).values():
        if isinstance(attr, type) and issubclass(attr, ScoringPlugin) and attr is not ScoringPlugin:
            try:
                inst = attr()
            except Exception as e:  # noqa: BLE001 — 插件实例化失败仅告警跳过
                logger.warning("插件 %s 实例化失败，已跳过: %s", label, e)
                continue
            if inst.name in seen_names:
                logger.warning("插件名重复，已跳过: %s", inst.name)
                continue
            seen_names.add(inst.name)
            found.append(inst)
    return found
