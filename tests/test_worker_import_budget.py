"""进程池 worker 的导入闭包不得连带加载重可选依赖（CI run 40174423841 的回归用例）。

`ProcessPoolExecutor` 的 worker 按 module+qualname **重新 import** `flashgaze.core.hybrid_scorer`
才能反序列化阶段 1 的顶层函数。该文件曾把三个「重」可选依赖的宿主模块放在模块级导入：

- `flashgaze/core/deduplicator.py:18` → `imagededup`（整套 hash/CNN 栈）
- `flashgaze/core/vlm_client.py:55` → `litellm`
- `flashgaze/core/portrait_engine.py:32` → `face_recognition`（dlib + 模型加载）

于是每起一个 worker 都要重付一遍这三笔 import。放大项是「池数 × worker 数」：
`tests/test_hybrid_scorer.py:490` 一条用例就是 10 次 `score_batch` × 4 worker = 40 次 spawn。
实测后果是 extras CI 腿在 macOS 上跑满 2091s 仍未结束、被 `timeout-minutes: 40` 杀掉
（同一命令 ubuntu 只要 404s；而默认矩阵的 ubuntu→macOS 只差 1.46 倍——差额正是这里，
因为默认矩阵不装 imagededup/litellm/face_recognition，worker 无税可付）。

判据用「假包被真正 import 时独立落盘的哨兵文件」，不用计时（计时断言必 flaky，见
docs/agent-context/pitfalls.md §3.9），也不用 stdout（本用例要测的正是「有没有导入」）。
假包经 `PYTHONPATH` 前置注入，真实 extras 装上时同样被影子覆盖，故 12 腿与 extras 双腿
都是有效测量。**一律子进程隔离**：本进程的 `sys.modules` 早已被同会话其他测试填满，
就地 purge 会产生第二份模块对象并污染 `tests/test_portrait.py` 的双向 skipif 判定
（范式与理由同 `tests/test_portrait_import_guard.py`）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# 子进程走完全程才会打印的成功标记。
CHILD_OK = "CHILD_OK"

# 三个重可选依赖（顶层包名，与 .coveragerc-extras 无关，纯粹按 import 成本取）。
HEAVY_MODULES = ("imagededup", "litellm", "face_recognition")


def _sentinel(fake_root: Path, name: str) -> Path:
    """假包 name 被导入时落盘的哨兵文件路径（在 fake_root 的上一级）。"""
    return fake_root.parent / f"loaded_{name}.txt"


def _mark_source(sentinel: Path) -> str:
    """写进假包 __init__ 的自报家门代码：落一个独立哨兵文件。"""
    return (
        f"import pathlib\npathlib.Path({str(sentinel)!r}).write_text('loaded', encoding='utf-8')\n"
    )


def _install_heavy_fakes(tmp_path: Path) -> Path:
    """造三个「一被导入就落哨兵」的假可选依赖，返回要放进 PYTHONPATH 的目录。

    假包必须**可用**（提供被测代码真正会取的名字），否则「导入成功」与「导入失败被
    守卫兜住」两种状态在哨兵上分不开——后者照样落了哨兵，但用例要测的是前者。
    """
    fake_root = tmp_path / "heavy_fakes"
    (fake_root / "imagededup").mkdir(parents=True)
    (fake_root / "litellm").mkdir(parents=True)

    (fake_root / "imagededup" / "__init__.py").write_text(
        _mark_source(_sentinel(fake_root, "imagededup")), encoding="utf-8"
    )
    (fake_root / "imagededup" / "methods.py").write_text(
        "class PHash:\n"
        "    def encode_image(self, image_path):\n"
        '        return "0123456789abcdef"\n',
        encoding="utf-8",
    )
    (fake_root / "litellm" / "__init__.py").write_text(
        _mark_source(_sentinel(fake_root, "litellm")) + "def completion(**kwargs):\n"
        '    raise RuntimeError("fake litellm must not be called")\n',
        encoding="utf-8",
    )
    (fake_root / "litellm" / "exceptions.py").write_text(
        "class Timeout(Exception):\n    pass\n\nclass APIConnectionError(Exception):\n    pass\n",
        encoding="utf-8",
    )
    (fake_root / "face_recognition.py").write_text(
        _mark_source(_sentinel(fake_root, "face_recognition"))
        + "def face_locations(image, model='hog'):\n"
        "    return []\n",
        encoding="utf-8",
    )
    return fake_root


def _loaded_names(tmp_path: Path) -> list[str]:
    """返回已被导入的假包名（按 HEAVY_MODULES 顺序，稳定可断言）。"""
    present = {p.name[len("loaded_") : -len(".txt")] for p in tmp_path.glob("loaded_*.txt")}
    return [name for name in HEAVY_MODULES if name in present]


def _run_child(code: str, fake_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """以 fake_root 优先的 PYTHONPATH 跑子进程代码（cwd 为仓库根，flashgaze 就地可导）。"""
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(fake_root) + (os.pathsep + existing if existing else "")
    return subprocess.run(
        [sys.executable, "-c", code, *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )


# 只导入被测模块——worker 冷启动的等价物。
_IMPORT_ONLY_CODE = """
import flashgaze.core.hybrid_scorer

print("CHILD_OK")
"""

# 正向对照：证明三个假包确实可导入、且导入必然落哨兵（否则「没有哨兵」什么都测不到）。
_DIRECT_IMPORT_CODE = """
import imagededup.methods
import litellm
import litellm.exceptions
import face_recognition

print("CHILD_OK")
"""

# 阶段 1 worker 函数本体：人像依赖只应在 enable_portrait 时被加载。
_WORKER_CODE = """
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

from flashgaze.core.hybrid_scorer import _evaluate_cv_and_portrait

enable_portrait = sys.argv[1] == "portrait=on"
path = Path(tempfile.mkdtemp()) / "frame.png"
array = np.zeros((24, 32, 3), dtype=np.uint8)
array[:, :, 1] = 180
assert cv2.imwrite(str(path), array), "合成图写入失败"

img_path, cv_result, portrait, phash = _evaluate_cv_and_portrait(
    str(path), False, False, False, enable_portrait
)
assert img_path == str(path)
assert portrait.face_count == 0, portrait
assert phash is None, phash

print("CHILD_OK")
"""

# 主进程装配：构造 HybridScorer 仍必须把两个可选引擎装上（覆盖率与对外属性的来源）。
_CONSTRUCT_CODE = """
from flashgaze.core.cv_engine import CVEngine
from flashgaze.core.hybrid_scorer import HybridScorer
from flashgaze.models.schemas import Config

config = Config(
    directory=".",
    top=30,
    no_vlm=True,
    weights={"sharpness": 0.5, "exposure": 0.5},
)
scorer = HybridScorer(CVEngine(), None, config)
assert type(scorer.portrait_engine).__name__ == "PortraitEngine"
assert type(scorer.deduplicator).__name__ == "Deduplicator"

print("CHILD_OK")
"""


def _require_child_ok(result: subprocess.CompletedProcess[str]) -> None:
    """子进程必须走完全程；否则后面所有「有没有落哨兵」的判定都失去意义。"""
    assert CHILD_OK in result.stdout, (
        f"子进程未走完全程：exit={result.returncode} stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )


def test_importing_hybrid_scorer_does_not_pull_heavy_optional_deps(tmp_path: Path) -> None:
    """`import flashgaze.core.hybrid_scorer` 不得连带加载任何重可选依赖。

    这是 worker 冷启动的等价物：spawn 子进程只做这一件事，然后逐任务执行。
    修复前三个哨兵全部落下（模块级导入 `deduplicator`/`vlm_client`/`portrait_engine`），
    本用例判红。
    """
    fake_root = _install_heavy_fakes(tmp_path)
    result = _run_child(_IMPORT_ONLY_CODE, fake_root)

    _require_child_ok(result)
    assert _loaded_names(tmp_path) == [], (
        f"worker 的导入闭包仍被重可选依赖污染：{_loaded_names(tmp_path)}；"
        "改回模块级导入会让 extras 腿每个 spawn worker 重付一遍 import（见本文件首段）"
    )


def test_heavy_fake_harness_is_not_vacuous(tmp_path: Path) -> None:
    """非空洞性凭证：同一假包环境被直接导入时，三个哨兵必然全部落盘。

    没有这条，`_loaded_names() == []` 既可以解释成「代码没导入它们」（我们要的结论），
    也可以解释成「假包根本没生效 / PYTHONPATH 没生效」（用例已失效）。与主用例互为反向，
    二者不可能同时恒真。
    """
    fake_root = _install_heavy_fakes(tmp_path)
    result = _run_child(_DIRECT_IMPORT_CODE, fake_root)

    _require_child_ok(result)
    assert _loaded_names(tmp_path) == list(HEAVY_MODULES), (
        f"假包注入失效，只测到 {_loaded_names(tmp_path)}——主用例的绿不可信"
    )


def test_portrait_dependency_follows_the_enable_portrait_switch(tmp_path: Path) -> None:
    """人像依赖按开关注入：关闭时不加载，开启时**必须**加载。

    两个方向都要钉：
    - 关闭不加载 → 默认（纯 CV）批量的 worker 不再付 dlib 的 import 成本。
    - 开启必须加载 → 堵住「为了变快干脆永不人像」这种拿删功能换绿的假绿。
    同时 `_evaluate_cv_and_portrait` 的返回值在两侧都保持 `face_count=0`（合成图无人脸），
    证明开关只影响加载时机，不影响结果契约。
    """
    fake_root = _install_heavy_fakes(tmp_path)

    off = _run_child(_WORKER_CODE, fake_root, "portrait=off")
    _require_child_ok(off)
    assert _loaded_names(tmp_path) == [], (
        f"人像关闭时仍加载了重依赖：{_loaded_names(tmp_path)}——worker 税没消掉"
    )

    on_root = _install_heavy_fakes(tmp_path / "on")
    on = _run_child(_WORKER_CODE, on_root, "portrait=on")
    _require_child_ok(on)
    assert _loaded_names(tmp_path / "on") == ["face_recognition"], (
        f"人像开启必须加载 face_recognition（且只它一个）；实测 {_loaded_names(tmp_path / 'on')}"
    )


def test_scorer_construction_still_probes_optional_engines(tmp_path: Path) -> None:
    """主进程构造 HybridScorer 仍照旧导入两个可选引擎，且始终不碰 litellm。

    本用例守的是「改按需导入不能顺手把装配点也搬走」：
    - `deduplicator` / `portrait_engine` 的模块级探测与 `__init__` 是 extras 覆盖率
      （`.coveragerc-extras` 的 deduplicator/portrait_engine 两项）的真实来源之一，
      构造点一旦被 `config.dedup` / `config.enable_portrait` 条件化，这两个数字会静默下移。
    - `vlm_client` 只以类型注解形态出现在 hybrid_scorer，构造 HybridScorer 不应当加载
      litellm（VLMClient 的真实构造点在 `flashgaze/core/factory.py`）。
    """
    fake_root = _install_heavy_fakes(tmp_path)
    result = _run_child(_CONSTRUCT_CODE, fake_root)

    _require_child_ok(result)
    assert _loaded_names(tmp_path) == ["imagededup", "face_recognition"], (
        f"装配点加载集合异常：{_loaded_names(tmp_path)}——"
        "dedup/portrait 的探测须在构造期照常发生，litellm 不应被 hybrid_scorer 拖入"
    )
