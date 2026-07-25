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

# 直方图极端像素阈值
EXPOSURE_DARK_THRESHOLD = 30
EXPOSURE_BRIGHT_THRESHOLD = 225

# ── 构图评分参数 ────────────────────────────────────────
# 综合分内部权重（四项总和应为 1.0；saliency 不可用时由 compute_composition
# 自动按 thirds/leading/symmetry 三项归一化）
COMPOSITION_WEIGHT_THIRDS = 0.3
COMPOSITION_WEIGHT_LEADING_LINES = 0.2
COMPOSITION_WEIGHT_SYMMETRY = 0.2
COMPOSITION_WEIGHT_SALIENCY = 0.3

# 引导线检测参数（Canny + HoughLinesP）
LEADING_LINES_CANNY_LOW = 50           # Canny 低阈值
LEADING_LINES_CANNY_HIGH = 150         # Canny 高阈值
LEADING_LINES_HOUGH_THRESHOLD = 80     # HoughLinesP 累加器阈值
LEADING_LINES_HOUGH_MIN_LINE_LEN = 50  # 最短直线长度
LEADING_LINES_HOUGH_MAX_LINE_GAP = 10  # 最大可连接线段间隙

# 对称性评估参数
# 翻转差异均值映射上限（0~CEIL → 100~0），差异越大分越低
SYMMETRY_DIFF_CEIL = 60.0

# 显著性（谱残差）参数
SALIENCY_MAP_CEIL = 0.25  # 显著性图归一化后均值映射上限

# 导出目录
DEFAULT_EXPORT_DIR = "./flashgaze_selected"

# CSV 清单默认输出文件名（F-04：单一来源，避免 entry.py 硬编码）
DEFAULT_CSV_OUTPUT = "flashgaze_result.csv"

# 环境变量名
ENV_API_KEY = "FLASHGAZE_API_KEY"
ENV_API_BASE = "FLASHGAZE_API_BASE"
ENV_MODEL = "FLASHGAZE_MODEL"
ENV_TIMEOUT = "FLASHGAZE_TIMEOUT"
ENV_WORKERS = "FLASHGAZE_WORKERS"
ENV_MAX_RETRIES = "FLASHGAZE_MAX_RETRIES"
ENV_VLM_MAX_ADJUSTMENT = "FLASHGAZE_VLM_MAX_ADJUSTMENT"
ENV_WEIGHTS = "FLASHGAZE_WEIGHTS"
ENV_VLM_LANG = "FLASHGAZE_VLM_LANG"

# VLM prompt 语言（zh=中文，en=英文）
DEFAULT_VLM_LANG = "zh"
SUPPORTED_VLM_LANGS = ("zh", "en")
