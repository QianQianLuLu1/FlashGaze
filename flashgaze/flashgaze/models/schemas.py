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
    DEFAULT_TIMEOUT_SEC,
    DEFAULT_VLM_MAX_ADJUSTMENT,
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
    error: Optional[str] = None            # 错误信息，None 表示成功


@dataclass(frozen=True)
class VLMResult:
    """VLM 场景补偿结果。"""

    adjustment: float                      # -max ~ +max，场景补偿分
    reason: str                            # 判断依据摘要
    ok: bool = True                        # 调用是否成功
    error: Optional[str] = None            # 错误信息


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
    api_key: Optional[str] = None
    api_base: str = DEFAULT_API_BASE
    model: str = DEFAULT_MODEL
    timeout_sec: int = DEFAULT_TIMEOUT_SEC
    max_retries: int = DEFAULT_MAX_RETRIES
    workers: int = DEFAULT_WORKERS
    weights: Mapping[str, float] = field(default_factory=lambda: DEFAULT_WEIGHTS)
    vlm_max_adjustment: float = DEFAULT_VLM_MAX_ADJUSTMENT

    # ── 导出字段（CLI --export 与 MCP export_selected_images 共用）──
    export: bool = False
    export_dir: str = DEFAULT_EXPORT_DIR  # 导出目标目录（--export-dir）
    move: bool = False

    # ── CLI 输出专用字段（MCP 模式不使用）──────────────────
    output_json: bool = False
    output_csv: bool = False
    output_path: Optional[str] = None       # JSON 清单输出路径（--output）
    csv_output_path: Optional[str] = None   # CSV 清单输出路径（--csv-output，默认 DEFAULT_CSV_OUTPUT）
    verbose: bool = False
