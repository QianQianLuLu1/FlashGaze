"""全局默认常量。所有可被环境变量/配置文件覆盖的值都从这里取默认。"""

from types import MappingProxyType

# VLM API 默认配置
DEFAULT_API_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen-vl-max"
DEFAULT_TIMEOUT_SEC = 30
DEFAULT_MAX_RETRIES = 3
DEFAULT_WORKERS = 4

# 评分权重（清晰度、曝光度）
# MappingProxyType 不可变映射，防止全局状态被原地修改（C-07）。
# 读取（.get/.items）兼容 dict；赋值（["x"] = y）会抛 TypeError。
DEFAULT_WEIGHTS = MappingProxyType({"sharpness": 0.5, "exposure": 0.5})

# VLM 补偿范围
DEFAULT_VLM_MAX_ADJUSTMENT = 10.0

# ── VLM 多提供商与场景化（VLM 扩展 M1）─────────────────
# 默认 VLM 提供商：qwen 走原 OpenAI 兼容路径，零新依赖，100% 向后兼容
DEFAULT_VLM_PROVIDER = "qwen"
# 默认场景：auto 由 VLM 自行判断，与原版单一提示词语义一致
DEFAULT_SCENE = "auto"
# 支持的 VLM 提供商白名单（构建 Config 时校验）
SUPPORTED_VLM_PROVIDERS = ("qwen", "openai", "anthropic", "ollama")
# 支持的场景模式白名单
SUPPORTED_SCENES = ("auto", "portrait", "landscape", "still_life")
# vlm_reason 字段最大字符数（按字符计，不按字节）
VLM_REASON_MAX_CHARS = 20

# 环境变量名
ENV_API_KEY = "FLASHGAZE_API_KEY"
ENV_API_BASE = "FLASHGAZE_API_BASE"
ENV_MODEL = "FLASHGAZE_MODEL"
ENV_TIMEOUT = "FLASHGAZE_TIMEOUT"
ENV_WORKERS = "FLASHGAZE_WORKERS"
ENV_MAX_RETRIES = "FLASHGAZE_MAX_RETRIES"
ENV_VLM_MAX_ADJUSTMENT = "FLASHGAZE_VLM_MAX_ADJUSTMENT"
ENV_WEIGHTS = "FLASHGAZE_WEIGHTS"
# ── VLM 扩展新增环境变量 ─────────────────────────────
ENV_VLM_PROVIDER = "FLASHGAZE_VLM_PROVIDER"
ENV_SCENE = "FLASHGAZE_SCENE"

# 选取默认值
DEFAULT_TOP = 30

# 支持的图片格式
SUPPORTED_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".webp",
    ".bmp", ".tiff", ".tif",
    ".heic", ".heif",
)

# 拉普拉斯方差映射上限（超过此值封顶 100 分）
SHARPNESS_VARIANCE_CEIL = 500.0

# 清晰度评估时的归一化长边尺寸（消除分辨率差异）
SHARPNESS_NORMALIZE_SIZE = 1024

# 降采样阈值：图片长边超过此值时按比例等比缩小（仅用于内部评分，不修改原文件）
# 选 2048px 平衡内存占用与评分精度：远大于 SHARPNESS_NORMALIZE_SIZE(1024)，
# 避免降采样与归一化双重缩放引入额外偏差；同时将 4K+ 大图内存降至 1/4。
DOWNSCALE_THRESHOLD = 2048

# 直方图极端像素阈值
EXPOSURE_DARK_THRESHOLD = 30
EXPOSURE_BRIGHT_THRESHOLD = 225

# 导出目录
DEFAULT_EXPORT_DIR = "./精选"

# CSV 清单默认输出文件名（F-04：单一来源，避免 entry.py 硬编码）
DEFAULT_CSV_OUTPUT = "flashgaze_result.csv"
# XLSX 清单默认输出文件名（M3）
DEFAULT_XLSX_OUTPUT = "flashgaze_result.xlsx"

# ── CV 增强维度常量（M2/M4/M5）──────────────────────────
# BRISQUE 模型文件目录（相对包路径，需用户自行下载模型文件）
BRISQUE_MODEL_DIR = "flashgaze/models/brisque"
# 人像加分上限（每张人脸 +1，首张 +3，封顶 5）
PORTRAIT_BONUS_MAX = 5.0
# PHash 去重默认汉明距离阈值（越小越严格）
DEFAULT_DEDUP_THRESHOLD = 8
# 环境变量：去重阈值
ENV_DEDUP_THRESHOLD = "FLASHGAZE_DEDUP_THRESHOLD"
