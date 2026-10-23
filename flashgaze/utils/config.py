"""配置加载工具。

优先级：CLI 参数 > 环境变量 > 配置文件 > 默认值（defaults.py）。
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import MISSING, fields, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, get_type_hints

from flashgaze.defaults import (
    CLEANUP_GUARD_MIN_SAMPLE,
    DEFAULT_API_BASE,
    DEFAULT_API_BASE_ALLOWLIST,
    DEFAULT_MAX_RETRIES,
    DEFAULT_MODEL,
    DEFAULT_SCENE,
    DEFAULT_TIMEOUT_SEC,
    DEFAULT_TOP,
    DEFAULT_VLM_BREAKER_THRESHOLD,
    DEFAULT_VLM_MAX_ADJUSTMENT,
    DEFAULT_VLM_PROVIDER,
    DEFAULT_VLM_SEED,
    DEFAULT_VLM_TEMPERATURE,
    DEFAULT_WEIGHTS,
    DEFAULT_WORKERS,
    ENV_ALLOW_PRIVATE_TARGETS,
    ENV_ALLOW_UNTRUSTED_API_BASE,
    ENV_API_BASE,
    ENV_API_BASE_ALLOWLIST,
    ENV_API_KEY,
    ENV_CONFIG_FILE,
    ENV_DEDUP_THRESHOLD,
    ENV_MAX_RETRIES,
    ENV_MODEL,
    ENV_SCENE,
    ENV_TIMEOUT,
    ENV_VLM_BREAKER_THRESHOLD,
    ENV_VLM_MAX_ADJUSTMENT,
    ENV_VLM_PROVIDER,
    ENV_VLM_SEED,
    ENV_VLM_TEMPERATURE,
    ENV_WEIGHTS,
    ENV_WORKERS,
    SUPPORTED_SCENES,
    SUPPORTED_VLM_PROVIDERS,
)
from flashgaze.models.schemas import Config
from flashgaze.utils.logging import get_logger
from flashgaze.utils.net_guard import check_api_base

# 合法权重 key 集合（sharpness/exposure 必填，composition/noise/color 可选）
_WEIGHT_KEYS_REQUIRED = ("sharpness", "exposure")
_WEIGHT_KEYS_OPTIONAL = ("composition", "noise", "color")
_WEIGHT_KEYS_ALL = _WEIGHT_KEYS_REQUIRED + _WEIGHT_KEYS_OPTIONAL


def _parse_weights(raw: Any) -> dict[str, float] | None:
    """解析权重 dict，支持 sharpness/exposure/composition/noise/color 五个 key。

    - sharpness/exposure 必填，composition/noise/color 可选
    - 自动归一化到总和 1.0
    - 非法输入（非 dict、缺必填 key、值非数值、总和<=0）返回 None
    """
    if not isinstance(raw, dict):
        return None
    for k in _WEIGHT_KEYS_REQUIRED:
        if k not in raw:
            return None
    try:
        weights: dict[str, float] = {}
        for k in _WEIGHT_KEYS_REQUIRED:
            weights[k] = float(raw[k])
        for k in _WEIGHT_KEYS_OPTIONAL:
            if k in raw:
                weights[k] = float(raw[k])
    except (ValueError, TypeError, OverflowError):
        # FIX(#3-6): 巨型整数（如 10**400）会让 float() 抛 OverflowError，按非法输入处理
        return None
    # FIX(#3-1): 拒绝非有限值（NaN/inf）与负值权重，避免污染归一化或扭曲评分。
    for v in weights.values():
        if not math.isfinite(v) or v < 0:
            return None
    # fsum 而非 sum：CPython 3.12 起内置 sum() 改用 Neumaier 补偿求和，3.10/3.11 仍是朴素
    # 左折叠；两次归一化叠加后同一份 --weights 在不同解释器上末位不相等（0.4 → 0.3999…97）。
    # fsum 逐版本精确一致。_adjust_custom_weights 的兜底归一化必须同步改，只改一处更糟。
    total = math.fsum(weights.values())
    if total <= 0:
        return None
    return {k: v / total for k, v in weights.items()}


def _validate_weights(config: Config) -> None:
    """最终权重合法性兜底：权重总和必须为正数。

    正常装配路径（_parse_weights 已拒绝 total<=0、_adjust_custom_weights 归一化到
    1.0）下恒为 sum=1.0，不会触发；仅作回归护栏，拦截直接构造 Config 传入零和权重等
    绕过 build_config 的退化场景，让错误在装配期响亮暴露（而非静默归零全部评分）。

    FIX(#C-15): 零权重会让全部评分被静默归零、失去意义，故一律响亮抛错。
    """
    if sum(config.weights.values()) <= 0:
        raise ValueError(
            "权重总和必须为正数（当前为 0），sharpness/exposure 不可同时为 0，"
            "请检查 --weights / FLASHGAZE_WEIGHTS 配置"
        )


def _coerce_numeric(base: dict[str, Any]) -> None:
    """统一强转数值字段并钳制下限，避免配置文件/override 传入 str 或 float
    触发 TypeError（C-05）。失败记 warning 并回退默认值。原地修改 base。

    覆盖：workers（int，[1, min(cpu,16)]）、timeout_sec（int，>=1）、
    max_retries（int，>=0）、dedup_threshold（可选 int，>=0，非法则移除让默认兜底）。

    FIX(#3-6): 捕获元组补 OverflowError——JSON 允许 1e999（解析为 inf），而
    int(inf) 抛 OverflowError，不在 (TypeError, ValueError) 内，曾击穿本函数
    「不抛异常」的契约。
    """
    logger = get_logger()

    # workers：int，下限 1，上限 min(cpu_count, 16)
    cpu_count = os.cpu_count() or 4
    max_workers = min(cpu_count, 16)
    raw = base.get("workers", DEFAULT_WORKERS)
    try:
        workers = int(raw)
    except (TypeError, ValueError, OverflowError):
        logger.warning("workers=%r 非法，回退默认 %d", raw, DEFAULT_WORKERS)
        workers = DEFAULT_WORKERS
    if workers < 1:
        logger.warning("workers=%d 小于 1，已自动钳制为 1", workers)
        workers = 1
    elif workers > max_workers:
        logger.warning(
            "workers=%d 超过上限 %d（cpu_count=%d），已自动钳制为 %d",
            workers,
            max_workers,
            cpu_count,
            max_workers,
        )
        workers = max_workers
    base["workers"] = workers

    # timeout_sec：int，下限 1
    raw = base.get("timeout_sec", DEFAULT_TIMEOUT_SEC)
    try:
        timeout = int(raw)
    except (TypeError, ValueError, OverflowError):
        logger.warning("timeout_sec=%r 非法，回退默认 %d", raw, DEFAULT_TIMEOUT_SEC)
        timeout = DEFAULT_TIMEOUT_SEC
    if timeout < 1:
        logger.warning("timeout_sec=%d 小于 1，已自动钳制为 1", timeout)
        timeout = 1
    base["timeout_sec"] = timeout

    # max_retries：int，下限 0
    raw = base.get("max_retries", DEFAULT_MAX_RETRIES)
    try:
        retries = int(raw)
    except (TypeError, ValueError, OverflowError):
        logger.warning("max_retries=%r 非法，回退默认 %d", raw, DEFAULT_MAX_RETRIES)
        retries = DEFAULT_MAX_RETRIES
    if retries < 0:
        logger.warning("max_retries=%d 小于 0，已自动钳制为 0", retries)
        retries = 0
    base["max_retries"] = retries

    # dedup_threshold：可选 int，>=0；非法则移除让默认兜底
    raw = base.get("dedup_threshold")
    if raw is not None:
        try:
            thr = int(raw)
        except (TypeError, ValueError, OverflowError):
            logger.warning("dedup_threshold=%r 非法，已忽略", raw)
            base.pop("dedup_threshold", None)
        else:
            if thr < 0:
                logger.warning("dedup_threshold=%d 小于 0，已忽略", thr)
                base.pop("dedup_threshold", None)
            else:
                base["dedup_threshold"] = thr


# ── 布尔字段统一强转（M-7）────────────────────────────────
# 非空字符串在 Python 中一律为真：配置文件 / env / override 写 "false"、"0"、
# "no"、"off" 会被静默当成 True，把「显式关闭」变成「开启」。集中在此强转。
_BOOL_TRUE_LITERALS = frozenset({"true", "1", "yes", "on"})
_BOOL_FALSE_LITERALS = frozenset({"false", "0", "no", "off"})


def _bool_field_defaults() -> dict[str, bool]:
    """反射生成「Config 布尔字段名 → 字段默认值」映射。

    用 `get_type_hints` 而非 `field.type`：schemas.py 开启了 PEP 563
    （`from __future__ import annotations`），`field.type` 是字符串，
    无法用于 `is bool` 判定。仅收录有字面默认值的字段（无默认值的
    directory 等被 MISSING 过滤）。
    """
    hints = get_type_hints(Config)
    return {
        f.name: bool(f.default)
        for f in fields(Config)
        if f.default is not MISSING and hints.get(f.name) is bool
    }


_BOOL_FIELDS: dict[str, bool] = _bool_field_defaults()


def _coerce_bool(base: dict[str, Any]) -> None:
    """统一强转 Config 布尔字段并回退非法值（M-7）。原地修改 base，不抛异常。

    覆盖 `_BOOL_FIELDS`（由 Config 反射生成的全部布尔字段）。

    - bool：原样放行
    - str：去空白并小写，命中 `true/1/yes/on` → True，`false/0/no/off` → False
    - int：仅 0 / 1 合法，其余按非法处理
    - None：视为「未设置」，移除该键回落 Config 默认值，不告警
    - 其它（"maybe" / 2 / [] / {} 等）：WARNING 并回退该字段默认值

    与 `_coerce_numeric` / `_clamp_*` 同风格，是「配置装配层不抛异常」契约
    在布尔侧的延伸——让非法配置在装配期可见（告警），而非在评分期变成误行为。
    """
    logger = get_logger()
    for name, default in _BOOL_FIELDS.items():
        if name not in base:
            continue
        raw = base[name]
        if isinstance(raw, bool):
            continue
        if raw is None:
            # 显式 null 等同「未设置」：交给 Config 默认值，不制造告警噪音
            base.pop(name)
            continue
        val: bool | None = None
        if isinstance(raw, str):
            token = raw.strip().lower()
            if token in _BOOL_TRUE_LITERALS:
                val = True
            elif token in _BOOL_FALSE_LITERALS:
                val = False
        elif isinstance(raw, int) and raw in (0, 1):
            val = bool(raw)
        if val is None:
            logger.warning("%s=%r 非法布尔值，回退默认 %s", name, raw, default)
            val = default
        base[name] = val


def _clamp_selection_bounds(base: dict[str, Any]) -> None:
    """钳制 top / threshold 到安全范围，覆盖 env / 文件 / CLI / MCP 四条来源。

    top：非法（不可转 int）或 < 1 → WARNING 并回退 DEFAULT_TOP。刻意不钳到 1——
    top=0 会被解释成"只留 1 张、删掉其余"，比回退默认值更危险；回退 DEFAULT_TOP
    与 `hybrid_scorer._mark_selected`、`cleanup._reselect` 的既有兜底语义一致。

    threshold：越界数值钳到 [0.0, 100.0]；NaN / inf / 不可解析 → 视为"未设置"
    （置 None）回落到 top 语义。NaN 必须单独处置：`<0 / >100` 比较捕获不到它，
    而 `score >= nan` 恒为 False 会让全部图进入待删、一次调用删空整个工作空间。

    原地修改 base，不抛异常（与 _coerce_numeric / _clamp_vlm_max_adjustment 同风格）。

    FIX(#3-6): 捕获元组补 OverflowError——top 传 JSON 1e999（解析为 inf）时
    int(inf) 会抛 OverflowError；threshold 传 10**400 量级巨型整数时 float()
    同样溢出。二者均按"非法输入"走既有回退路径，维持「不抛异常」契约。
    """
    logger = get_logger()

    raw_top = base.get("top")
    try:
        top = int(raw_top)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        if raw_top is not None:
            logger.warning("top=%r 非法，回退默认 %d", raw_top, DEFAULT_TOP)
        top = DEFAULT_TOP
    if top < 1:
        logger.warning("top=%d 小于 1，回退默认 %d（禁止清空整个工作空间）", top, DEFAULT_TOP)
        top = DEFAULT_TOP
    base["top"] = top

    raw_thr = base.get("threshold")
    if raw_thr is None:
        # 未设置：保持 None，走 top 语义
        base["threshold"] = None
        return
    try:
        threshold = float(raw_thr)
    except (TypeError, ValueError, OverflowError):
        logger.warning("threshold=%r 非法，视为未设置（回落 top 语义）", raw_thr)
        base["threshold"] = None
        return
    if not math.isfinite(threshold):
        # NaN/inf 会让全部分数比较恒为 False（NaN）或恒为 True（+inf 之外），
        # 均会扭曲删除决策，统一按"未设置"处理。
        logger.warning("threshold=%r 非有限值（NaN/inf），视为未设置（回落 top 语义）", raw_thr)
        base["threshold"] = None
        return
    if threshold < 0.0 or threshold > 100.0:
        logger.warning("threshold=%s 越界，已钳制到 [0.0, 100.0]", threshold)
        threshold = max(0.0, min(100.0, threshold))
    base["threshold"] = threshold


def load_config_file(path: str | Path) -> dict[str, Any]:
    """加载 JSON 配置文件。文件不存在或格式错误返回空 dict（不抛异常）。"""
    p = Path(path)
    if not p.exists():
        # M-11 配套：文件不存在原为静默返回空 dict，与损坏路径的 #3-4 告警不对称，
        # 配置未生效难以察觉；补 warning 使 --config-file / FLASHGAZE_CONFIG_FILE
        # 两类入口一致可观测。
        get_logger().warning("配置文件 %s 不存在，已忽略", p)
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        # FIX(#3-4): 配置文件存在但损坏/不可读时原静默回退默认配置，用户难以察觉
        # 配置未生效；补 warning 与 env/CLI 路径行为一致。
        get_logger().warning("配置文件 %s 读取或解析失败，已回退默认配置: %s", p, e)
        return {}
    # 顶层非 JSON 对象（数组/字符串等）同样无法作为配置使用，按损坏处理回退默认
    if not isinstance(data, dict):
        get_logger().warning("配置文件 %s 顶层不是 JSON 对象，已回退默认配置", p)
        return {}
    return data


def merge_env() -> dict[str, Any]:
    """从环境变量读取配置。未设置的字段不包含在返回 dict 中。"""
    cfg: dict[str, Any] = {}
    logger = get_logger()
    if os.environ.get(ENV_API_KEY):
        cfg["api_key"] = os.environ[ENV_API_KEY]
    if os.environ.get(ENV_API_BASE):
        cfg["api_base"] = os.environ[ENV_API_BASE]
    if os.environ.get(ENV_MODEL):
        cfg["model"] = os.environ[ENV_MODEL]
    if os.environ.get(ENV_TIMEOUT):
        try:
            cfg["timeout_sec"] = int(os.environ[ENV_TIMEOUT])
        except ValueError:
            # FIX(#3-5): 与文件/CLI 路径一致，非法 env 值须告警而非静默丢弃。
            logger.warning(
                "环境变量 %s=%r 非法，已忽略并使用默认超时", ENV_TIMEOUT, os.environ[ENV_TIMEOUT]
            )
    if os.environ.get(ENV_WORKERS):
        try:
            cfg["workers"] = int(os.environ[ENV_WORKERS])
        except ValueError:
            logger.warning(
                "环境变量 %s=%r 非法，已忽略并使用默认并发数", ENV_WORKERS, os.environ[ENV_WORKERS]
            )
    if os.environ.get(ENV_MAX_RETRIES):
        try:
            cfg["max_retries"] = int(os.environ[ENV_MAX_RETRIES])
        except ValueError:
            logger.warning(
                "环境变量 %s=%r 非法，已忽略并使用默认重试次数",
                ENV_MAX_RETRIES,
                os.environ[ENV_MAX_RETRIES],
            )
    if os.environ.get(ENV_VLM_MAX_ADJUSTMENT):
        try:
            cfg["vlm_max_adjustment"] = float(os.environ[ENV_VLM_MAX_ADJUSTMENT])
        except ValueError:
            logger.warning(
                "环境变量 %s=%r 非法，已忽略并使用默认补偿上限",
                ENV_VLM_MAX_ADJUSTMENT,
                os.environ[ENV_VLM_MAX_ADJUSTMENT],
            )
    if os.environ.get(ENV_VLM_BREAKER_THRESHOLD):
        try:
            cfg["vlm_breaker_threshold"] = int(os.environ[ENV_VLM_BREAKER_THRESHOLD])
        except ValueError:
            logger.warning(
                "环境变量 %s=%r 非法，已忽略并使用默认熔断阈值",
                ENV_VLM_BREAKER_THRESHOLD,
                os.environ[ENV_VLM_BREAKER_THRESHOLD],
            )
    # ── VLM 采样参数（可复现性）────────────────────────
    if os.environ.get(ENV_VLM_TEMPERATURE):
        try:
            cfg["vlm_temperature"] = float(os.environ[ENV_VLM_TEMPERATURE])
        except ValueError:
            logger.warning(
                "环境变量 %s=%r 非法，已忽略并使用默认 VLM 采样温度",
                ENV_VLM_TEMPERATURE,
                os.environ[ENV_VLM_TEMPERATURE],
            )
    if os.environ.get(ENV_VLM_SEED):
        try:
            cfg["vlm_seed"] = int(os.environ[ENV_VLM_SEED])
        except ValueError:
            logger.warning(
                "环境变量 %s=%r 非法，已忽略并使用默认 VLM seed",
                ENV_VLM_SEED,
                os.environ[ENV_VLM_SEED],
            )
    if os.environ.get(ENV_WEIGHTS):
        try:
            raw = json.loads(os.environ[ENV_WEIGHTS])
            parsed = _parse_weights(raw)
            if parsed is not None:
                cfg["weights"] = parsed
            else:
                # FIX(#3-2): 与文件配置路径一致，非法权重须告警而非静默丢弃。
                logger.warning(
                    "环境变量 %s 权重非法（缺必填 key 或含负值/NaN），已忽略并使用默认权重",
                    ENV_WEIGHTS,
                )
        except (json.JSONDecodeError, ValueError, TypeError):
            # FIX(#3-2): JSON 解析失败也须告警，避免调用方无感知。
            logger.warning("环境变量 %s 解析失败，已忽略并使用默认权重", ENV_WEIGHTS)
    if os.environ.get(ENV_DEDUP_THRESHOLD):
        try:
            cfg["dedup_threshold"] = int(os.environ[ENV_DEDUP_THRESHOLD])
        except ValueError:
            # FIX(#3-5): 非法 env 值须告警而非静默丢弃。
            logger.warning(
                "环境变量 %s=%r 非法，已忽略并使用默认去重阈值",
                ENV_DEDUP_THRESHOLD,
                os.environ[ENV_DEDUP_THRESHOLD],
            )
    # ── VLM 扩展新增环境变量（M3）──────────────────────
    if os.environ.get(ENV_VLM_PROVIDER):
        cfg["vlm_provider"] = os.environ[ENV_VLM_PROVIDER]
    if os.environ.get(ENV_SCENE):
        cfg["scene"] = os.environ[ENV_SCENE]
    # ── SSRF 逃生通道（本修复）──────────────────────────
    # 仅当显式为真值时放行，其余（未设置/"false"/"0"）保持默认 False，避免误放开云 API。
    raw_allow = os.environ.get(ENV_ALLOW_PRIVATE_TARGETS)
    if raw_allow is not None and raw_allow.strip().lower() in _BOOL_TRUE_LITERALS:
        cfg["allow_private_targets"] = True
    # ── api_base 端点白名单（H-6）──────────────────────
    # 自定义白名单：逗号分隔主机后缀；非法/空条目由 _normalize_allowlist 过滤。
    if os.environ.get(ENV_API_BASE_ALLOWLIST):
        cfg["api_base_allowlist"] = _normalize_allowlist(os.environ[ENV_API_BASE_ALLOWLIST])
    # 端点确认逃生舱：显式真值表示用户已确认当前端点可信，非白名单不再告警。
    raw_untrusted = os.environ.get(ENV_ALLOW_UNTRUSTED_API_BASE)
    if raw_untrusted is not None and raw_untrusted.strip().lower() in _BOOL_TRUE_LITERALS:
        cfg["allow_untrusted_api_base"] = True
    return cfg


def _normalize_allowlist(raw: Any) -> tuple[str, ...]:
    """把白名单来源归一化为非空字符串元组（H-6）。

    接受 str（逗号分隔）与 list/tuple/set（配置文件 JSON 数组）；过滤空条目与
    非字符串元素——空条目若保留会命中任意主机、令白名单整体失效。

    归一化结果为空（未提供 / 全是空条目 / 类型非法）时**回落内置默认**
    `DEFAULT_API_BASE_ALLOWLIST`，绝不产出空白名单：空白名单等于「一切端点皆非
    白名单」，告警会退化成噪音并丧失白名单语义。不抛异常（与 _clamp_* 同契约）。
    """
    if isinstance(raw, str):
        candidates: list[Any] = raw.split(",")
    elif isinstance(raw, (list, tuple, set, frozenset)):
        candidates = list(raw)
    else:
        candidates = []
    items = [item.strip() for item in candidates if isinstance(item, str) and item.strip()]
    if not items:
        return DEFAULT_API_BASE_ALLOWLIST
    return tuple(items)


def _warn_untrusted_api_base(base: dict[str, Any]) -> None:
    """非白名单 api_base 告警（H-6 唯一卡口）。只告警、不改写、不抛异常。

    env / 配置文件 / CLI --api-base / WebUI 文本框四条来源在 build_config 汇聚后
    统一在此判定：任何来源把端点指向非白名单主机，都会在 stderr 留下一条 WARNING，
    使「clone 第三方仓库携带配置即劫持端点」这类隐蔽攻击可见。

    刻意**不阻断**（用户裁定零破坏性）：不改写 api_base、不改退出码、不抛异常，
    自托管用户在补齐白名单或逃生变量前仍可继续运行。
    与 _clamp_* 同契约：原地读 base，不改变装配结果。
    """
    logger = get_logger()
    allowlist = base.get("api_base_allowlist") or DEFAULT_API_BASE_ALLOWLIST
    verdict = check_api_base(
        str(base.get("api_base") or ""),
        provider=str(base.get("vlm_provider") or DEFAULT_VLM_PROVIDER),
        allow_private_targets=bool(base.get("allow_private_targets")),
        allowlist=allowlist,
        allow_untrusted=bool(base.get("allow_untrusted_api_base")),
    )
    if verdict.trusted:
        return
    logger.warning(
        "VLM 端点 %s 不可信（%s）：API Key 与图片内容将发往该主机。"
        "确认可信请设置 %s=1；长期自托管请把主机加入 %s（逗号分隔主机后缀）",
        verdict.host or "(无法解析主机名)",
        verdict.reason,
        ENV_ALLOW_UNTRUSTED_API_BASE,
        ENV_API_BASE_ALLOWLIST,
    )


def default_config_dict() -> dict[str, Any]:
    """返回 defaults.py 中的默认配置 dict。"""
    return {
        "api_base": DEFAULT_API_BASE,
        "model": DEFAULT_MODEL,
        "timeout_sec": DEFAULT_TIMEOUT_SEC,
        "max_retries": DEFAULT_MAX_RETRIES,
        "workers": DEFAULT_WORKERS,
        "weights": DEFAULT_WEIGHTS,
        "vlm_max_adjustment": DEFAULT_VLM_MAX_ADJUSTMENT,
        "vlm_breaker_threshold": DEFAULT_VLM_BREAKER_THRESHOLD,
        "vlm_temperature": DEFAULT_VLM_TEMPERATURE,
        "vlm_seed": DEFAULT_VLM_SEED,
        "vlm_provider": DEFAULT_VLM_PROVIDER,
        "scene": DEFAULT_SCENE,
        "allow_private_targets": False,
    }


# Config dataclass 合法字段名集合（构造时过滤非法 key，避免 TypeError）
_CONFIG_FIELD_NAMES: set[str] = {f.name for f in fields(Config)}


def _adjust_weights_for_enabled_features(config: Config) -> Config:
    """启用新维度时对齐权重表，保证"启用即生效"。

    两分支——默认权重（用户未自定义）走原有逻辑，零漂移；自定义权重走
    维度对齐（Rule A 借权重注入缺的已启用维度 + Rule B 忽略未启用维度的权重）。
    不走此函数的兜底归一化，最终保证 config.weights 之和恒为 1.0。
    """
    if config.weights is DEFAULT_WEIGHTS:
        return _adjust_default_weights(config)
    return _adjust_custom_weights(config)


def _adjust_default_weights(config: Config) -> Config:
    """默认权重分支（用户未自定义）：原有注入逻辑，行为零变化。"""
    has_composition = config.enable_composition
    has_noise = config.enable_noise
    has_color = config.enable_color

    # 未启用任何新维度，保持默认 sharpness 0.5 / exposure 0.5
    if not (has_composition or has_noise or has_color):
        return config

    # 全维度启用：使用预设的非对称权重
    if has_composition and has_noise and has_color:
        weights = {
            "sharpness": 0.35,
            "exposure": 0.25,
            "composition": 0.20,
            "noise": 0.10,
            "color": 0.10,
        }
        return replace(config, weights=MappingProxyType(weights))

    # 部分启用：从基础 0.5/0.5 逐步借权重
    # （不带注解：weights 已在上方全启用分支绑定，注解重声明会触发 no-redef）
    weights = {"sharpness": 0.5, "exposure": 0.5}
    if has_composition:
        weights["composition"] = 0.2
        weights["sharpness"] = 0.4
        weights["exposure"] = 0.4
    if has_noise:
        weights["noise"] = 0.1
        weights["sharpness"] = round(weights["sharpness"] - 0.05, 2)
        weights["exposure"] = round(weights["exposure"] - 0.05, 2)
    if has_color:
        weights["color"] = 0.1
        weights["sharpness"] = round(weights["sharpness"] - 0.05, 2)
        weights["exposure"] = round(weights["exposure"] - 0.05, 2)
    return replace(config, weights=MappingProxyType(weights))


# 已启用但自定义权重缺 key 时，从 sharpness/exposure 借出的默认权重
_BORROW_TABLE = {"composition": 0.2, "noise": 0.1, "color": 0.1}


def _adjust_custom_weights(config: Config) -> Config:
    """自定义权重分支（Rule A + Rule B）：维度对齐 + 借权重注入 + 归一化。

    Rule B：未启用维度却给了权重 → 忽略该 key 并记 WARNING。
    Rule A：已启用维度缺 key → 从 sharpness/exposure 按原比例借出默认权重注入；
            若 headroom 不足（极端退化）则全表归一化借出，绝不产生负权重。
    结束时兜底归一化到 sum=1.0，吸收被忽略维度的权重并消除浮点误差。
    """
    logger = get_logger()
    W = dict(config.weights)  # 可变副本，避免污染入参

    enabled = {
        "composition": config.enable_composition,
        "noise": config.enable_noise,
        "color": config.enable_color,
    }

    # Rule B：未启用维度若被给了权重，忽略并告警
    for dim, is_on in enabled.items():
        if not is_on and dim in W:
            logger.warning(
                "维度 %s 由 --weights 指定了权重，但未启用（缺少 --enable-%s），已忽略该权重",
                dim,
                dim,
            )
            W.pop(dim)

    # Rule A：已启用维度缺 key，从 sharpness/exposure 借权重注入
    missing = [dim for dim in ("composition", "noise", "color") if enabled[dim] and dim not in W]
    if missing:
        borrowed = sum(_BORROW_TABLE[dim] for dim in missing)
        headroom = W.get("sharpness", 0.0) + W.get("exposure", 0.0)
        if headroom >= borrowed:
            # 按原比例从 sharpness/exposure 扣减，保持两者相对权重不变
            keep = (headroom - borrowed) / headroom
            W["sharpness"] = W.get("sharpness", 0.0) * keep
            W["exposure"] = W.get("exposure", 0.0) * keep
        else:
            # 退化：headroom 不足，直接加入借出额后全表归一化，绝不产生负权重
            logger.warning("自定义权重 headroom 不足，已按比例全表归一化借出维度权重")
        for dim in missing:
            W[dim] = _BORROW_TABLE[dim]

    # 兜底归一化：消除浮点误差并吸收被忽略维度的权重（fsum 恒为 1.0，跨版本理由见 _parse_weights）
    total = math.fsum(W.values())
    if total <= 0:
        # 不应发生（sharpness/exposure 必填且合计 > 0），极端兜底回默认分支
        # 文案与 _validate_weights 的响亮失败保持一致，便于用户按同一提示排查
        logger.warning(
            "自定义权重归一化后总和为 0（sharpness/exposure 不可同时为 0），"
            "回退默认权重；请检查 --weights / FLASHGAZE_WEIGHTS 配置"
        )
        return _adjust_default_weights(config)
    W = {k: v / total for k, v in W.items()}
    return replace(config, weights=MappingProxyType(W))


def _clamp_vlm_max_adjustment(base: dict[str, Any]) -> None:
    """将 vlm_max_adjustment 强转为 float 并钳制到 [0.0, 100.0]。

    # FIX(#3-3): 负值或极大值（如 -100 / 1e9）会令合并公式补偿分越界。
    覆盖 env/文件/CLI 全部来源，非法/缺失时回退默认值。
    """
    logger = get_logger()
    raw = base.get("vlm_max_adjustment", DEFAULT_VLM_MAX_ADJUSTMENT)
    try:
        val = float(raw)
    except (TypeError, ValueError, OverflowError):
        # FIX(#3-6): 巨型整数会让 float() 抛 OverflowError，与非法值同等回退默认
        logger.warning("vlm_max_adjustment=%r 非法，回退默认 %s", raw, DEFAULT_VLM_MAX_ADJUSTMENT)
        val = DEFAULT_VLM_MAX_ADJUSTMENT
    if not math.isfinite(val):
        logger.warning(
            "vlm_max_adjustment=%r 非有限值，回退默认 %s", raw, DEFAULT_VLM_MAX_ADJUSTMENT
        )
        val = DEFAULT_VLM_MAX_ADJUSTMENT
    if val < 0.0 or val > 100.0:
        logger.warning("vlm_max_adjustment=%s 越界，已钳制到 [0.0, 100.0]", val)
        val = max(0.0, min(100.0, val))
    base["vlm_max_adjustment"] = val


def _clamp_vlm_breaker_threshold(base: dict[str, Any]) -> None:
    """将 vlm_breaker_threshold 强转为 int 并钳制到 >= 0。

    0 是合法语义（关闭熔断，等价旧行为），负值属配置错误，钳制到 0 并告警。
    覆盖 env/文件/CLI 全部来源，非法/缺失时回退默认值。
    """
    logger = get_logger()
    raw = base.get("vlm_breaker_threshold", DEFAULT_VLM_BREAKER_THRESHOLD)
    try:
        val = int(raw)
    except (TypeError, ValueError, OverflowError):
        logger.warning(
            "vlm_breaker_threshold=%r 非法，回退默认 %s", raw, DEFAULT_VLM_BREAKER_THRESHOLD
        )
        val = DEFAULT_VLM_BREAKER_THRESHOLD
    if val < 0:
        logger.warning("vlm_breaker_threshold=%s 为负，已钳制到 0（关闭熔断）", val)
        val = 0
    base["vlm_breaker_threshold"] = val


def _clamp_vlm_sampling(base: dict[str, Any]) -> None:
    """VLM 采样参数钳制（可复现性）：temperature ∈ [0, 2]、seed 为非负整数。

    None 保留原值——配置文件 `null` 语义为「不注入该参数」（旧行为逃生舱），
    不能被默认值吞掉。bool 是 int 子类，先拒绝（True 不得当 1/1.0 使用）。
    覆盖 env/文件/overrides 全部来源，非法时回退默认值，不抛异常
    （与 _coerce_numeric 同契约）。provider 级二次钳制/裁剪见
    core/vlm_client.py::effective_sampling_params（anthropic 上限 1.0、
    anthropic/ollama 不注入 seed）。
    """
    logger = get_logger()
    # temperature：先强转 float（接受 "0.5" 等字符串数字，与 vlm_breaker_threshold
    # 同契约），再钳 [0.0, 2.0]；非有限值（NaN/inf）与非法类型回退默认
    raw = base.get("vlm_temperature", DEFAULT_VLM_TEMPERATURE)
    if raw is None:
        pass  # 配置文件 null：不注入语义，保留
    elif isinstance(raw, bool):
        logger.warning("vlm_temperature=%r 非法，回退默认 %s", raw, DEFAULT_VLM_TEMPERATURE)
        base["vlm_temperature"] = DEFAULT_VLM_TEMPERATURE
    else:
        try:
            val = float(raw)
        except (TypeError, ValueError, OverflowError):
            logger.warning("vlm_temperature=%r 非法，回退默认 %s", raw, DEFAULT_VLM_TEMPERATURE)
            base["vlm_temperature"] = DEFAULT_VLM_TEMPERATURE
        else:
            if not math.isfinite(val):
                logger.warning(
                    "vlm_temperature=%r 非有限，回退默认 %s", raw, DEFAULT_VLM_TEMPERATURE
                )
                base["vlm_temperature"] = DEFAULT_VLM_TEMPERATURE
            else:
                base["vlm_temperature"] = max(0.0, min(2.0, val))

    # seed：非负整数（整数值 float 接受）；负数/非整数/非法回退默认
    raw = base.get("vlm_seed", DEFAULT_VLM_SEED)
    if raw is None:
        pass  # 配置文件 null：不注入语义，保留
    elif isinstance(raw, bool):
        logger.warning("vlm_seed=%r 非法，回退默认 %s", raw, DEFAULT_VLM_SEED)
        base["vlm_seed"] = DEFAULT_VLM_SEED
    else:
        try:
            val = int(raw)
        except (TypeError, ValueError, OverflowError):
            logger.warning("vlm_seed=%r 非法，回退默认 %s", raw, DEFAULT_VLM_SEED)
            val = DEFAULT_VLM_SEED
        else:
            if isinstance(raw, float) and raw != val:
                logger.warning("vlm_seed=%r 非整数，回退默认 %s", raw, DEFAULT_VLM_SEED)
                val = DEFAULT_VLM_SEED
            elif val < 0:
                logger.warning("vlm_seed=%d 为负，回退默认 %s", val, DEFAULT_VLM_SEED)
                val = DEFAULT_VLM_SEED
        base["vlm_seed"] = val


def _clamp_cleanup_guard_min_sample(base: dict[str, Any]) -> None:
    """将 cleanup_guard_min_sample 强转为 int 并钳制到 >= 1（不可逆删除防护）。

    批量删除比例护栏的最小样本量。刻意**不提供 0 = 关闭护栏的通道**：小目录同样
    暴露在 threshold 配置错误之下，而回收站 + force 指纹确认落地后误拦代价只是
    多一步 dry_run 核对——确需放行请走 --force + --confirm-fingerprint。
    覆盖 CLI/env/文件全部来源，非法时回退默认值，不抛异常（与 _coerce_numeric 同契约）。
    """
    logger = get_logger()
    raw = base.get("cleanup_guard_min_sample", CLEANUP_GUARD_MIN_SAMPLE)
    try:
        val = int(raw)
    except (TypeError, ValueError, OverflowError):
        logger.warning(
            "cleanup_guard_min_sample=%r 非法，回退默认 %d", raw, CLEANUP_GUARD_MIN_SAMPLE
        )
        val = CLEANUP_GUARD_MIN_SAMPLE
    if val < 1:
        logger.warning("cleanup_guard_min_sample=%d 小于 1，已钳制到 1（护栏不可关闭）", val)
        val = 1
    base["cleanup_guard_min_sample"] = val


def build_config(
    directory: str,
    file_cfg: dict[str, Any] | None = None,
    **overrides: Any,
) -> Config:
    """装配 Config。优先级：overrides > env > file > default。

    CLI 与 MCP 共用此函数，消除两处重复的 env 读取 + 默认值填充逻辑。
    overrides 中值为 None 的键不参与覆盖（保留下层值）。

    file 层解析（M-11）：环境变量 FLASHGAZE_CONFIG_FILE 指向的 JSON 文件作为
    file 层兜底，使 CLI / MCP / WebUI 三入口的配置文件行为一致；显式传入的
    file_cfg（CLI --config-file）与之同层逐键合并、显式键优先。未设置该环境
    变量时不做任何默认路径探测。
    """
    defaults = default_config_dict()
    env = merge_env()
    logger = get_logger()

    # file 层：FLASHGAZE_CONFIG_FILE 指向的文件（M-11）。空串/纯空白视为未设置；
    # 文件不存在/损坏由 load_config_file 统一 WARNING 并回退空 dict，不中断运行。
    env_file_path = os.environ.get(ENV_CONFIG_FILE, "").strip()
    env_file_cfg: dict[str, Any] = load_config_file(env_file_path) if env_file_path else {}
    if env_file_cfg:
        logger.info(
            "已从 FLASHGAZE_CONFIG_FILE 加载配置文件: %s（%d 个键）",
            env_file_path,
            len(env_file_cfg),
        )
        if file_cfg:
            logger.info("同时存在 FLASHGAZE_CONFIG_FILE 与显式配置文件，显式配置文件的键优先")
    file_cfg = {**env_file_cfg, **(file_cfg or {})}

    # 配置文件传入的 weights 走校验：必填 sharpness/exposure，缺失或非法则
    # 回退默认权重（删除该 key 让 defaults 兜底），与 env/CLI 路径保持一致
    if "weights" in file_cfg:
        parsed = _parse_weights(file_cfg["weights"])
        if parsed is None:
            logger.warning(
                "配置文件 weights=%r 缺失必填 key（sharpness/exposure）或非法，回退到默认权重",
                file_cfg["weights"],
            )
            file_cfg = {k: v for k, v in file_cfg.items() if k != "weights"}
        else:
            file_cfg = {**file_cfg, "weights": parsed}

    # 三层基础合并：default < file < env
    base: dict[str, Any] = {**defaults, **file_cfg, **env}
    # overrides 覆盖（仅非 None 值）
    for k, v in overrides.items():
        if v is None:
            continue
        # EXIF 备份单一真源归一化（C-配置）：no_exif_backup 为兼容反向开关，不得进入
        # Config。任一来源传 no_exif_backup=True 即强制禁用备份（exif_backup=False），
        # 并在二者同时为真时记 WARNING 防止隐性矛盾。
        if k == "no_exif_backup":
            if v:
                if base.get("exif_backup"):
                    logger.warning(
                        "no_exif_backup=True 与 exif_backup=True 同时出现，归一化为不备份"
                        "（exif_backup=False）"
                    )
                base["exif_backup"] = False
            continue
        if k == "weights":
            # C-06：与 file/env 路径一致，override 的 weights 也必须经 _parse_weights
            # 校验（必填 sharpness/exposure），非法则忽略该 key 回退默认权重
            parsed = _parse_weights(v)
            if parsed is None:
                logger.warning(
                    "overrides weights=%r 缺失必填 key（sharpness/exposure）或非法，"
                    "已忽略，回退默认权重",
                    v,
                )
                continue
            base["weights"] = parsed
            continue
        base[k] = v

    # ── VLM 扩展字段校验（M3）──────────────────────────
    # 非法 provider/scene 回退到默认值并记 warning，不抛异常
    if base.get("vlm_provider") not in SUPPORTED_VLM_PROVIDERS:
        if base.get("vlm_provider") is not None:
            logger.warning(
                "不支持的 vlm_provider=%s，回退到 %s",
                base.get("vlm_provider"),
                DEFAULT_VLM_PROVIDER,
            )
        base["vlm_provider"] = DEFAULT_VLM_PROVIDER
    if base.get("scene") not in SUPPORTED_SCENES:
        if base.get("scene") is not None:
            logger.warning(
                "不支持的 scene=%s，回退到 %s",
                base.get("scene"),
                DEFAULT_SCENE,
            )
        base["scene"] = DEFAULT_SCENE

    # C-05：统一强转数值字段（workers/timeout_sec/max_retries/dedup_threshold）
    # 并钳制下限，避免配置文件/override 传入 str/float 触发 TypeError
    _coerce_numeric(base)

    # M-7：布尔字段强转（"false"/"0"/"no"/"off" 不得被当成真值），非法值告警回退。
    # 必须在 no_exif_backup 归一化之后、构造 Config 之前执行。
    _coerce_bool(base)

    # FIX(H-6)：api_base 端点白名单归一 + 非白名单告警（四条来源的唯一卡口）。
    # 必须在 vlm_provider 校验之后（判定依赖最终 provider）、_coerce_bool 之后
    # （allow_private_targets / allow_untrusted_api_base 已定型）执行。
    # 白名单来源可能是 str（env 逗号分隔）或 list（配置文件 JSON 数组），统一归一化。
    base["api_base_allowlist"] = _normalize_allowlist(base.get("api_base_allowlist"))
    _warn_untrusted_api_base(base)

    # FIX(#sec-threshold): top/threshold 边界钳制下沉到配置装配层，使 CLI / env /
    # 配置文件 / MCP 四条来源同时生效（此前 0-100 校验只存在于 cli/parser.py，
    # MCP 与配置文件可传入 threshold=150 让全部图不达标 → 一次调用删空工作空间）。
    _clamp_selection_bounds(base)

    # FIX(#3-3): vlm_max_adjustment 钳制到 [0.0, 100.0]，覆盖 env/文件/CLI 全部来源。
    _clamp_vlm_max_adjustment(base)

    # 熔断阈值钳制到 >= 0（0 = 关闭），覆盖 env/文件/CLI 全部来源。
    _clamp_vlm_breaker_threshold(base)

    # VLM 采样参数钳制（可复现性）：temperature ∈ [0,2]、seed 非负整数；
    # None（配置文件 null「不注入」）原样保留。
    _clamp_vlm_sampling(base)

    # 删除护栏最小样本量钳制到 >= 1（不可关闭），覆盖 env/文件/CLI 全部来源。
    _clamp_cleanup_guard_min_sample(base)

    # 过滤掉非 Config 字段，避免构造报错；
    # 未知键（拼写错误/已废弃）曾静默丢弃，现记 WARNING 便于发现配置未生效
    valid = _CONFIG_FIELD_NAMES
    kwargs: dict[str, Any] = {}
    for k, v in base.items():
        if k not in valid and k != "directory":
            logger.warning("忽略未知配置键: %s", k)
        elif k in valid and k != "directory":
            kwargs[k] = v
    config = Config(directory=directory, **kwargs)

    # 启用新维度但未自定义权重时，自动注入默认权重
    config = _adjust_weights_for_enabled_features(config)

    # 统一保证 config.weights 不可变：无论来源（默认/env/CLI/配置文件/自动注入），
    # 都用 MappingProxyType 包裹，封堵 config.weights["x"] = y 原地修改路径
    weights = config.weights
    if not isinstance(weights, MappingProxyType):
        weights = MappingProxyType(dict(weights))
    config = replace(config, weights=weights)

    # FIX(#C-15): 收尾硬校验权重总和 > 0，零和权重会让全部评分无意义，响亮失败。
    _validate_weights(config)
    return config
