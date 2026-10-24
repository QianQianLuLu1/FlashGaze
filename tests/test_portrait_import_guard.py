"""可选依赖的 import 守卫必须挡住 `SystemExit`（CI run 39986414762 extras 两腿的回归用例）。

上游 `face_recognition` 在 `face_recognition_models` 导入失败时（Python 3.12 的 venv 不再
自带 setuptools，`pkg_resources` 因此缺失）打印安装提示后直接调用 `quit()`，抛出的是
`SystemExit`——它继承自 `BaseException`，**不是 `ImportError`**。只 `except ImportError` 的
守卫拦不住它，异常会沿 `portrait_engine → hybrid_scorer → factory → cleanup` 一路上抛，
在 pytest 收集阶段打死整个 session（CI run 39986414762 的 extras 两腿即为此，exit code 3，
覆盖率数据根本没生成，门禁于是报 `No data to report.`）。

本文件用子进程复现，而不是在本进程里改 `sys.modules`：`flashgaze.core.cleanup` 等模块
在会话早期已被其他测试导入，就地 purge 再重导会产生第二份模块对象并污染
`tests/test_portrait.py` 的双向 skipif 判定。子进程隔离保证状态零泄漏。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# 上游 face_recognition 那句安装提示的前缀，用作「假模块确实被执行了」的非空洞性凭证。
UPSTREAM_HINT = "Please install `face_recognition_models`"

# 子进程的成功标记：只有整条导入链不被打死才会打印。
IMPORT_CHAIN_OK = "IMPORT_CHAIN_OK"

# 导入链走通后的断言集合（在子进程里执行，失败即非零退出）。
_CHAIN_CODE = f"""
import flashgaze.core.portrait_engine as portrait_engine

assert portrait_engine._FACE_RECOGNITION_AVAILABLE is False, "探测标志应为 False"
assert portrait_engine.PortraitEngine(enable=True).enable is False, "enable=True 须降级"

# CI 真实崩溃入口链：tests/test_cleanup.py -> cleanup -> factory -> hybrid_scorer -> portrait_engine
import flashgaze.core.cleanup

print({IMPORT_CHAIN_OK!r})
"""

# 反面：不经我们的守卫、直接 import 那个会 quit() 的包，用于钉住「退出码 0 不可作判据」。
_BARE_CODE = f"""
import face_recognition  # noqa: F401  —— 上游 import 期即 quit()

print({IMPORT_CHAIN_OK!r})
"""


def _install_broken_face_recognition(tmp_path: Path) -> Path:
    """在 tmp_path 造一个「import 即 print 提示 + quit()」的假 face_recognition。"""
    pkg_dir = tmp_path / "broken_pkg"
    pkg_dir.mkdir(exist_ok=True)
    (pkg_dir / "face_recognition.py").write_text(
        f"print({UPSTREAM_HINT!r})\nraise SystemExit\n",
        encoding="utf-8",
    )
    return pkg_dir


def _run_child(code: str, pkg_dir: Path) -> subprocess.CompletedProcess[str]:
    """以 pkg_dir 优先的 PYTHONPATH 跑一段子进程代码（cwd 为仓库根，`-c` 会把 cwd 置于 sys.path[0]）。"""
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(pkg_dir) + (os.pathsep + existing if existing else "")
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        # check=False 是用例语义本身：修复前的子进程退出码同样是 0（`quit()` 抛
        # SystemExit(None)），必须由「成功标记是否出现」来判定，不能让 returncode 抛错。
        check=False,
        timeout=180,
    )


def test_broken_face_recognition_does_not_kill_the_import_chain(tmp_path: Path) -> None:
    """缺陷修复主用例：第三方包 import 期 quit() 不得打死我们的导入链。

    修复前失效证据：子进程在 `import flashgaze.core.portrait_engine` 处被 SystemExit 终止，
    走不到 `import flashgaze.core.cleanup`，因此 IMPORT_CHAIN_OK 不出现。
    """
    result = _run_child(_CHAIN_CODE, _install_broken_face_recognition(tmp_path))

    # 非空洞性：假模块确实被执行了，否则本用例等于什么都没测。
    assert UPSTREAM_HINT in result.stdout, (
        f"注入的 face_recognition 未被导入，用例已失效："
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert IMPORT_CHAIN_OK in result.stdout, (
        f"导入链被可选依赖的 quit() 打死（CI INTERNALERROR 复现）："
        f"exit={result.returncode} stderr={result.stderr!r}"
    )
    assert result.returncode == 0, (
        f"子进程异常退出：exit={result.returncode} stderr={result.stderr!r}"
    )


def test_exit_code_alone_cannot_detect_the_killed_chain(tmp_path: Path) -> None:
    """反例护栏：`quit()` 抛 SystemExit(None)，解释器按退出码 **0** 收尾。

    这钉住了两件事：① 产品侧危害是真的——用户会拿到「退出码 0 + stdout 只有 pip 提示 +
    没有任何 JSON」，直接违反 CLI「stdout 只输出 JSON」契约；② 主用例不能简化成
    「returncode == 0 即通过」，因为被杀死的链路 rc 也是 0，唯一可信的判据是成功标记缺席。
    """
    pkg_dir = _install_broken_face_recognition(tmp_path)
    result = _run_child(_BARE_CODE, pkg_dir)

    assert result.returncode == 0, (
        f"预期 quit() 的退出码是 0（这正是本缺陷的隐蔽之处），实际 {result.returncode}："
        f"stderr={result.stderr!r}"
    )
    assert IMPORT_CHAIN_OK not in result.stdout, "裸 import 应被 quit() 打断，标记不该出现"
    assert UPSTREAM_HINT in result.stdout
