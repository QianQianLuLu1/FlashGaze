"""生成 100 张拟真尺寸基准图（固定种子，可复现）。

输出到本文件同级的 images/，该目录已 gitignore。

核心逻辑封装为可导入的 ``generate()``，供 benchmarks/conftest.py 复用，
避免生成算法在脚本与基准套件间重复维护。benchmark.yml 中该 images/
目录会被 actions/cache 缓存，脚本内容（哈希）即缓存失效依据。
"""

from pathlib import Path

import cv2
import numpy as np

COUNT = 100
WIDTH, HEIGHT = 2000, 1500
SEED = 42


def generate(out_dir: Path) -> Path:
    """生成 100 张拟真基准图（固定种子，可复现）到 out_dir，返回该目录。

    幂等：out_dir 已存在时直接覆盖写同名文件，可重复运行。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    for i in range(COUNT):
        base = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        base[:, :, 0] = np.linspace(0, 255, WIDTH, dtype=np.uint8)[None, :]
        base[:, :, 1] = np.linspace(0, 255, HEIGHT, dtype=np.uint8)[:, None]
        base[:, :, 2] = (i * 2) % 256
        img = cv2.add(base, rng.integers(0, 40, (HEIGHT, WIDTH, 3), dtype=np.uint8))
        cv2.imwrite(
            str(out_dir / f"img_{i:03d}.jpg"),
            img,
            [int(cv2.IMWRITE_JPEG_QUALITY), 90],
        )
    print("generated", len(list(out_dir.glob("*.jpg"))))
    return out_dir


if __name__ == "__main__":
    generate(Path(__file__).parent / "images")
