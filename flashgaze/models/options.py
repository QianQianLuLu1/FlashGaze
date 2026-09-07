"""评分选项载体：CLI / MCP / WebUI 三个入口共享的"评分旋钮"单一事实来源。

字段名与 `flashgaze.models.schemas.Config` 逐字同名，值域语义与
`flashgaze.utils.config.build_config` 的 `overrides` 逐字相同：`None` = 不覆盖下层配置。

它只是入口层的搬运载体——不做校验、不读 env、不读配置文件、不做归一化，
那些仍然只发生在 `build_config` 里（保持唯一实现）。

本模块只依赖标准库：不 import Config / build_config / argparse / gradio / mcp，
既避免循环依赖，也让契约测试能零依赖运行。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from typing import Any

# 入口标识。字段 metadata 里的 entries 声明"该旋钮应在哪些入口暴露"，
# 供契约测试与 argparse dest / MCP 工具签名 / WebUI 表单做差集断言。
ENTRY_CLI = "cli"
ENTRY_MCP = "mcp"
ENTRY_WEBUI = "webui"
ALL_ENTRIES = (ENTRY_CLI, ENTRY_MCP, ENTRY_WEBUI)


def _knob(entries: tuple[str, ...] = ALL_ENTRIES) -> Any:
    """声明一个评分旋钮：默认 None（不覆盖），并记录应暴露它的入口。"""
    return field(default=None, metadata={"entries": entries})


@dataclass(frozen=True)
class ScoringOptions:
    """三入口共享的评分旋钮。全部字段默认 None，语义为"不覆盖下层配置"。

    不含 `directory`：它是作用对象而非旋钮，且 `build_config` 已把它作为独立位置参数
    （`score_uploaded_images` 还要显式传空串）。放进来只会制造"两个 directory 谁优先"的歧义。

    不含输出/导出字段（output_json / export / move / verbose 等）：它们只有单个入口用，
    留在各入口原地传给 `build_config`。
    """

    # ── 选取策略 ──
    top: int | None = _knob()
    threshold: float | None = _knob()
    # ── 评分维度开关 ──
    no_vlm: bool | None = _knob()
    enable_composition: bool | None = _knob()
    enable_noise: bool | None = _knob()
    enable_color: bool | None = _knob()
    enable_portrait: bool | None = _knob()
    # ── 去重 ──
    dedup: bool | None = _knob()
    dedup_threshold: int | None = _knob()
    # ── 性能 ──
    no_downscale: bool | None = _knob((ENTRY_CLI, ENTRY_WEBUI, ENTRY_MCP))
    workers: int | None = _knob()
    # ── VLM 接入 ──
    api_key: str | None = _knob((ENTRY_CLI, ENTRY_WEBUI))  # MCP 走 env
    api_base: str | None = _knob((ENTRY_CLI, ENTRY_WEBUI))
    model: str | None = _knob((ENTRY_CLI, ENTRY_WEBUI))
    vlm_provider: str | None = _knob()
    scene: str | None = _knob()
    timeout_sec: int | None = _knob(())  # 仅 env / 配置文件
    max_retries: int | None = _knob(())
    vlm_max_adjustment: float | None = _knob(())
    vlm_breaker_threshold: int | None = _knob(())  # 仅 env / 配置文件
    # 仅 env / 配置文件（与 vlm_breaker_threshold 同定位）；Config 侧 None = 不注入
    # 采样参数（旧行为逃生舱），ScoringOptions 侧 None = 不覆盖下层配置
    vlm_temperature: float | None = _knob(())
    vlm_seed: int | None = _knob(())
    # ── 权重（已解析好的 Mapping；JSON 串/滑块的解析留在各入口）──
    weights: Mapping[str, float] | None = _knob((ENTRY_CLI, ENTRY_WEBUI))
    # ── 插件 ──
    enable_plugins: bool | None = _knob((ENTRY_CLI,))
    plugin_dir: str | None = _knob((ENTRY_CLI,))
    # ── 删除护栏（cleanup 专用）──
    # 仅 CLI 暴露：MCP/WebUI 不设 cleanup 旋钮，走默认值或 env/配置文件。
    cleanup_guard_min_sample: int | None = _knob((ENTRY_CLI,))

    def to_config_kwargs(self) -> dict[str, Any]:
        """转成 `build_config` 的 overrides。

        三条硬约束：

        1. **只剔除 None，绝不剔除 False / 0 / ""** —— 与 `build_config` 的
           `if v is not None: base[k] = v` 逐字对齐。写成 `if value` 会让
           `--no-vlm` 之类的显式 False 失去覆盖能力，静默改变优先级链路。
        2. **禁止用 `dataclasses.asdict()`** —— 它会递归深拷贝 `weights`，破坏
           `_adjust_weights_for_enabled_features` 依赖的
           `config.weights is not DEFAULT_WEIGHTS` 身份比较。此处用 `fields()` +
           `getattr` 做浅取，保留对象身份。
        3. **`weights` 默认必须是 None** —— 一旦默认"有值"，就会永远向下传 weights，
           启用 noise/color 时的自动权重注入将永久失效且无任何报错。
        """
        kwargs: dict[str, Any] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if value is not None:
                kwargs[f.name] = value
        return kwargs


def knobs_for(entry: str) -> frozenset[str]:
    """返回应在指定入口暴露的旋钮字段名集合（契约测试据此检查各入口有无漏接）。"""
    return frozenset(
        f.name for f in fields(ScoringOptions) if entry in f.metadata.get("entries", ())
    )
