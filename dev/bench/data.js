window.BENCHMARK_DATA = {
  "lastUpdate": 1792735541921,
  "repoUrl": "https://github.com/QianQianLuLu1/FlashGaze",
  "entries": {
    "Benchmark": [
      {
        "commit": {
          "author": {
            "email": "init@flashgaze.local",
            "name": "FlashGaze Init"
          },
          "committer": {
            "email": "init@flashgaze.local",
            "name": "FlashGaze Init"
          },
          "distinct": true,
          "id": "c202ed2742c7c93b7b1daa6a020ac84436fd28bc",
          "message": "docs: 归档 11 份一次性修复计划并订正其失效引用\n\n- docs/plans/ 已完成计划移出仓库，引用改由 docs/extras-governance.md §2.1 承载\n- cv_engine.py BRISQUE 完整性说明、mcp_server.py 降采样与清理护栏 docstring 对齐代码\n- pyproject numpy 注释与 CHANGELOG 的 PEP 695 解锁门槛统一为 3.12+",
          "timestamp": "2026-10-23T11:44:55+08:00",
          "tree_id": "1ee10786e1604e2fef941117353e4cf295451257",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/c202ed2742c7c93b7b1daa6a020ac84436fd28bc"
        },
        "date": 1792727824940,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 15.388236749663992,
            "unit": "iter/sec",
            "range": "stddev: 0.0015950150200866597",
            "extra": "mean: 64.98470333333255 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 17.174917598341423,
            "unit": "iter/sec",
            "range": "stddev: 0.0025250445266190484",
            "extra": "mean: 58.224442374999796 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 237.10593475265634,
            "unit": "iter/sec",
            "range": "stddev: 0.00008841455052263122",
            "extra": "mean: 4.217524124999983 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 3059.8533603959986,
            "unit": "iter/sec",
            "range": "stddev: 0.00000849365738343304",
            "extra": "mean: 326.81304697248055 usec\nrounds: 1767"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 23.070699063731613,
            "unit": "iter/sec",
            "range": "stddev: 0.0013163503993363862",
            "extra": "mean: 43.34502379999634 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 49.8142492400663,
            "unit": "iter/sec",
            "range": "stddev: 0.00012056751305552252",
            "extra": "mean: 20.074577359999353 msec\nrounds: 50"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 106.9139778935995,
            "unit": "iter/sec",
            "range": "stddev: 0.00008681703815529584",
            "extra": "mean: 9.353313941748546 msec\nrounds: 103"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 1934.4518721061556,
            "unit": "iter/sec",
            "range": "stddev: 0.000010773424875038696",
            "extra": "mean: 516.9422999969697 usec\nrounds: 10"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "init@flashgaze.local",
            "name": "FlashGaze Init"
          },
          "committer": {
            "email": "init@flashgaze.local",
            "name": "FlashGaze Init"
          },
          "distinct": true,
          "id": "e837d508db8fc0eff03dc966ddddc07c157f5be7",
          "message": "ci: 逐腿产出 junit 与失败摘要,对齐 Codecov flag 名并钉死 coverage 引擎\n\n12 腿覆盖率产物复核的落地:coverage-* 只含 coverage.xml,某条腿为何红读不出来。\n- ci.yml test job 补 --junitxml,junit-<os>-py<ver> 单独成产物(不塞进 coverage-*,\n  保住跨腿比对前提),逐腿把 FAILED/ERROR 写进 job summary 并发 ::error:: 注解;\n  junit 缺失或损坏时只发 ::notice:: 且以 0 退出,绝不因缺产物判红(真门禁是 pytest 退出码)\n- extras job 投递 Codecov 的 flag 由 extras-${{ matrix.os }} 改为 fromJSON 查表,\n  与 codecov.yml 声明的 extras-ubuntu / extras-macos 对齐(此前永不相交,\n  carryforward/informational 全程落空)\n- requirements-dev.txt 钉死 coverage[toml]==7.16.2,消除 12 腿双测量引擎\n- 契约测试 test_coverage_gate_contract.py 由 8 条增至 11 条,双向钉住 flag 对齐与钉版\n- 新增假池 _FakeProc + __procs__,使「terminate 未生效→升级 kill」由 1/12 腿计时偶然\n  变为确定性覆盖;补 atomic_write 两处 OSError 兜底与 image_io._is_junction lstat 竞态用例\n- 口径同步:AGENTS.md §3.7/§4.6/§7、docs/agent-context/{pitfalls,fixes}.md、\n  docs/extras-governance.md §3、CHANGELOG、README 中英双语覆盖率门禁段",
          "timestamp": "2026-10-23T14:02:16+08:00",
          "tree_id": "f8128ef3257c5044a5ea382121535187fb528822",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/e837d508db8fc0eff03dc966ddddc07c157f5be7"
        },
        "date": 1792735541401,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 12.325310852865458,
            "unit": "iter/sec",
            "range": "stddev: 0.008368334746520831",
            "extra": "mean: 81.13385633332844 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 16.85803411792449,
            "unit": "iter/sec",
            "range": "stddev: 0.00018710944171135502",
            "extra": "mean: 59.31889762500475 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 207.2052786582564,
            "unit": "iter/sec",
            "range": "stddev: 0.000027048318427112958",
            "extra": "mean: 4.826131874995809 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 2383.3806967446935,
            "unit": "iter/sec",
            "range": "stddev: 0.000017679391222327217",
            "extra": "mean: 419.572081525136 usec\nrounds: 1521"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 25.520900463937924,
            "unit": "iter/sec",
            "range": "stddev: 0.0017584238577008178",
            "extra": "mean: 39.183570399995915 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 46.4736105669232,
            "unit": "iter/sec",
            "range": "stddev: 0.0003839924088934541",
            "extra": "mean: 21.517587891303908 msec\nrounds: 46"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 96.78468080842661,
            "unit": "iter/sec",
            "range": "stddev: 0.00011121616499156765",
            "extra": "mean: 10.332213648349754 msec\nrounds: 91"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 1483.1483204614465,
            "unit": "iter/sec",
            "range": "stddev: 0.000014737018050872181",
            "extra": "mean: 674.2414000029839 usec\nrounds: 10"
          }
        ]
      }
    ]
  }
}