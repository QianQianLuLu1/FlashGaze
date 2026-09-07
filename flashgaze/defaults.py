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

# ── VLM 批量熔断（core/vlm_client）──────────────────────
# 连续失败多少张图后熔断：熔断开启后剩余图直接跳过 VLM（纯 CV 口径），
# 避免端点宕机时每图重复烧满 max_retries × timeout 重试预算（假性挂起数小时）。
# 0 = 关闭熔断（等价旧行为，保守逃生通道）。
DEFAULT_VLM_BREAKER_THRESHOLD = 5

# ── VLM 采样参数（可复现性，PLAN-vlm-sampling-reproducibility）──────────
# 默认固定 temperature=0 + 固定 seed，收敛「启用 VLM 时」的采样随机性（结果可复现原则；
# 此前 payload 从未携带采样参数，同一批图两次运行得分可能不同）。
# provider 差异见 core/vlm_client.py::_PROVIDER_SPECS：anthropic 协议无 seed、
# temperature 上限 1.0；ollama OpenAI 兼容层对 seed 未承诺，保守不注入。
# None 语义 = 不注入对应参数（旧行为逃生舱，仅配置文件可达）。
DEFAULT_VLM_TEMPERATURE = 0.0
DEFAULT_VLM_SEED = 42

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

# ── api_base 端点白名单（H-6）──────────────────────────
# 内置各 provider 官方域名（按主机后缀匹配：host == 条目，或 host 以 ".条目" 结尾，
# 大小写不敏感）。非白名单端点**仅告警放行**（不阻断、不改退出码、不改配置值）：
# 任何来源（env / 配置文件 / CLI --api-base / WebUI 文本框）写入的端点都会在
# build_config 卡口留一条 WARNING，使配置劫持可见。
# 私网/回环主机在 provider=ollama 或 allow_private_targets 下免白名单，
# 以保住 LAN / Docker 自托管场景（仍走 pin-IP 直连与 SSRF 防护）。
DEFAULT_API_BASE_ALLOWLIST: tuple[str, ...] = (
    # 阿里云百炼 DashScope（qwen，OpenAI 兼容模式）与国际站
    "dashscope.aliyuncs.com",
    "dashscope-intl.aliyuncs.com",
    # OpenAI
    "api.openai.com",
    # Anthropic
    "api.anthropic.com",
    # 本机与容器回连宿主（ollama 自托管 / Docker）
    "localhost",
    "host.docker.internal",
)
# 追加自定义端点白名单（逗号分隔主机后缀），与内置默认**叠加前的替换**由
# build_config 决定：环境变量/配置文件一旦提供即整体替换内置默认。
ENV_API_BASE_ALLOWLIST = "FLASHGAZE_API_BASE_ALLOWLIST"
# 显式确认「当前 api_base 可信」的逃生舱（真值 1/true/yes/on）：
# 置位后非白名单端点不再告警，用于自托管 / 自建网关等合法非标端点。
ENV_ALLOW_UNTRUSTED_API_BASE = "FLASHGAZE_ALLOW_UNTRUSTED_API_BASE"

# 环境变量名
ENV_API_KEY = "FLASHGAZE_API_KEY"
ENV_API_BASE = "FLASHGAZE_API_BASE"
ENV_MODEL = "FLASHGAZE_MODEL"
ENV_TIMEOUT = "FLASHGAZE_TIMEOUT"
ENV_WORKERS = "FLASHGAZE_WORKERS"
ENV_MAX_RETRIES = "FLASHGAZE_MAX_RETRIES"
ENV_VLM_MAX_ADJUSTMENT = "FLASHGAZE_VLM_MAX_ADJUSTMENT"
# 环境变量：VLM 批量熔断的连续失败阈值（0 = 关闭熔断）
ENV_VLM_BREAKER_THRESHOLD = "FLASHGAZE_VLM_BREAKER_THRESHOLD"
# 环境变量：VLM 采样温度与固定种子（固定值收敛采样随机性；None「不注入」语义仅配置文件可达）
ENV_VLM_TEMPERATURE = "FLASHGAZE_VLM_TEMPERATURE"
ENV_VLM_SEED = "FLASHGAZE_VLM_SEED"
ENV_WEIGHTS = "FLASHGAZE_WEIGHTS"
# ── VLM 扩展新增环境变量 ─────────────────────────────
ENV_VLM_PROVIDER = "FLASHGAZE_VLM_PROVIDER"
ENV_SCENE = "FLASHGAZE_SCENE"
# 环境变量：显式允许 VLM 访问私网/链路本地等受限地址（SSRF 逃生通道，默认关）。
# ollama provider 内部已默认放行，无需此变量；本变量用于自托管 qwen/openai 兼容端点。
ENV_ALLOW_PRIVATE_TARGETS = "FLASHGAZE_ALLOW_PRIVATE_TARGETS"
# 环境变量：指向 JSON 配置文件的路径（审查项 M-11）。
# build_config 在 file 层加载该文件，使 CLI / MCP / WebUI 三入口的配置文件行为
# 一致；与 CLI --config-file 同层（逐键合并、显式传入的键优先），低于各
# FLASHGAZE_* 值变量。不做默认路径探测，未设置即不加载。
ENV_CONFIG_FILE = "FLASHGAZE_CONFIG_FILE"

# ── MCP 路径边界（mcp_server 允许扫描根，审查项 H-12）────
# 逗号分隔的允许根目录列表：MCP 上传/单图评分仅允许读取这些根内的图片，
# 越界路径直接拒绝，防止调用方把磁盘任意位置的图片读取后送往 VLM 端点。
# 未配置时回退为进程启动目录（CWD），保证开箱即有路径边界。
ENV_MCP_ALLOWED_ROOTS = "FLASHGAZE_MCP_ALLOWED_ROOTS"

# 选取默认值
DEFAULT_TOP = 30

# ── 清理删除护栏（core/cleanup.classify_and_delete）──────
# 实际删除模式下，待删数量占可评分图的比例超过此值时整批拦截（一张不删），
# 需调用方显式传 force 才放行。防御 threshold 越界/配置错误（如 threshold=150
# → 全部图不达标 → 一次调用删空整个工作空间）这类静默数据丢失。
# 比例按可评分图口径：分母不含 error 非 None 的损坏图（它们本就不进分子），
# 否则目录混有损坏图时比例被稀释、护栏失效（80 张可评分图全低分 + 20 张损坏
# → 80/100=80%<95%，一次删空全部可评分图、只剩损坏图）。
CLEANUP_MAX_DELETE_RATIO = 0.95
# 护栏启用的最小样本量：评分图少于此数量时不启用护栏。已从 20 下调为 6（不可逆
# 删除防护）：回收站 + force 指纹确认落地后，误拦的代价只是多一步 dry_run 核对，
# 而小目录同样暴露在 threshold 配置错误之下（如 --threshold 100 全不达标一次删空）。
# 可经 Config.cleanup_guard_min_sample（CLI --guard-min-sample / 配置文件）覆盖，
# 下限钳到 1——护栏不可经配置关闭，放行须走 --force + 清单指纹。
CLEANUP_GUARD_MIN_SAMPLE = 6

# ── 删除回收站与审计清单（core/cleanup.classify_and_delete）──
# 实际删除绝不再直接 unlink：先同卷 rename 进 workspace 内回收站（字节完整、可回滚），
# 再落盘审计清单（原路径 / 回收站路径 / SHA256 / 大小 / 评分），使删除可追溯。
# 目录与清单名均以 "." 开头——iter_images 整体跳过以 . 开头的目录与文件，回收站副本
# 与清单不会被 score / export / cleanup 二次扫描，故无需加入 exclusion_dirs。
CLEANUP_RECYCLE_DIR_NAME = ".flashgaze_deleted"
# 回收站内的批次子目录前缀（后接 UTC 时间戳与 pid，多次运行互不覆盖）
CLEANUP_RECYCLE_BATCH_PREFIX = "deleted_"
# 审计清单文件名前缀：<ws>/.flashgaze_deleted_<UTC>_<pid>.jsonl
DELETE_MANIFEST_PREFIX = ".flashgaze_deleted_"

# 支持的图片格式
SUPPORTED_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".tiff",
    ".tif",
    ".heic",
    ".heif",
)

# 拉普拉斯方差映射上限（超过此值封顶 100 分）
SHARPNESS_VARIANCE_CEIL = 500.0

# 清晰度评估时的归一化长边尺寸（消除分辨率差异）
SHARPNESS_NORMALIZE_SIZE = 1024

# 降采样阈值：图片长边超过此值时按比例等比缩小（仅用于内部评分，不修改原文件）
# 选 2048px 平衡内存占用与评分精度：远大于 SHARPNESS_NORMALIZE_SIZE(1024)，
# 避免降采样与归一化双重缩放引入额外偏差；同时将 4K+ 大图内存降至 1/4。
DOWNSCALE_THRESHOLD = 2048

# ── 解码像素预算（H-7，解压炸弹防护）────────────────────────────────────
# 单张图解码前的像素上限：超过即在分配像素缓冲之前抛 ImageReadError，降级为
# error 占位（绝不解压）。解压炸弹可让一个几十字节的文件声明上亿像素。
# Pillow 自带阈值为 89478485（约 89M 才告警、约 178M 才抛错），两者之间的
# 灰色地带正是"能解但可能 OOM"。评分只需长边 2048，64M 足以覆盖 61MP 全画幅
# （9504×6336≈60.2M）与 8K 帧（33M），同时拒绝 100M 级中画幅/拼接/炸弹图。
# 收紧后单张最坏约 192MB（3 通道），不再是无上限。
MAX_IMAGE_PIXELS = 64_000_000
# 环境变量：覆盖解码像素上限（正整数生效；0 或负数 = 关闭项目上限、沿用 Pillow
# 自带阈值），作为 100MP+ 中画幅等既有场景的逃生舱。运行期读取，见
# flashgaze.utils.image_io.max_image_pixels。
ENV_MAX_IMAGE_PIXELS = "FLASHGAZE_MAX_IMAGE_PIXELS"

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
# BRISQUE 模型目录固定在包内 flashgaze/models/brisque/，
# 由 cv_engine 通过 importlib.resources.files() 按包导入位置解析，
# 与工作目录无关，故不再定义路径常量。
# 人像加分上限（每张人脸 +1，首张 +3，封顶 5）
PORTRAIT_BONUS_MAX = 5.0
# PHash 去重默认汉明距离阈值（越小越严格）
DEFAULT_DEDUP_THRESHOLD = 8
# 环境变量：去重阈值
ENV_DEDUP_THRESHOLD = "FLASHGAZE_DEDUP_THRESHOLD"
# 环境变量：显式允许运行时联网下载 BRISQUE 模型（默认关闭）。
# 缺省行为是"缺文件即降级"，绝不隐式联网；开启后下载内容仍须通过 SHA256 校验。
ENV_BRISQUE_ALLOW_DOWNLOAD = "FLASHGAZE_BRISQUE_ALLOW_DOWNLOAD"
