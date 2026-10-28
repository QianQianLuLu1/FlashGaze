# 性能基准（自动化基准测试与趋势跟踪）

基准套件位于顶层 `benchmarks/` 目录，基于 [pytest-benchmark](https://pytest-benchmark.readthedocs.io/)，
由 `.github/workflows/benchmark.yml` 驱动：**PR 上回归超阈值自动失败并输出对比报告**，
main/nightly 运行累积趋势数据并在 gh-pages 渲染趋势图。

## 基准清单

| 基准 | 目标 | 覆盖路径 | 运行集 |
|---|---|---|---|
| `test_evaluate_2000x1500` | 大图完整单图评分（构图+色彩，含解码） | `cv_engine.evaluate` | quick |
| `test_evaluate_512x384` | 小图完整单图评分（无降采样分支） | `cv_engine.evaluate` | quick |
| `test_compute_sharpness_inmemory` | 纯 CV 计算（注入预解码数组，无磁盘 IO） | `cv_engine.compute_sharpness` | quick |
| `test_decode_bgr_jpeg_2000x1500` | Pillow JPEG 解码 | `image_io.decode_bgr` | quick |
| `test_downscale_inter_area_3840` | 4K→2048 INTER_AREA 降采样 | `image_io.downscale_if_needed` | quick |
| `test_encode_bgr_b64_2000x1500` | VLM base64 编码 | `image_io.encode_bgr_b64` | quick |
| `test_iter_images_scan` | 目录扫描（os.walk+过滤+排序） | `image_io.iter_images` | quick |
| `test_score_batch_small_20` | 批量端到端吞吐（进程池，20 小图） | `hybrid_scorer.score_batch` | quick |
| `test_score_batch_full_100_2000x1500` | 全量批量吞吐（100 大图，历史口径） | `hybrid_scorer.score_batch` | bench_full |

- **quick**：每次 PR / main push 运行（全套 < 1 分钟）
- **bench_full**：仅 nightly 定时任务（`-m 'not bench_full'` 跳过）
- BRISQUE 噪点维度不进基准：依赖 opencv-contrib extras 与模型文件，不属于跨环境稳定基线
- **quick 语料**（large/small/batch_small）仍由 `benchmarks/conftest.py` 在 pytest
  临时目录按固定种子现场生成（小图，秒级，不缓存）。
- **bench_full 语料**（100 张 2000×1500 大图）复用 `tools/bench/images/`，该目录
  由 `tools/bench/make_images.py` 按固定种子生成、在 `benchmark.yml` 中经
  `actions/cache` 缓存；`conftest.batch_full_dir` 优先读取该目录，缺失时兜底现场
  生成。缓存 key 基于 `make_images.py` 内容哈希——脚本不变即命中复用，变更即失效重生成。
  本地 `pytest benchmarks/` 无缓存时也能自动重建，无需手动预生成。

## CI 行为（benchmark workflow）

| 触发 | 行为 |
|---|---|
| `pull_request` | **同机自对比门禁**：同一 runner 先跑 merge-base 基线再跑 head，`mean` 超基线 **15%** 即 `PerformanceRegression` → job 失败；对比表（含 FAIL 标记与 delta）写入 Job Summary，github-action-benchmark 在 PR 发对比评论、超 15% 追加告警评论 |
| `push` 到 main | 跑 quick 集，结果自动推送到 gh-pages `dev/bench/` 累积趋势 |
| nightly（UTC 18:00） | 跑全量（含 bench_full），推送趋势数据 |
| `workflow_dispatch` | 手动触发，`full` 输入可包含 bench_full |

- **阈值调整**：`benchmark.yml` 顶部 `BENCH_FAIL_THRESHOLD`（单一调整点）
- **为什么同机自对比**：GitHub 托管 runner 每次可能分配不同物理机，跨机噪声
  可达 10-20%，会淹没 15% 阈值；同一 runner 上两次运行噪声 <5%
- **趋势图**：数据在 gh-pages 分支 `dev/bench/` 下，图表页面为
  `https://<org>.github.io/FlashGaze/dev/bench/`（需在仓库 Settings → Pages
  启用 gh-pages 分支；未启用时数据仍正常累积，只是没有网页视图）
- 基准环境固定 ubuntu-latest + Python 3.12 单腿：跨 OS/版本对比没有意义
- **测量引擎钉死单版本**：`requirements-dev.txt` 钉 `pytest==9.1.1` 与
  `pytest-benchmark==5.3.0`。区间式会让 nightly 在无人改代码时换掉引擎——
  pytest 9.2.0（2026-10-27 发布）删私有 `_nodeid` 而 pytest-benchmark 仍读它，
  `benchmark` fixture 构造即抛 `AttributeError`，step 8 因此 1 秒判 rc=1
  （CI run 40590781626，见 pitfalls §3.14 / fixes §4.12）。抬钉前须先在一次性 venv
  用合成探针复跑，并覆盖 3.10/3.11/3.12/3.13 四条腿

## 本地运行

```bash
pip install -r requirements-dev.txt          # 含钉版的 pytest / pytest-benchmark

# 跑 quick 集（.benchmarks/ 目录会留 autosave 历史，已 gitignore）
python -m pytest benchmarks/ -m "not bench_full" --benchmark-autosave

# 跑全量（含 bench_full；首次/缺失时 100 张 2000x1500 语料生成约 10-20 秒，
# 之后复用 tools/bench/images/，也可手动 `python tools/bench/make_images.py` 预生成）
python -m pytest benchmarks/

# 与最近一次保存的结果对比（CI 门禁的同款机制）
python -m pytest benchmarks/ -m "not bench_full" --benchmark-compare

# 与指定历史文件对比 + 阈值失败（同机两遍才可比；跨机对比仅供参考）
python -m pytest benchmarks/ --benchmark-compare=.benchmarks/0001_xxx.json \
    --benchmark-compare-fail=mean:15%
```

注意：本地（尤其 Windows）与 CI（ubuntu）的绝对耗时不可直接对比；趋势与
门禁均只使用 CI 同环境数据。`pytest tests/` 不会收集 `benchmarks/`。

## 附录：hybrid_scorer 并行重构基准（2026-08，手动）

> 以下为自动化基准上线前的手动测量记录，方法论已被 `benchmarks/` 取代。

`flashgaze/core/hybrid_scorer.py` 的 CVEngine 复用重构（每 worker 只构造一次引擎，
而非每张图构造一次）前后对比。原始逐图明细已丢弃，此处只保留汇总。

### 采集环境

| 项 | 值 |
|---|---|
| 平台 | Windows，本地开发机 |
| 采集时间 | 2026-08-10 |
| 样本 | 100 张固定种子生成图，见 `tools/bench/make_images.py` |
| 大图场景 | 2000×1500，JPEG q90 |
| 小图场景 | 256×256 |
| 命令 | `python -m flashgaze <dir> --no-vlm --enable-noise --workers N --top 100 --json` |
| 取值 | 每组 3 次运行，下表为落盘 JSON 中的 `summary.elapsed_ms` |

### 结果

#### 大图（2000×1500）

| workers | before | after | 变化 |
|---|---|---|---|
| 1 | 13456 ms | 12612 ms | −6.3% |
| 4 | 4505 ms | 4468 ms | −0.8% |

#### 小图（256×256）

| workers | before | after | 变化 |
|---|---|---|---|
| 1 | 1543 ms | 1027 ms | −33.4% |
| 4 | 721 ms | 588 ms | −18.4% |

### 结论

- `avg_score` 在所有 4 组中前后完全一致（大图 65.59、小图 90.61），重构行为等价。
- 收益与单张图的处理耗时成反比：小图场景下引擎构造开销占比高，提速明显；
  大图场景下像素计算占主导，提速有限。
- 引擎复用的正确性由 `tools/bench/probe_count.py` 单独验证
  （同一 worker 进程内 engine id 恒定）。

### 复现

```bash
python tools/bench/make_images.py     # 生成样本图到 tools/bench/images/（已 gitignore）
python tools/bench/probe_count.py     # 验证每 worker 只建一次 CVEngine
```

> 原 `bench.sh` / `bench_small.sh` 未纳入版本控制：它们在运行中会用 `.bak` 副本
> 覆盖 `flashgaze/core/hybrid_scorer.py`，且硬编码了本机 Python 路径，属一次性产物。
