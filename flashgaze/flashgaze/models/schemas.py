from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional

from flashgaze.defaults import (
    DEFAULT_API_BASE,
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


@dataclass
class Config:
    """运行时配置。由 CLIParser 装配，全模块共享。"""

    directory: str
    top: int = 30
    threshold: Optional[float] = None
    export: bool = False
    export_dir: str = DEFAULT_EXPORT_DIR  # 导出目标目录（--export-dir）
    move: bool = False
    output_json: bool = False
    output_csv: bool = False
    output_path: Optional[str] = None       # JSON 清单输出路径（--output）
    csv_output_path: Optional[str] = None   # CSV 清单输出路径（--csv-output）
    no_vlm: bool = False
    enable_composition: bool = False
    api_key: Optional[str] = None
    api_base: str = DEFAULT_API_BASE
    model: str = DEFAULT_MODEL
    timeout_sec: int = DEFAULT_TIMEOUT_SEC
    max_retries: int = DEFAULT_MAX_RETRIES
    workers: int = DEFAULT_WORKERS
    weights: dict = field(default_factory=lambda: DEFAULT_WEIGHTS)
    vlm_max_adjustment: float = DEFAULT_VLM_MAX_ADJUSTMENT
    verbose: bool = False
