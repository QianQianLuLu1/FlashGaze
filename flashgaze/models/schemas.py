from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Mapping, Optional

from flashgaze.defaults import (
    DEFAULT_API_BASE,
    DEFAULT_CSV_OUTPUT,
    DEFAULT_EXPORT_DIR,
    DEFAULT_MAX_RETRIES,
    DEFAULT_MODEL,
    DEFAULT_SCENE,
    DEFAULT_TIMEOUT_SEC,
    DEFAULT_VLM_MAX_ADJUSTMENT,
    DEFAULT_VLM_PROVIDER,
    DEFAULT_WEIGHTS,
    DEFAULT_WORKERS,
)


class ExitCode(IntEnum):
    """标准返回码。CLI 与 JSON 输出共用此定义。"""

    SUCCESS = 0          # 成功
    PARAM_ERROR = 1      # 参数错误
    API_FAILURE = 2      # API 调用失败（非致命时降级为 0）
    NO_IMAGES = 3        # 目录无效或无图片
    IMAGE_ERROR = 4      # 图片处理错误（单图损坏/不支持）
    EXPORT_ERROR = 5     # 导出失败
    CONFIG_ERROR = 6     # 配置错误（缺 API Key 等）


@dataclass(frozen=True)
class CVResult:
    """CV 引擎单图评分结果。frozen=True 保证不可变，可复现。"""

    sharpness: float                       # 0-100，清晰度
    exposure: float                        # 0-100，曝光度
    composition: Optional[float] = None    # 0-100，构图分（实验性，默认 None）
    noise: Optional[float] = None          # 0-100，噪点分（BRISQUE，默认 None）
    color: Optional[float] = None          # 0-100，色彩丰富度（HSV 直方图，默认 None）
    error: Optional[str] = None            # 错误信息，None 表示成功


@dataclass(frozen=True)
class PortraitResult:
    """人像专项评分结果。"""

    face_count: int = 0                                    # 检测到的人脸数量
    face_sharpness: Optional[float] = None                 # 人脸区域清晰度 0-100
    portrait_bonus: float = 0.0                            # 人像加分 0-5
    error: Optional[str] = None                            # 错误信息


@dataclass(frozen=True)
class VLMResult:
    """VLM 场景补偿结果。"""

    adjustment: float                      # -max ~ +max，场景补偿分
    reason: str                            # 判断依据摘要（≤20 字）
    ok: bool = True                        # 调用是否成功
    error: Optional[str] = None            # 错误信息
    # ── VLM 扩展（M1）──────────────────────────────────
    provider: str = ""                     # 实际调用的提供商标识（qwen/openai/anthropic/ollama）
    scene: str = "auto"                    # 本次评分使用的场景标签


@dataclass
class ImageScore:
    """单图最终评分。CLI 输出与 JSON 清单的最小单元。"""

    file: str                              # 文件名
    path: str                              # 绝对路径
    sharpness: float
    exposure: float
    composition: Optional[float]
    vlm_adjustment: float
    score: float                           # 综合分 0-100
    selected: bool = False                 # 是否入选
    error: Optional[str] = None
    # ── CV 增强维度（M2/M3）──────────────────────────────
    noise: Optional[float] = None          # 0-100，噪点分（BRISQUE）
    color: Optional[float] = None          # 0-100，色彩丰富度
    # ── 人像专项（M4）────────────────────────────────────
    face_count: int = 0                    # 检测到的人脸数量
    face_sharpness: Optional[float] = None # 人脸区域清晰度
    portrait_bonus: float = 0.0            # 人像加分
    # ── 去重标记（M5）────────────────────────────────────
    deduped: bool = False                  # 是否被去重标记（保留最高分图）
    # ── VLM 可解释性（VLM 扩展 M1/M4）──────────────────
    vlm_reason: str = ""                   # VLM 评分理由（≤20 字），未启用或失败时为空串
    vlm_provider: str = ""                 # VLM 提供商标识，未启用时为空串


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
      - CLI 输出专用（MCP 不使用）：output_json / output_csv / output_path /
        csv_output_path / verbose
      - 导出专用（CLI 与 MCP export_selected_images 共用）：export / export_dir / move
    """

    # ── 评分核心字段（CLI 与 MCP 共用）─────────────────────
    directory: str
    top: int = 30
    threshold: Optional[float] = None
    no_vlm: bool = False
    enable_composition: bool = False
    # CV 增强维度开关（M2/M3/M4/M5）：默认 False，确保默认行为与原版完全一致
    enable_noise: bool = False             # BRISQUE 无参考噪点评分
    enable_color: bool = False             # HSV 色彩丰富度评分
    enable_portrait: bool = False          # 人像专项评分（face_recognition）
    dedup: bool = False                    # PHash 图片去重（imagededup）
    dedup_threshold: Optional[int] = None  # PHash 汉明距离阈值，None 时用 DEFAULT_DEDUP_THRESHOLD
    # 降采样：默认 False（启用降采样），传 --no-downscale 时置 True 使用原始分辨率
    no_downscale: bool = False
    api_key: Optional[str] = None
    api_base: str = DEFAULT_API_BASE
    model: str = DEFAULT_MODEL
    timeout_sec: int = DEFAULT_TIMEOUT_SEC
    max_retries: int = DEFAULT_MAX_RETRIES
    workers: int = DEFAULT_WORKERS
    weights: Mapping[str, float] = field(default_factory=lambda: DEFAULT_WEIGHTS)
    vlm_max_adjustment: float = DEFAULT_VLM_MAX_ADJUSTMENT
    # ── VLM 多提供商与场景化（VLM 扩展 M1/M3）──────────
    # provider=qwen 时走原 requests.post 路径，零新依赖；其他 provider 走 LiteLLM
    vlm_provider: str = DEFAULT_VLM_PROVIDER
    # 场景模式：auto 由 VLM 自行判断，与原版单一提示词一致
    scene: str = DEFAULT_SCENE
    # ── 插件系统（M4）────────────────────────────────────
    enable_plugins: bool = False               # 是否执行插件评分阶段
    plugin_dir: Optional[str] = None           # 自定义插件目录（可选）

    # ── 导出字段（CLI --export 与 MCP export_selected_images 共用）──
    export: bool = False
    export_dir: str = DEFAULT_EXPORT_DIR  # 导出目标目录（--export-dir）
    move: bool = False
    # ── EXIF 元数据导出（M2）──
    exif: bool = False               # 评分后是否将结果写入图片 EXIF
    no_exif_backup: bool = False     # True 时禁用 .flashgaze_backup 原文件备份

    # ── CLI 输出专用字段（MCP 模式不使用）──────────────────
    output_json: bool = False
    output_csv: bool = False
    output_path: Optional[str] = None       # JSON 清单输出路径（--output）
    csv_output_path: Optional[str] = None   # CSV 清单输出路径（--csv-output，默认 DEFAULT_CSV_OUTPUT）
    # ── Excel 导出（M3）──
    output_xlsx: bool = False               # 是否生成 .xlsx 清单（--xlsx）
    xlsx_output_path: Optional[str] = None  # .xlsx 输出路径（--xlsx-output，默认 DEFAULT_XLSX_OUTPUT）
    verbose: bool = False
