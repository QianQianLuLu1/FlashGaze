"""探针：验证「每 worker 只建一次 CVEngine」。

worker 内回报 (pid, id(engine))，同一 pid 的 id 应恒定，不同 pid 数 == worker 数。
不修改任何源码。样本图由同目录的 make_images.py 生成。
"""

import os
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from flashgaze.core import hybrid_scorer as hs

# FIX(#15-3): 本探针刻意访问 hybrid_scorer 的私有 API（下划线函数），
# 用于验证「每 worker 只建一次引擎」的白盒语义。若内部改名/签名变化，
# 给出明确提示而非裸 AttributeError，避免静默失效难以排查。
for _priv in ("_get_cv_engine", "_init_cv_engine"):
    if not hasattr(hs, _priv):
        sys.exit(
            f"探针依赖的私有 API {_priv} 已不存在：hybrid_scorer 内部结构可能已变更，"
            f"请同步更新 tools/bench/probe_count.py 后再运行。"
        )

ARGS = (False, True, False, True)  # composition, noise, color, downscale


def probe(img_path: str) -> tuple[int, int, float | None]:
    """worker 内对单图评分，回报 (pid, engine 对象 id, noise 分)。"""
    engine = hs._get_cv_engine(*ARGS)
    cv = engine.evaluate(img_path)
    return os.getpid(), id(engine), cv.noise


if __name__ == "__main__":
    images_dir = Path(__file__).resolve().parent / "images"
    paths = sorted(str(p) for p in images_dir.glob("*.jpg"))
    if not paths:
        sys.exit(f"{images_dir} 下没有样本图，请先运行 make_images.py")

    by_pid = defaultdict(set)
    noises = 0
    with ProcessPoolExecutor(max_workers=4, initializer=hs._init_cv_engine, initargs=ARGS) as pool:
        futs = [pool.submit(probe, p) for p in paths]
        for f in as_completed(futs):
            pid, eid, noise = f.result()
            by_pid[pid].add(eid)
            if noise is not None:
                noises += 1

    print(f"图片数: {len(paths)}  有效 noise 数: {noises}")
    print(f"worker 进程数: {len(by_pid)}")
    for pid, ids in by_pid.items():
        print(f"  pid={pid}  不同 engine id 数={len(ids)}")
    total_engines = sum(len(v) for v in by_pid.values())
    print(f"CVEngine 实例化总次数: {total_engines}（改动前应为 {len(paths)}）")
    assert total_engines == len(by_pid), "存在 worker 内重复构造引擎"
