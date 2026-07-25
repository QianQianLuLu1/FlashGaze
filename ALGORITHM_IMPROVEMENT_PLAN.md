# FlashGaze 评分算法改进计划

> 范围：构图评分增强 + VLM prompt 国际化。所有改动默认关闭，保证现有 134 项测试与 `--no-vlm` 可复现性不受影响。

---

## 1. 现状分析

### 1.1 构图评分算法（[cv_engine.py:94-116](file:///h:/45001/Documents/SaiTu%20skill/flashgaze/flashgaze/core/cv_engine.py#L94-L116)）

当前 `compute_composition` 的完整逻辑：

```python
def compute_composition(self, img_path: str) -> float:
    color = load_image_color(img_path)
    gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    moments = cv2.moments(thresh)
    if moments["m00"] == 0:
        return 50.0
    cx = moments["m10"] / moments["m00"]
    cy = moments["m01"] / moments["m00"]
    thirds_x = [w / 3, 2 * w / 3]
    thirds_y = [h / 3, 2 * h / 3]
    min_dist = min(abs(cx - tx) + abs(cy - ty) for tx in thirds_x for ty in thirds_y)
    diag = (w**2 + h**2) ** 0.5
    score = max(0.0, 100.0 - (min_dist / diag) * 300.0)
    return float(round(score, 2))
```

**局限性：**

1. **单一维度——仅三分法质心**。整张图只算一个质心到三分线交点的曼哈顿距离，无法识别引导线、对称、框架、前景/背景层次等常见构图语言。一张引导线汇聚完美但质心偏移的图，反而得分低于一张质心到位但画面平庸的图。

2. **Otsu 二值化假设"前景 vs 背景"二元结构**。对低对比度、雾景、逆光剪影、多主体场景，Otsu 阈值要么失败（`m00 == 0` 直接返回中位分 50，丢失全部信息），要么把噪声当作前景，质心漂移到无意义位置。测试中 `test_composition_returns_float_in_range` 仅验证范围，未验证区分度。

3. **曼哈顿距离 + 线性映射过于粗糙**。`min_dist / diag * 300` 的 300 是经验系数，缺乏理论依据；质心稍偏离三分点即快速掉分，无法体现"接近三分点"与"远离三分点"的真实差异梯度。

4. **无显著性信息**。无法判断主体是否突出——一张主体居中但被杂乱背景淹没的图，质心可能在三分点上拿到高分，实际构图却很差。

5. **`enable_composition` 默认 `False`**（[schemas.py:90](file:///h:/45001/Documents/SaiTu%20skill/flashgaze/flashgaze/models/schemas.py#L90)），且 [hybrid_scorer.py:99](file:///h:/45001/Documents/SaiTu%20skill/flashgaze/flashgaze/core/hybrid_scorer.py#L99) 中 `c_w` 在 `composition is None` 时为 0——即使启用，权重也被归一化稀释。当前构图分对最终评分影响微弱。

### 1.2 VLM prompt 硬编码中文（[vlm_client.py:69-77](file:///h:/45001/Documents/SaiTu%20skill/flashgaze/flashgaze/core/vlm_client.py#L69-L77)）

```python
def _build_prompt(self, cv: CVResult) -> str:
    return (
        "你是摄影评分助手。下面给出该图的客观指标："
        f"清晰度={cv.sharpness}/100，曝光度={cv.exposure}/100。"
        "请判断图片中的'模糊'或'偏暗'是否为艺术手法..."
    )
```

**局限性：**

1. **prompt 字符串硬编码在 `_build_prompt` 方法体内**，无法在不改源码的情况下切换语言或调整措辞。
2. **仅中文模板**。使用英文 VLM 模型（如 GPT-4o-mini）时，中文 prompt 可能导致理解偏差或 token 效率下降；面向国际用户时也无法本地化。
3. **无配置入口**。`VLMClient` 构造函数（[vlm_client.py:23-39](file:///h:/45001/Documents/SaiTu%20skill/flashgaze/flashgaze/core/vlm_client.py#L23-L39)）没有 `vlm_lang` 参数，`Config`（[schemas.py:66-110](file:///h:/45001/Documents/SaiTu%20skill/flashgaze/flashgaze/models/schemas.py#L66-L110)）也没有对应字段，环境变量层（[config.py:45-90](file:///h:/45001/Documents/SaiTu%20skill/flashgaze/flashgaze/utils/config.py#L45-L90)）更无读取逻辑。三层都缺。

---

## 2. 改进目标

### 2.1 构图评分增强

在现有三分法基础上，增加三个评分维度，**全部使用 OpenCV + NumPy 已有能力，不引入新依赖**：

| 维度 | 算法 | OpenCV / NumPy API | 评估目标 |
|------|------|---------------------|----------|
| 引导线检测 | Canny 边缘 + Hough 直线变换 | `cv2.Canny`、`cv2.HoughLinesP` | 画面中是否存在汇聚向主体的引导线 |
| 对称性评估 | 水平/垂直翻转后像素差异 | `cv2.flip`、`cv2.absdiff`、`np.mean` | 评估对称构图（水面倒影、建筑对称等）质量 |
| 主体显著性 | 谱残差（Spectral Residual） | `np.fft.fft2`、`np.log`、`np.exp`（纯 NumPy 实现） | 主体在画面中的突出程度 |

> **关于谱残差实现**：OpenCV 的 `cv2.saliency.SaliencySpectralResidual_create()` 位于 `opencv-contrib-python`，项目当前仅依赖 `opencv-python`。为严格遵守"不引入新依赖"的约束，谱残差用 **NumPy FFT 手动实现**（谱残差本质就是对幅度谱做 log 残差再 IFFT，纯数值运算）。这也保证 `--no-vlm` 模式的可复现性不受外部库版本波动影响。

**最终 `compute_composition` 综合分权重：**

| 维度 | 权重 | 理由 |
|------|------|------|
| 三分法 | 0.3 | 构图基础，主体位置仍是核心 |
| 引导线 | 0.2 | 强化视觉引导，但非所有照片都有 |
| 对称性 | 0.2 | 特定场景（建筑、倒影）才适用 |
| 显著性 | 0.3 | 主体突出度，通用且重要 |

### 2.2 VLM prompt 国际化

- prompt 模板从 `_build_prompt` 方法体抽取为模块级常量（中英文两套）
- 通过 `FLASHGAZE_VLM_LANG` 环境变量或配置文件 `vlm_lang` 字段切换
- 支持值：`"zh"`（中文，默认）、`"en"`（英文）
- **默认保持中文**，向后兼容现有用户的评分行为

---

## 3. 详细实施步骤

### 3.1 构图评分增强

#### 3.1.1 在 `defaults.py` 新增常量

```python
# 构图评分权重（综合分内部加权，四项总和应为 1.0）
COMPOSITION_WEIGHT_THIRDS = 0.3
COMPOSITION_WEIGHT_LEADING_LINES = 0.2
COMPOSITION_WEIGHT_SYMMETRY = 0.2
COMPOSITION_WEIGHT_SALIENCY = 0.3

# 引导线检测参数
LEADING_LINES_CANNY_LOW = 50          # Canny 低阈值
LEADING_LINES_CANNY_HIGH = 150        # Canny 高阈值
LEADING_LINES_HOUGH_THRESHOLD = 80    # HoughLinesP 累加器阈值
LEADING_LINES_HOUGH_MIN_LINE_LEN = 50 # 最短直线长度
LEADING_LINES_HOUGH_MAX_LINE_GAP = 10 # 最大线段间隙（可连接的）

# 对称性评估参数
SYMMETRY_DIFF_CEIL = 60.0  # 翻转差异均值映射上限（0~CEIL → 0~100），差异越大分越低

# 显著性（谱残差）参数
SALIENCY_RESIZE_SIZE = 64   # FFT 前缩放边长（谱残差对尺寸不敏感，64 足够且快）
SALIENCY_MAP_CEIL = 0.25    # 显著性图归一化后均值映射上限
```

#### 3.1.2 在 `cv_engine.py` 新增三个方法

**方法 1：`_detect_leading_lines(gray) -> float`**

```python
def _detect_leading_lines(self, gray: np.ndarray) -> float:
    """Canny + HoughLinesP 检测引导线，返回 0-100。

    思路：检测画面中的直线段，统计其方向分布。若存在多条直线
    汇聚向画面中心区域（消失点附近），说明有强引导线，给高分；
    若直线稀少或方向散乱，给低分。
    """
    h, w = gray.shape[:2]
    edges = cv2.Canny(gray, LEADING_LINES_CANNY_LOW, LEADING_LINES_CANNY_HIGH)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=LEADING_LINES_HOUGH_THRESHOLD,
        minLineLength=LEADING_LINES_HOUGH_MIN_LINE_LEN,
        maxLineGap=LEADING_LINES_HOUGH_MAX_LINE_GAP,
    )
    if lines is None:
        return 20.0  # 无直线，给基础分（非 0，避免过度惩罚无直线的场景）
    
    cx_img, cy_img = w / 2, h / 2
    converging_count = 0
    total = len(lines)
    for ln in lines:
        x1, y1, x2, y2 = ln[0]
        # 计算直线延长线是否靠近画面中心（消失点估计）
        # 用直线两端到中心的平均距离，归一化后判断收敛性
        dist = (abs(x1 - cx_img) + abs(y1 - cy_img) +
                abs(x2 - cx_img) + abs(y2 - cy_img)) / 4
        diag = (w**2 + h**2) ** 0.5
        if dist / diag < 0.3:
            converging_count += 1
    # 汇聚比例 + 直线数量共同决定分数
    ratio = converging_count / total if total > 0 else 0
    count_factor = min(total / 10.0, 1.0)  # 10 条直线封顶
    score = (ratio * 0.6 + count_factor * 0.4) * 100.0
    return float(round(min(score, 100.0), 2))
```

**方法 2：`_compute_symmetry(gray) -> float`**

```python
def _compute_symmetry(self, gray: np.ndarray) -> float:
    """翻转差异计算对称性，返回 0-100。

    水平翻转 + 垂直翻转，取两者中较小差异（较高对称性）。
    差异越小，对称性越高，分越高。
    """
    h_flip = cv2.flip(gray, 1)  # 水平翻转（左右对称检测）
    v_flip = cv2.flip(gray, 0)  # 垂直翻转（上下对称检测）
    diff_h = float(cv2.mean(cv2.absdiff(gray, h_flip))[0])
    diff_v = float(cv2.mean(cv2.absdiff(gray, v_flip))[0])
    min_diff = min(diff_h, diff_v)
    # 差异 0 → 满分 100；差异 >= CEIL → 0 分
    score = max(0.0, 100.0 - (min_diff / SYMMETRY_DIFF_CEIL) * 100.0)
    return float(round(score, 2))
```

**方法 3：`_compute_saliency(gray) -> float`**

```python
def _compute_saliency(self, gray: np.ndarray) -> float:
    """谱残差（Spectral Residual）显著性检测，返回 0-100。

    纯 NumPy 实现，不依赖 opencv-contrib。
    步骤：
    1. 缩放到固定尺寸（FFT 对大图慢，64x64 足够）
    2. 二维 FFT → 幅度谱 + 相位谱
    3. log 幅度谱减去其均值滤波（残差）
    4. 残差 + 相位谱 → IFFT → 显著性图
    5. 平滑后归一化，取显著性区域的强度均值作为分数
    """
    small = cv2.resize(gray, (SALIENCY_RESIZE_SIZE, SALIENCY_RESIZE_SIZE),
                       interpolation=cv2.INTER_AREA)
    f = np.fft.fft2(small)
    magnitude = np.abs(f)
    phase = np.angle(f)
    log_mag = np.log(magnitude + 1e-8)
    # 3x3 均值滤波得到"背景平均 log 谱"
    avg = cv2.blur(log_mag, (3, 3))
    residual = log_mag - avg
    # 重建并 IFFT
    rebuilt = np.exp(residual + 1j * phase)
    saliency_map = np.abs(np.fft.ifft2(rebuilt))
    # 平滑抑制高频噪声
    saliency_map = cv2.GaussianBlur(saliency_map, (5, 5), 0)
    # 归一化到 0-1
    s_min, s_max = float(saliency_map.min()), float(saliency_map.max())
    if s_max - s_min < 1e-8:
        return 50.0  # 平坦图，无显著区域
    saliency_norm = (saliency_map - s_min) / (s_max - s_min)
    # 显著性图均值越高，说明整体越突出
    mean_sal = float(saliency_norm.mean())
    score = min(mean_sal / SALIENCY_MAP_CEIL * 100.0, 100.0)
    return float(round(score, 2))
```

#### 3.1.3 修改 `compute_composition` 方法

```python
def compute_composition(self, img_path: str) -> float:
    """综合构图评分（三分法 + 引导线 + 对称性 + 显著性）→ 0-100。

    四项加权平均：三分法 0.3 + 引导线 0.2 + 对称性 0.2 + 显著性 0.3。
    各子项均返回 0-100，加权后仍是 0-100。
    """
    color = load_image_color(img_path)
    gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)

    thirds = self._compute_thirds(gray)
    leading = self._detect_leading_lines(gray)
    symmetry = self._compute_symmetry(gray)
    saliency = self._compute_saliency(gray)

    score = (
        thirds * COMPOSITION_WEIGHT_THIRDS
        + leading * COMPOSITION_WEIGHT_LEADING_LINES
        + symmetry * COMPOSITION_WEIGHT_SYMMETRY
        + saliency * COMPOSITION_WEIGHT_SALIENCY
    )
    return float(round(min(max(score, 0.0), 100.0), 2))
```

> 将原 `compute_composition` 中的三分法逻辑抽取为私有方法 `_compute_thirds(gray) -> float`（逻辑不变，仅接收已加载的 `gray` 避免重复读图）。`img_path` 读图一次，传递给四个子方法。

#### 3.1.4 在 `cv_engine.py` 顶部新增 import

```python
from flashgaze.defaults import (
    EXPOSURE_BRIGHT_THRESHOLD,
    EXPOSURE_DARK_THRESHOLD,
    SHARPNESS_NORMALIZE_SIZE,
    SHARPNESS_VARIANCE_CEIL,
    # 新增构图相关常量
    COMPOSITION_WEIGHT_THIRDS,
    COMPOSITION_WEIGHT_LEADING_LINES,
    COMPOSITION_WEIGHT_SYMMETRY,
    COMPOSITION_WEIGHT_SALIENCY,
    LEADING_LINES_CANNY_LOW,
    LEADING_LINES_CANNY_HIGH,
    LEADING_LINES_HOUGH_THRESHOLD,
    LEADING_LINES_HOUGH_MIN_LINE_LEN,
    LEADING_LINES_HOUGH_MAX_LINE_GAP,
    SYMMETRY_DIFF_CEIL,
    SALIENCY_RESIZE_SIZE,
    SALIENCY_MAP_CEIL,
)
```

### 3.2 VLM prompt 国际化

#### 3.2.1 在 `defaults.py` 新增常量

```python
# VLM prompt 语言（zh=中文，en=英文）
DEFAULT_VLM_LANG = "zh"
SUPPORTED_VLM_LANGS = ("zh", "en")

# 环境变量
ENV_VLM_LANG = "FLASHGAZE_VLM_LANG"
```

#### 3.2.2 在 `schemas.py` 的 `Config` 中新增字段

在 [schemas.py:98](file:///h:/45001/Documents/SaiTu%20skill/flashgaze/flashgaze/models/schemas.py#L98) `vlm_max_adjustment` 之后添加：

```python
vlm_lang: str = DEFAULT_VLM_LANG
```

并在顶部 import 中补充 `DEFAULT_VLM_LANG`。

#### 3.2.3 在 `config.py` 的 `merge_env()` 中读取环境变量

在 [config.py:73](file:///h:/45001/Documents/SaiTu%20skill/flashgaze/flashgaze/utils/config.py#L73) `ENV_VLM_MAX_ADJUSTMENT` 分支后添加：

```python
if os.environ.get(ENV_VLM_LANG):
    lang = os.environ[ENV_VLM_LANG].strip().lower()
    if lang in SUPPORTED_VLM_LANGS:
        cfg["vlm_lang"] = lang
```

并在 `default_config_dict()` 中补充 `"vlm_lang": DEFAULT_VLM_LANG`，在顶部 import 中补充 `DEFAULT_VLM_LANG`、`ENV_VLM_LANG`、`SUPPORTED_VLM_LANGS`。

#### 3.2.4 在 `vlm_client.py` 中实现 prompt 国际化

**步骤 1：构造函数添加 `vlm_lang` 参数**

```python
def __init__(
    self,
    api_key: str,
    api_base: str,
    model: str,
    timeout_sec: int = 30,
    max_retries: int = 3,
    max_adjustment: float = 10.0,
    vlm_lang: str = "zh",          # 新增
):
    ...
    self.vlm_lang = vlm_lang if vlm_lang in ("zh", "en") else "zh"
```

**步骤 2：将 prompt 模板抽为模块级常量**

```python
_PROMPT_TEMPLATES = {
    "zh": (
        "你是摄影评分助手。下面给出该图的客观指标："
        "清晰度={sharpness}/100，曝光度={exposure}/100。"
        "请判断图片中的'模糊'或'偏暗'是否为艺术手法"
        "（如背景虚化、逆光剪影、暗调氛围）。"
        "若是艺术手法，给正补偿；若是技术失误，给负补偿。"
        "补偿值范围 -{max_adj} 到 +{max_adj}。"
        "仅返回 JSON：{{\"adjustment\": 数字, \"reason\": \"一句话理由\"}}"
    ),
    "en": (
        "You are a photography scoring assistant. "
        "Objective metrics for this image: "
        "sharpness={sharpness}/100, exposure={exposure}/100. "
        "Judge whether 'blurriness' or 'darkness' in the image is an artistic technique "
        "(e.g., background bokeh, backlit silhouette, moody low-key). "
        "If it is an artistic technique, give positive compensation; "
        "if it is a technical flaw, give negative compensation. "
        "Compensation range: -{max_adj} to +{max_adj}. "
        "Return only JSON: {{\"adjustment\": number, \"reason\": \"one-sentence reason\"}}"
    ),
}
```

**步骤 3：`_build_prompt` 改为根据 `self.vlm_lang` 选模板**

```python
def _build_prompt(self, cv: CVResult) -> str:
    template = _PROMPT_TEMPLATES.get(self.vlm_lang, _PROMPT_TEMPLATES["zh"])
    return template.format(
        sharpness=cv.sharpness,
        exposure=cv.exposure,
        max_adj=self.max_adjustment,
    )
```

#### 3.2.5 在 VLMClient 两处构造点透传 `vlm_lang`

**[entry.py:52-59](file:///h:/45001/Documents/SaiTu%20skill/flashgaze/flashgaze/cli/entry.py#L52-L59)：**

```python
vlm_client = VLMClient(
    api_key=config.api_key,
    api_base=config.api_base,
    model=config.model,
    timeout_sec=config.timeout_sec,
    max_retries=config.max_retries,
    max_adjustment=config.vlm_max_adjustment,
    vlm_lang=config.vlm_lang,          # 新增
)
```

**[mcp_server.py:69-76](file:///h:/45001/Documents/SaiTu%20skill/flashgaze/flashgaze/mcp_server.py#L69-L76) `_make_vlm_client`：**

```python
return VLMClient(
    api_key=config.api_key,
    api_base=config.api_base,
    model=config.model,
    timeout_sec=config.timeout_sec,
    max_retries=config.max_retries,
    max_adjustment=config.vlm_max_adjustment,
    vlm_lang=config.vlm_lang,          # 新增
)
```

### 3.3 测试更新

#### 3.3.1 构图评分新增单元测试（追加到 `tests/test_cv_engine.py`）

```python
# ---------- 引导线 ----------
def test_leading_lines_returns_float_in_range(sharp_img):
    engine = CVEngine(enable_composition=True)
    from flashgaze.utils.image_io import load_image_grayscale
    import cv2
    gray = cv2.cvtColor(load_image_grayscale(sharp_img), cv2.COLOR_GRAY2B2GRAY)  # 视实际签名调整
    score = engine._detect_leading_lines(gray)
    assert isinstance(score, float)
    assert 0.0 <= score <= 100.0

def test_leading_lines_is_deterministic(sharp_img):
    engine = CVEngine(enable_composition=True)
    gray = load_image_grayscale(sharp_img)
    scores = [engine._detect_leading_lines(gray) for _ in range(5)]
    assert len(set(scores)) == 1

# ---------- 对称性 ----------
def test_symmetry_returns_float_in_range(sharp_img):
    gray = load_image_grayscale(sharp_img)
    score = CVEngine()._compute_symmetry(gray)
    assert isinstance(score, float)
    assert 0.0 <= score <= 100.0

def test_symmetry_is_deterministic(sharp_img):
    gray = load_image_grayscale(sharp_img)
    scores = [CVEngine()._compute_symmetry(gray) for _ in range(5)]
    assert len(set(scores)) == 1

# ---------- 显著性 ----------
def test_saliency_returns_float_in_range(sharp_img):
    gray = load_image_grayscale(sharp_img)
    score = CVEngine()._compute_saliency(gray)
    assert isinstance(score, float)
    assert 0.0 <= score <= 100.0

def test_saliency_is_deterministic(sharp_img):
    gray = load_image_grayscale(sharp_img)
    scores = [CVEngine()._compute_saliency(gray) for _ in range(5)]
    assert len(set(scores)) == 1

# ---------- 综合构图 ----------
def test_composition_still_in_range_after_enhancement(sharp_img):
    score = CVEngine(enable_composition=True).compute_composition(sharp_img)
    assert 0.0 <= score <= 100.0

def test_composition_is_deterministic_after_enhancement(sharp_img):
    engine = CVEngine(enable_composition=True)
    scores = [engine.compute_composition(sharp_img) for _ in range(10)]
    assert len(set(scores)) == 1
```

> 注意：`load_image_grayscale` 已在 `flashgaze.utils.image_io` 中导出，测试需在文件头补充 `from flashgaze.utils.image_io import load_image_grayscale`。

#### 3.3.2 VLM prompt 国际化测试（追加到 `tests/test_vlm_client.py`）

```python
# ---------- prompt 国际化 ----------
def test_default_prompt_is_chinese(sharp_img, monkeypatch):
    """默认 vlm_lang='zh'，prompt 含中文关键词。"""
    captured = {}
    def fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        return _ok_response(1.0)
    monkeypatch.setattr("flashgaze.core.vlm_client.requests.post", fake_post)
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    client.judge(sharp_img, _make_cv())
    prompt = captured["payload"]["messages"][0]["content"][0]["text"]
    assert "摄影评分助手" in prompt
    assert "清晰度" in prompt

def test_english_prompt_when_vlm_lang_en(sharp_img, monkeypatch):
    """vlm_lang='en' 时，prompt 为英文。"""
    captured = {}
    def fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        return _ok_response(1.0)
    monkeypatch.setattr("flashgaze.core.vlm_client.requests.post", fake_post)
    client = VLMClient(api_key="k", api_base="http://x", model="m", vlm_lang="en")
    client.judge(sharp_img, _make_cv())
    prompt = captured["payload"]["messages"][0]["content"][0]["text"]
    assert "photography scoring assistant" in prompt
    assert "sharpness" in prompt
    assert "清晰度" not in prompt

def test_invalid_vlm_lang_falls_back_to_chinese():
    """非法 vlm_lang 回退为中文。"""
    client = VLMClient(api_key="k", api_base="http://x", model="m", vlm_lang="fr")
    assert client.vlm_lang == "zh"

def test_prompt_contains_cv_metrics(sharp_img, monkeypatch):
    """prompt 中包含 CV 指标数值。"""
    captured = {}
    def fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        return _ok_response(1.0)
    monkeypatch.setattr("flashgaze.core.vlm_client.requests.post", fake_post)
    cv = CVResult(sharpness=85.5, exposure=72.3)
    client = VLMClient(api_key="k", api_base="http://x", model="m")
    client.judge(sharp_img, cv)
    prompt = captured["payload"]["messages"][0]["content"][0]["text"]
    assert "85.5" in prompt
    assert "72.3" in prompt
```

#### 3.3.3 环境变量读取测试（追加到 `tests/test_config.py`）

```python
def test_merge_env_reads_vlm_lang(monkeypatch):
    monkeypatch.setenv("FLASHGAZE_VLM_LANG", "en")
    from flashgaze.utils.config import merge_env
    cfg = merge_env()
    assert cfg.get("vlm_lang") == "en"

def test_merge_env_ignores_invalid_vlm_lang(monkeypatch):
    monkeypatch.setenv("FLASHGAZE_VLM_LANG", "fr")
    from flashgaze.utils.config import merge_env
    cfg = merge_env()
    assert "vlm_lang" not in cfg  # 非法值被静默忽略
```

#### 3.3.4 确保可复现性测试不变

- **关键保证**：新增的三个构图方法都是纯函数式计算（Canny、Hough、FFT、flip 均为确定性算法），无随机性。
- `--no-vlm` 模式下，`enable_composition` 默认 `False`，`compute_composition` 根本不会被调用——现有 6 项可复现性测试（[test_reproducibility.py](file:///h:/45001/Documents/SaiTu%20skill/flashgaze/tests/test_reproducibility.py)）的 `Config(directory=".", no_vlm=True, top=2)` 未设 `enable_composition`，保持 `False`，分数路径完全不变。
- `test_cv_composition_10_runs_identical` 和 `test_cv_evaluate_10_runs_identical` 显式启用构图，需验证增强后的构图分仍 10 次一致——确定性算法天然满足。

---

## 4. 向后兼容保证

| 改动 | 兼容性保证 |
|------|-----------|
| 构图评分增强 | `enable_composition` 默认 `False`（[schemas.py:90](file:///h:/45001/Documents/SaiTu%20skill/flashgaze/flashgaze/models/schemas.py#L90)），新增的三维度仅在显式启用时才参与计算。未启用时 `compute_composition` 不被调用，`CVResult.composition` 为 `None`，`_weighted_cv_score` 中 `c_w=0`，最终分与改动前完全一致。 |
| VLM prompt 国际化 | `DEFAULT_VLM_LANG = "zh"`，`Config.vlm_lang` 默认中文，`VLMClient` 构造函数 `vlm_lang` 默认 `"zh"`。未设置环境变量且未传参时，`_build_prompt` 选用中文模板，内容与改动前逐字一致（仅从方法体抽为常量，语义零变化）。 |
| 环境变量 | `FLASHGAZE_VLM_LANG` 为新增变量，未设置时 `merge_env()` 不写入 `vlm_lang` key，回落到 `default_config_dict()` 的默认值。 |
| 测试 | 现有 134 项测试中，无任何测试断言构图分的具体数值（仅断言范围与可复现性），增强后的构图分仍在 0-100 内且确定性不变。VLM 测试未断言 prompt 具体内容，国际化不破坏现有断言。 |

---

## 5. 验证清单

- [ ] 新增构图方法（`_detect_leading_lines`、`_compute_symmetry`、`_compute_saliency`）有单元测试覆盖
- [ ] `_compute_thirds` 抽取后，原有三分法逻辑不变
- [ ] `--no-vlm` 模式可复现性测试全部通过（6 项：清晰度、曝光度、构图、evaluate、HybridScorer、CLI e2e）
- [ ] `enable_composition=True` 时，构图分 10 次调用完全一致
- [ ] VLM prompt 中英文切换正常（`vlm_lang="zh"` → 中文，`"en"` → 英文）
- [ ] 非法 `vlm_lang` 回退为中文
- [ ] `FLASHGAZE_VLM_LANG=en` 环境变量被 `merge_env()` 正确读取
- [ ] 非法 `FLASHGAZE_VLM_LANG` 被静默忽略（不影响配置装配）
- [ ] 现有 134 项测试全部通过
- [ ] 新增测试全部通过
- [ ] 无新依赖引入（仅用 `cv2`、`numpy`、标准库）

---

## 6. 参考项目

- **[ocampor/image-quality](https://github.com/ocampor/image-quality)**：图像质量评估库。参考其清晰度（拉普拉斯方差）与曝光度评估思路，但 FlashGaze 已实现这两项。本次仅借鉴其对多维度分数加权聚合的架构思路，不引入该依赖（它依赖 `scipy`，违反"不引入新依赖"约束）。
- **OpenCV 文档**：
  - [`cv2.HoughLinesP`](https://docs.opencv.org/master/dd/dd1/tutorial__hough_lines.html)：概率霍夫直线变换，检测直线段
  - [`cv2.Canny`](https://docs.opencv.org/master/da/d22/tutorial_py_canny.html)：Canny 边缘检测
  - [`cv2.flip`](https://docs.opencv.org/master/d2/de8/group__core__array.html#gaca7be533e3dac7feb70fc60635adf441)：图像翻转
  - [`cv2.absdiff`](https://docs.opencv.org/master/d2/de8/group__core__array.html#ga6fef31bc8c4071cbc114a058fa2ce898)：绝对差值
  - 谱残差原论文：Xiaodi Hou & Liqing Zhang, "Saliency Detection: A Spectral Residual Approach", CVPR 2007. 用 NumPy FFT 实现而非 `cv2.saliency`（后者属 `opencv-contrib-python`）。

---

## 附：实施顺序建议

1. **先做 VLM prompt 国际化**（改动小、独立、风险低）→ 跑测试确认绿
2. **再做 `defaults.py` 常量新增** → 跑测试确认绿（仅新增常量，不影响逻辑）
3. **再做 `_compute_thirds` 抽取**（纯重构，不改逻辑）→ 跑测试确认绿
4. **逐个新增三个构图方法**（每加一个跑一次测试）→ 确保每步可回滚
5. **最后修改 `compute_composition` 综合加权** → 跑全量测试 + 可复现性测试
6. **补齐所有新增测试** → 确认全绿

每步完成后运行：`python -m pytest tests/ -v`，确保现有 134 项 + 新增项全通过。
