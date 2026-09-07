from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import IntEnum

from flashgaze.defaults import (
    CLEANUP_GUARD_MIN_SAMPLE,
    DEFAULT_API_BASE,
    DEFAULT_API_BASE_ALLOWLIST,
    DEFAULT_EXPORT_DIR,
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
    VLM_REASON_MAX_CHARS,
)

# 清单列定义单一来源：CSV / XLSX / 导出契约共用，避免多处置裂（C-09）。
# 顺序即 to_row() 返回值顺序，改动需同步 ImageScore.to_row()。
MANIFEST_COLUMNS = (
    "file",
    "path",
    "sharpness",
    "exposure",
    "composition",
    "vlm_adjustment",
    "score",
    "selected",
    "error",
    "noise",
    "color",
    "face_count",
    "face_sharpness",
    "portrait_bonus",
    "deduped",
    "vlm_reason",
    "vlm_provider",
    "vlm_applied",
    "vlm_error",
)


class ExitCode(IntEnum):
    """标准返回码。CLI 与 JSON 输出共用此定义。"""

    SUCCESS = 0  # 成功
    PARAM_ERROR = 1  # 参数错误
    API_FAILURE = 2  # API 调用失败（非致命时降级为 0）
    NO_IMAGES = 3  # 目录无效或无图片
    IMAGE_ERROR = 4  # 图片处理错误（单图损坏/不支持）
    EXPORT_ERROR = 5  # 导出失败
    CONFIG_ERROR = 6  # 配置错误（缺 API Key 等）
    # H-2：EXIF 元数据写入存在失败项（部分失败也算）——原以 SUCCESS 收场，
    # Agent/CI 无法程序化感知「评分成功但原图 EXIF 未写入」。
    EXIF_ERROR = 7  # EXIF 写入失败
    # H-8：main() 兜底层专用——子命令未自行收敛的异常（既非参数错误也非评分/
    # 导出/配置错误）统一落到此码，杜绝裸 traceback 后由解释器返回的默认 1
    # （与 PARAM_ERROR 数值重叠，Agent/CI 无法区分「参数错」与「内部崩溃」）。
    INTERNAL_ERROR = 8  # 未预期的内部错误（main 兜底）


# CSV/Excel 公式注入防护（LOW-5）：以这些前缀开头的字符串单元格会被 Excel/WPS
# 当公式求值（典型载体：攻击者构造的文件名，或 VLM 返回的 reason 以 "=" 开头）。
# 统一在 to_row()（CSV/XLSX 清单单一来源）加 ' 前缀中和，数值/布尔不受影响。
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _formula_safe(value: object) -> object:
    """字符串单元格以公式前缀开头时加 ' 前缀，阻断 CSV/Excel 公式注入。"""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


@dataclass(frozen=True)
class CVResult:
    """CV 引擎单图评分结果。frozen=True 保证不可变，可复现。"""

    sharpness: float  # 0-100，清晰度
    exposure: float  # 0-100，曝光度
    composition: float | None = None  # 0-100，构图分（实验性，默认 None）
    noise: float | None = None  # 0-100，噪点分（BRISQUE，默认 None）
    color: float | None = None  # 0-100，色彩丰富度（HSV 直方图，默认 None）
    error: str | None = None  # 错误信息，None 表示成功


@dataclass(frozen=True)
class PortraitResult:
    """人像专项评分结果。"""

    face_count: int = 0  # 检测到的人脸数量
    face_sharpness: float | None = None  # 人脸区域清晰度 0-100
    portrait_bonus: float = 0.0  # 人像加分 0-5
    error: str | None = None  # 错误信息


@dataclass(frozen=True)
class VLMResult:
    """VLM 场景补偿结果。"""

    adjustment: float  # -max ~ +max，场景补偿分
    reason: str  # 判断依据摘要（≤20 字）
    ok: bool = True  # 调用是否成功
    error: str | None = None  # 错误信息
    # ── VLM 扩展（M1）──────────────────────────────────
    provider: str = ""  # 实际调用的提供商标识（qwen/openai/anthropic/ollama）
    scene: str = "auto"  # 本次评分使用的场景标签

    def __post_init__(self) -> None:
        # 早期强制截断：无论来源（_parse_response 成功/失败路径、hybrid_scorer
        # 兜底、或未来新路径），reason 在对象诞生即受契约约束（≤20 字，按字符计），
        # 保证 JSON/CSV/EXIF 三 sink 输出一致。frozen 允许 __post_init__ 改字段。
        object.__setattr__(self, "reason", (self.reason or "")[:VLM_REASON_MAX_CHARS])


@dataclass
class ImageScore:
    """单图最终评分。CLI 输出与 JSON 清单的最小单元。"""

    file: str  # 文件名
    path: str  # 绝对路径
    sharpness: float
    exposure: float
    composition: float | None
    vlm_adjustment: float
    score: float  # 综合分 0-100
    selected: bool = False  # 是否入选
    error: str | None = None
    # ── CV 增强维度（M2/M3）──────────────────────────────
    noise: float | None = None  # 0-100，噪点分（BRISQUE）
    color: float | None = None  # 0-100，色彩丰富度
    # ── 人像专项（M4）────────────────────────────────────
    face_count: int = 0  # 检测到的人脸数量
    face_sharpness: float | None = None  # 人脸区域清晰度
    portrait_bonus: float = 0.0  # 人像加分
    # ── 去重标记（M5）────────────────────────────────────
    deduped: bool = False  # 是否被去重标记（保留最高分图）
    # ── VLM 可解释性（VLM 扩展 M1/M4）──────────────────
    vlm_reason: str = ""  # VLM 评分理由（≤20 字），未启用或失败时为空串
    vlm_provider: str = ""  # VLM 提供商标识，未启用时为空串
    # ── VLM 评分口径（熔断降级可观测）────────────────────
    # True 表示 VLM 结果参与了打分（含成功但补偿恰为 0 的情况），
    # 用于区分「VLM 成功」/「VLM 失败降级纯 CV」/「未启用 VLM」三种此前不可区分的状态。
    vlm_applied: bool = False
    vlm_error: str = ""  # VLM 调用失败原因（retry_exhausted/circuit_open 等），未启用时为空串

    def to_row(self) -> list[object]:
        """导出清单行（CSV/XLSX 单一来源，C-09）。

        顺序严格对应 MANIFEST_COLUMNS；None 维度统一转空串，
        selected/deduped/vlm_applied 保留原生布尔（供 XLSX 识别为 Excel 布尔）。
        字符串列（file/path/error/vlm_reason/vlm_provider/vlm_error）经
        _formula_safe 中和公式前缀（LOW-5），两个写出方（CSV/XLSX）自动同享防护。
        """
        return [
            _formula_safe(self.file),
            _formula_safe(self.path),
            self.sharpness,
            self.exposure,
            "" if self.composition is None else self.composition,
            self.vlm_adjustment,
            self.score,
            self.selected,
            _formula_safe("" if self.error is None else self.error),
            "" if self.noise is None else self.noise,
            "" if self.color is None else self.color,
            self.face_count,
            "" if self.face_sharpness is None else self.face_sharpness,
            self.portrait_bonus,
            self.deduped,
            _formula_safe(self.vlm_reason),
            _formula_safe(self.vlm_provider),
            self.vlm_applied,
            _formula_safe(self.vlm_error),
        ]

    def to_display_row(self) -> list[object]:
        """WebUI 表格/画廊展示行（与 app.TABLE_HEADERS 列数对齐）。

        与 to_row() 是两个关注点，各自单一来源：此处对分数四舍五入、
        selected/deduped 用 ✓ 标记、分数前置以贴合展示，不改底层清单格式。
        """
        mark = "✓" if self.selected else ""
        dedup_mark = "✓" if self.deduped else ""
        return [
            self.file,
            round(self.score, 2),
            round(self.sharpness, 2),
            round(self.exposure, 2),
            "" if self.composition is None else round(self.composition, 2),
            "" if self.noise is None else round(self.noise, 2),
            "" if self.color is None else round(self.color, 2),
            self.face_count,
            "" if self.face_sharpness is None else round(self.face_sharpness, 2),
            round(self.portrait_bonus, 2),
            round(self.vlm_adjustment, 2),
            self.vlm_reason,
            self.vlm_provider,
            self.vlm_applied,
            self.vlm_error,
            mark,
            dedup_mark,
            "" if self.error is None else self.error,
        ]


@dataclass(frozen=True)
class Config:
    """运行时配置。由 CLIParser 装配，全模块共享。

    frozen=True 强制装配后不可变，所有变更必须通过 dataclasses.replace 生成副本，
    避免共享状态突变（如 MCP export_selected_images 改 export/move 字段）。
    注意：weights 字段虽不可重新赋值，但若底层为可变 dict 仍可原地修改；
    已通过 C-07 将 DEFAULT_WEIGHTS 改为 MappingProxyType 不可变映射，
    配合此处 Mapping[str, float] 类型注解，彻底封堵原地修改路径。

    字段职责分组（C-16 轻量方案：保持单一 Config，文档标注职责）：
      - 评分核心（CLI 与 MCP 共用）：directory / top / threshold / no_vlm /
        enable_composition / api_key / api_base / model / timeout_sec /
        max_retries / workers / weights / vlm_max_adjustment
        该分组的入口层镜像见 models/options.py::ScoringOptions（字段名必须逐字对齐，
        否则 build_config 会静默丢弃拼错的键）
      - CLI 输出专用（MCP 不使用）：output_json / output_csv / output_path /
        csv_output_path / verbose
      - 导出专用（CLI 与 MCP export_selected_images 共用）：export / export_dir / move
    """

    # ── 评分核心字段（CLI 与 MCP 共用）─────────────────────
    directory: str
    # 默认值单一真源：与 CLI/WebUI/MCP 三处预填共用 defaults.DEFAULT_TOP
    top: int = DEFAULT_TOP
    threshold: float | None = None
    no_vlm: bool = False
    enable_composition: bool = False
    # CV 增强维度开关（M2/M3/M4/M5）：默认 False，确保默认行为与原版完全一致
    enable_noise: bool = False  # BRISQUE 无参考噪点评分
    enable_color: bool = False  # HSV 色彩丰富度评分
    enable_portrait: bool = False  # 人像专项评分（face_recognition）
    dedup: bool = False  # PHash 图片去重（imagededup）
    dedup_threshold: int | None = None  # PHash 汉明距离阈值，None 时用 DEFAULT_DEDUP_THRESHOLD
    # 降采样：默认 False（启用降采样），传 --no-downscale 时置 True 使用原始分辨率
    no_downscale: bool = False
    api_key: str | None = None
    api_base: str = DEFAULT_API_BASE
    model: str = DEFAULT_MODEL
    timeout_sec: int = DEFAULT_TIMEOUT_SEC
    max_retries: int = DEFAULT_MAX_RETRIES
    workers: int = DEFAULT_WORKERS
    weights: Mapping[str, float] = field(default_factory=lambda: DEFAULT_WEIGHTS)
    vlm_max_adjustment: float = DEFAULT_VLM_MAX_ADJUSTMENT
    # ── VLM 批量熔断（core/vlm_client）──────────────────
    # 连续失败多少张图后熔断（剩余图跳过 VLM、纯 CV 口径）；0 = 关闭熔断。
    # 与 vlm_max_adjustment 同类：仅 env / 配置文件可达，不设 CLI 旗标。
    vlm_breaker_threshold: int = DEFAULT_VLM_BREAKER_THRESHOLD
    # ── VLM 采样参数（可复现性，PLAN-vlm-sampling-reproducibility）──
    # 默认 temperature=0 + 固定 seed=42，收敛「启用 VLM 时」的采样随机性（此前
    # payload 从未携带采样参数，同一批图两次运行得分可能不同）。payload 注入与
    # provider 裁剪唯一真源见 core/vlm_client.py::effective_sampling_params。
    # None = 不注入该参数（旧行为逃生舱，仅配置文件 null 可达——overrides/env 语义
    # 中 None 是「不覆盖」）。与 vlm_breaker_threshold 同类：仅 env / 配置文件可达，
    # 不设 CLI 旗标。
    vlm_temperature: float | None = DEFAULT_VLM_TEMPERATURE
    vlm_seed: int | None = DEFAULT_VLM_SEED
    # ── VLM 多提供商与场景化（VLM 扩展 M1/M3）──────────
    # 所有 provider 默认走内置 pin-IP 直连层；use_litellm=True 时走可选 LiteLLM 后端
    vlm_provider: str = DEFAULT_VLM_PROVIDER
    # 场景模式：auto 由 VLM 自行判断，与原版单一提示词一致
    scene: str = DEFAULT_SCENE
    # ── SSRF 防护逃生通道（本修复）──────────────────────────
    # 默认 False：私网/链路本地/保留/组播地址仍按 SSRF 拒绝（qwen/openai/anthropic 公网云 API）。
    # 置 True 时放行上述受限地址（仍走 pin-IP 直连，保留 DNS 重绑定 TOCTOU 防护），
    # 用于自托管 qwen/openai 兼容端点；ollama provider 默认即视为自托管、内部自动放行，无需本开关。
    allow_private_targets: bool = False
    # ── api_base 端点白名单（H-6）──────────────────────────
    # 端点白名单（主机后缀）：非空时整体替换内置默认；空元组回落内置默认。
    # 非白名单端点**仅告警放行**（不阻断、不改退出码），使配置劫持在日志中可见。
    # 私网/回环主机在 provider=ollama 或 allow_private_targets 下免白名单。
    api_base_allowlist: tuple[str, ...] = DEFAULT_API_BASE_ALLOWLIST
    # 显式确认「当前 api_base 可信」的逃生舱：置 True 后非白名单端点不再告警。
    allow_untrusted_api_base: bool = False
    # ── 插件系统（M4）────────────────────────────────────
    enable_plugins: bool = False  # 是否执行插件评分阶段
    plugin_dir: str | None = None  # 自定义插件目录（可选）

    # ── 删除护栏（cleanup）────────────────────────────────
    # 批量删除比例护栏的最小样本量：评分图少于此数量时不启用 95% 比例护栏。
    # 装配期由 _clamp_cleanup_guard_min_sample 钳制（<1 → 1，非法回退默认）——
    # 护栏不可经配置关闭，放行须走 --force + 清单指纹。
    cleanup_guard_min_sample: int = CLEANUP_GUARD_MIN_SAMPLE

    # ── 导出字段（CLI --export 与 MCP export_selected_images 共用）──
    export: bool = False
    export_dir: str = DEFAULT_EXPORT_DIR  # 导出目标目录（--export-dir）
    move: bool = False
    # ── EXIF 元数据导出（M2）──
    exif: bool = False  # 评分后是否将结果写入图片 EXIF
    exif_backup: bool = True  # 单一真源：写入前是否落盘原图备份（.flashgaze_backup/）供回滚。
    # 反向语义（--no-exif-backup）已在 CLI parser 层反向映射为本字段，不另设独立开关字段，
    # 杜绝「exif_backup=True 且 no_exif_backup=True」的隐性矛盾。

    # ── CLI 输出专用字段（MCP 模式不使用）──────────────────
    output_json: bool = False
    output_csv: bool = False
    output_path: str | None = None  # JSON 清单输出路径（--output）
    csv_output_path: str | None = None  # CSV 清单输出路径（--csv-output，默认 DEFAULT_CSV_OUTPUT）
    # ── Excel 导出（M3）──
    output_xlsx: bool = False  # 是否生成 .xlsx 清单（--xlsx）
    xlsx_output_path: str | None = None  # .xlsx 输出路径（--xlsx-output，默认 DEFAULT_XLSX_OUTPUT）
    verbose: bool = False
