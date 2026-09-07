"""批量评分端到端吞吐基准（HybridScorer）。

经 factory.make_scorer 以 no-VLM 配置装配，走 score_batch 完整链路：
目录扫描 → 进程池 CV 评分（每 worker 单例引擎）→ 加权合分 → 排序。
rounds=3：每轮都重新拉起进程池，轮内开销真实反映用户体感吞吐；
同一 runner 上基线与 head 各跑一轮，池启动开销在对比中自然抵消。

- quick：20 张 512x384 小图，PR 门禁每次运行（秒级）；
- bench_full：100 张 2000x1500 大图，对齐 docs/bench 历史口径（约 4-5s/轮，
  仅 nightly 运行，见 pyproject marker 注释）。
"""

from __future__ import annotations

import pytest
from pytest_benchmark.fixture import BenchmarkFixture

from flashgaze.core.factory import make_scorer
from flashgaze.core.hybrid_scorer import HybridScorer
from flashgaze.models.schemas import Config

BENCH_WORKERS = 4  # 与 DEFAULT_WORKERS 一致：默认配置的吞吐才有代表性


def _bench_config(directory: str, top: int) -> Config:
    """构造基准用 Config：no-VLM、构图/色彩全开，与单图基准同一引擎配置。"""
    return Config(
        directory=directory,
        no_vlm=True,
        enable_composition=True,
        enable_color=True,
        workers=BENCH_WORKERS,
        top=top,
    )


def test_score_batch_small_20(benchmark: BenchmarkFixture, batch_small_dir: str) -> None:
    """quick 批量吞吐：20 张小图、4 workers（PR 门禁运行集）。"""
    scorer = make_scorer(_bench_config(batch_small_dir, top=20))
    results = benchmark.pedantic(
        scorer.score_batch, args=(batch_small_dir,), rounds=3, warmup_rounds=1
    )
    assert len(results) == 20
    assert all(r.error is None for r in results)


@pytest.mark.bench_full
def test_score_batch_full_100_2000x1500(benchmark: BenchmarkFixture, batch_full_dir: str) -> None:
    """full 批量吞吐：100 张大图、4 workers（nightly 运行，历史口径对齐）。"""
    scorer: HybridScorer = make_scorer(_bench_config(batch_full_dir, top=100))
    results = benchmark.pedantic(
        scorer.score_batch, args=(batch_full_dir,), rounds=3, warmup_rounds=1
    )
    assert len(results) == 100
    assert all(r.error is None for r in results)
