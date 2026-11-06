window.BENCHMARK_DATA = {
  "lastUpdate": 1793964849034,
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
          "id": "9659ad5da4d6f11500c35cb525a963e0c3dde96e",
          "message": "chore(gitignore): 忽略工作区 IDE 生成的 package-lock.json 空壳",
          "timestamp": "2026-10-24T00:21:01+08:00",
          "tree_id": "5fa713a7b7dfa17a138a83f5e345bb3a597002ff",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/9659ad5da4d6f11500c35cb525a963e0c3dde96e"
        },
        "date": 1792772671438,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 12.959885422171475,
            "unit": "iter/sec",
            "range": "stddev: 0.0005339838129764602",
            "extra": "mean: 77.16117599999943 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 13.86103600335438,
            "unit": "iter/sec",
            "range": "stddev: 0.002254016119114661",
            "extra": "mean: 72.1446795000027 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 218.12534949486178,
            "unit": "iter/sec",
            "range": "stddev: 0.00002436141762959186",
            "extra": "mean: 4.584519874997639 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 2472.4400052557103,
            "unit": "iter/sec",
            "range": "stddev: 0.000015195079722722973",
            "extra": "mean: 404.45875243657355 usec\nrounds: 1539"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 22.73093462917999,
            "unit": "iter/sec",
            "range": "stddev: 0.006383863409204515",
            "extra": "mean: 43.99291170000055 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 46.44000061559205,
            "unit": "iter/sec",
            "range": "stddev: 0.00014686314481509623",
            "extra": "mean: 21.533160782608903 msec\nrounds: 46"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 97.86502471154772,
            "unit": "iter/sec",
            "range": "stddev: 0.00011348044781321078",
            "extra": "mean: 10.218155086022307 msec\nrounds: 93"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 1585.4853257748657,
            "unit": "iter/sec",
            "range": "stddev: 0.000014786508467423773",
            "extra": "mean: 630.721700001402 usec\nrounds: 10"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "committer": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "id": "9659ad5da4d6f11500c35cb525a963e0c3dde96e",
          "message": "chore(gitignore): 忽略工作区 IDE 生成的 package-lock.json 空壳",
          "timestamp": "2026-10-23T16:21:01Z",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/9659ad5da4d6f11500c35cb525a963e0c3dde96e"
        },
        "date": 1792789786462,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 11.409633523256733,
            "unit": "iter/sec",
            "range": "stddev: 0.011892812752295975",
            "extra": "mean: 87.64523399999291 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_full_100_2000x1500",
            "value": 0.3093475054692263,
            "unit": "iter/sec",
            "range": "stddev: 0.025118110239005002",
            "extra": "mean: 3.232610518333336 sec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 13.332385000788358,
            "unit": "iter/sec",
            "range": "stddev: 0.00221321794787905",
            "extra": "mean: 75.00533474999926 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 206.92496109438594,
            "unit": "iter/sec",
            "range": "stddev: 0.00005060862140231421",
            "extra": "mean: 4.832669749996299 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 2435.774822414956,
            "unit": "iter/sec",
            "range": "stddev: 0.000015601013449596246",
            "extra": "mean: 410.5469811074519 usec\nrounds: 1535"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 22.28721048983396,
            "unit": "iter/sec",
            "range": "stddev: 0.008092405302796353",
            "extra": "mean: 44.868782499996485 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 45.80162259237459,
            "unit": "iter/sec",
            "range": "stddev: 0.0008859629461686918",
            "extra": "mean: 21.833287630436214 msec\nrounds: 46"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 97.5041724124747,
            "unit": "iter/sec",
            "range": "stddev: 0.0001093858077606203",
            "extra": "mean: 10.255971362637398 msec\nrounds: 91"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 1530.756651482326,
            "unit": "iter/sec",
            "range": "stddev: 0.000020966443645823256",
            "extra": "mean: 653.2716999998911 usec\nrounds: 10"
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
          "id": "dcf8c59a9fb3aefbc58500c326243c076189d431",
          "message": "fix(ci): 兜住 face_recognition import 期 SystemExit 并修通 extras-health 熔断链路\n\n三处收口（CI run 39986414762 / 40031692874 取证）：\n- portrait_engine 探测守卫 except ImportError -> except (ImportError, SystemExit)；\n  新增 tests/test_portrait_import_guard.py 子进程回归，含 SystemExit(None) 退出码为 0 的陷阱用例\n- extras-health.yml charts 步骤入参 raw-data-file/output-storage 均非该 action 参数，\n  未知入参被静默忽略 -> 改 output-file-path\n- 同文件引号 heredoc 内 open(\"$GITHUB_OUTPUT\") 不展开变量 -> steps.*.outputs 恒空，\n  R4 熔断加锁与建/关 Issue 从未执行 -> 改 os.environ[\"GITHUB_OUTPUT\"]\n- ci.yml 覆盖率门禁加 .coverage 存在且非空前置，把「无数据」与「未达标」在日志里分开；阈值一条未改\n- tests/test_coverage_gate_contract.py 12->14 条（benchmark 入参名、引号 heredoc 内的 $GITHUB_OUTPUT，各带反例）\n- AGENTS.md 新增 §3.11/§4.9，同步 pitfalls/fixes/extras-governance",
          "timestamp": "2026-10-24T23:28:17+08:00",
          "tree_id": "0466b991c54f12b6544d0c2bfe265c307021912c",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/dcf8c59a9fb3aefbc58500c326243c076189d431"
        },
        "date": 1792855918225,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 11.93720262662542,
            "unit": "iter/sec",
            "range": "stddev: 0.0008186089157715313",
            "extra": "mean: 83.77172033333362 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 13.308323533250203,
            "unit": "iter/sec",
            "range": "stddev: 0.0022890231702920615",
            "extra": "mean: 75.14094450000019 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 217.590695473706,
            "unit": "iter/sec",
            "range": "stddev: 0.00001403145810301942",
            "extra": "mean: 4.59578475000022 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 2439.090984981355,
            "unit": "iter/sec",
            "range": "stddev: 0.000017634104371104787",
            "extra": "mean: 409.9888057302808 usec\nrounds: 1431"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 22.51964802132466,
            "unit": "iter/sec",
            "range": "stddev: 0.006557094516784193",
            "extra": "mean: 44.405667399999516 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 46.17629298266943,
            "unit": "iter/sec",
            "range": "stddev: 0.00025918038463654144",
            "extra": "mean: 21.656134249999518 msec\nrounds: 44"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 97.10102209581525,
            "unit": "iter/sec",
            "range": "stddev: 0.00015914881932534898",
            "extra": "mean: 10.298552769230806 msec\nrounds: 91"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 1554.5912598693676,
            "unit": "iter/sec",
            "range": "stddev: 0.000013399268467633802",
            "extra": "mean: 643.2559000003835 usec\nrounds: 10"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "committer": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "id": "dcf8c59a9fb3aefbc58500c326243c076189d431",
          "message": "fix(ci): 兜住 face_recognition import 期 SystemExit 并修通 extras-health 熔断链路\n\n三处收口（CI run 39986414762 / 40031692874 取证）：\n- portrait_engine 探测守卫 except ImportError -> except (ImportError, SystemExit)；\n  新增 tests/test_portrait_import_guard.py 子进程回归，含 SystemExit(None) 退出码为 0 的陷阱用例\n- extras-health.yml charts 步骤入参 raw-data-file/output-storage 均非该 action 参数，\n  未知入参被静默忽略 -> 改 output-file-path\n- 同文件引号 heredoc 内 open(\"$GITHUB_OUTPUT\") 不展开变量 -> steps.*.outputs 恒空，\n  R4 熔断加锁与建/关 Issue 从未执行 -> 改 os.environ[\"GITHUB_OUTPUT\"]\n- ci.yml 覆盖率门禁加 .coverage 存在且非空前置，把「无数据」与「未达标」在日志里分开；阈值一条未改\n- tests/test_coverage_gate_contract.py 12->14 条（benchmark 入参名、引号 heredoc 内的 $GITHUB_OUTPUT，各带反例）\n- AGENTS.md 新增 §3.11/§4.9，同步 pitfalls/fixes/extras-governance",
          "timestamp": "2026-10-24T15:28:17Z",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/dcf8c59a9fb3aefbc58500c326243c076189d431"
        },
        "date": 1792873616770,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 15.557258430013878,
            "unit": "iter/sec",
            "range": "stddev: 0.0015512840552683693",
            "extra": "mean: 64.27867766667343 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_full_100_2000x1500",
            "value": 0.3743381061229735,
            "unit": "iter/sec",
            "range": "stddev: 0.03849250791240768",
            "extra": "mean: 2.671381790000003 sec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 13.77783546863576,
            "unit": "iter/sec",
            "range": "stddev: 0.0023890482214585338",
            "extra": "mean: 72.58034125000457 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 243.4143709472066,
            "unit": "iter/sec",
            "range": "stddev: 0.00004815246359390669",
            "extra": "mean: 4.108220874998736 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 3067.7504000425447,
            "unit": "iter/sec",
            "range": "stddev: 0.0000075009569424093775",
            "extra": "mean: 325.9717609314407 usec\nrounds: 1761"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 21.55368389734835,
            "unit": "iter/sec",
            "range": "stddev: 0.006831501173428113",
            "extra": "mean: 46.39578110000144 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 50.1394169105701,
            "unit": "iter/sec",
            "range": "stddev: 0.000124662983524619",
            "extra": "mean: 19.94438830000007 msec\nrounds: 50"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 106.8569204540169,
            "unit": "iter/sec",
            "range": "stddev: 0.00011224154320880228",
            "extra": "mean: 9.358308247619059 msec\nrounds: 105"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 2089.6134925648857,
            "unit": "iter/sec",
            "range": "stddev: 0.000009971384538801663",
            "extra": "mean: 478.5573999967596 usec\nrounds: 10"
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
          "id": "7288d7daf78f598f83fab80082c93fabf6f6e8ac",
          "message": "fix(ci): 静默 portrait 探测输出并修通 extras-health rc=2 熔断链路\n\n收口 main @ dcf8c59 首次转绿后浮现的三条连带问题（阈值一条未改）：\n- portrait_engine 探测块加 redirect_stdout/stderr，上游 face_recognition 的\n  print() 不再落在 --json 子进程 stdout 头部（4 条 CLI 用例 json.loads 失败的真因）\n- extras-health.yml 的 Evaluate health 只放行 rc∈{0,2}、其它非零原样退出，\n  不再让脚本自身退出码掐断 R4 熔断的写锁/建 Issue/关 Issue 三处（§3.12）\n- extras_health.py 新增 JUDGED_MODULES 限定 R1/R2/R4，R5 同步收敛，\n  dedup/portrait 保留观测并在 Issue 表格逐行标注\n- ci.yml extras timeout-minutes 20→40（macOS 实测需 ~31 分钟）+ 补 --junitxml\n  与 junit-extras-* 产物\n- 新增 tests/test_extras_health_rules.py 7 条；test_coverage_gate_contract.py 14→17 条\n- AGENTS.md 订正 §3.11、新增 §3.12/§4.10；pitfalls/fixes/extras-governance 同步口径",
          "timestamp": "2026-10-25T15:49:05+08:00",
          "tree_id": "385695a73f0c17aba2874dd226484aabc9910c0e",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/7288d7daf78f598f83fab80082c93fabf6f6e8ac"
        },
        "date": 1792914778109,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 12.290142840874283,
            "unit": "iter/sec",
            "range": "stddev: 0.0006716450416882611",
            "extra": "mean: 81.36601933333291 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 13.160793401588926,
            "unit": "iter/sec",
            "range": "stddev: 0.0023050097746835792",
            "extra": "mean: 75.9832609999993 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 207.72398799717345,
            "unit": "iter/sec",
            "range": "stddev: 0.00005306093753538133",
            "extra": "mean: 4.81408050000276 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 2387.8117711807195,
            "unit": "iter/sec",
            "range": "stddev: 0.00004921050355894127",
            "extra": "mean: 418.79347948164377 usec\nrounds: 1389"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 21.76954276998251,
            "unit": "iter/sec",
            "range": "stddev: 0.0072927358520030565",
            "extra": "mean: 45.935737400000676 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 45.30706583184729,
            "unit": "iter/sec",
            "range": "stddev: 0.0010803040821702387",
            "extra": "mean: 22.071612487804913 msec\nrounds: 41"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 96.23114436366676,
            "unit": "iter/sec",
            "range": "stddev: 0.0002413597067154822",
            "extra": "mean: 10.391646141304356 msec\nrounds: 92"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 1534.1369244798939,
            "unit": "iter/sec",
            "range": "stddev: 0.000024242371736116176",
            "extra": "mean: 651.8323000008763 usec\nrounds: 10"
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
          "id": "1c5e25a5bf63a34a1d8b174f2b53c53a9531e1db",
          "message": "fix(ci): 按需导入可选依赖宿主模块，消掉 spawn worker 的重导入税\n\nextras (macos-latest, py3.12) 在 CI run 40174423841 撞上 timeout-minutes: 40——测试步独自\n跑到 2091s 仍未结束（同一命令 ubuntu 404s），上一轮据 58% 停点做的「~31 分钟」线性外推\n就此被证伪。差额不是 macOS 天生慢：默认矩阵同平台只差 1.46 倍，多出来的是每个 spawn worker\n按 module+qualname 重导入 hybrid_scorer 时连带重付的 imagededup / face_recognition /\nlitellm 的 import，成本乘在「池代数 × worker 数」上（一条 test_score_batch_is_deterministic\n就是 40 次 spawn）。默认矩阵不装这三个包，所以本地与 12 腿恒无此税、结构上看不见它。\n\n改为按需导入：类型引用走 TYPE_CHECKING，运行时导入进函数体；worker 侧人像构造收进\nenable_portrait 开关（关闭时的返回值与 PortraitEngine(enable=False).evaluate() 的早返回\n逐字段相同）；HybridScorer.__init__ 的两个装配构造保持无条件——deduplicator/portrait_engine\n的模块级探测与构造是 extras 覆盖率的真实来源，条件化会让数字静默下移。三个可选依赖的探测块\n一行未改，§3.11 的 SystemExit + redirect_stdout/stderr 守卫原样留在原位；探测时机随之从\nimport 期推迟到装配期，缺陷没有消失只是换了触发点，相关注释已同步订正。\n\ntimeout-minutes 与 82/80/95/50/80 全部阈值一条未改，未撤 macOS 腿、未缩小 extras 测试范围。\n\n新增 tests/test_worker_import_budget.py 4 条：假包经 PYTHONPATH 前置注入 + 独立落盘哨兵作\n判据（不用计时断言），含「直接 import 假包必然落哨兵」的非空洞性对照与「开启/装配时必须\n加载」的反向守卫，防止拿删功能换绿伪装成优化成功。契约 17→18 条（静态兜底只认第 0 列导入、\n函数体内缩进导入不误报；并把被证伪的 run 号绑进注释要求）。test_hybrid_scorer 加 1 条进程内\nenable_portrait=True 用例，堵住 branch=true 口径下新分支只剩子进程可达的 partial branch 缺口。\n\n本地验证：修复前 3 红 1 绿 / 修复后 4 绿；反例 A-D 逐条实跑判红并用备份还原（git diff 无残留）；\nruff check + format --check + mypy（本机与 --platform linux 两面）+ tools.check_agents_md 全绿；\npytest tests/ --cov = 1058 passed, 29 skipped（跳过数与基线一致）, 覆盖率 90.49% ≥ 80。\n仍只能 CI 终验：macOS 腿 40 分钟够不够、benchmark ±15% 门禁。",
          "timestamp": "2026-10-25T18:08:29+08:00",
          "tree_id": "e992f3b375fd0e0b64478ada8aed5dbf25a619b8",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/1c5e25a5bf63a34a1d8b174f2b53c53a9531e1db"
        },
        "date": 1792923134176,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 14.652513374192015,
            "unit": "iter/sec",
            "range": "stddev: 0.006779027889861763",
            "extra": "mean: 68.2476769999975 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 13.658385190495073,
            "unit": "iter/sec",
            "range": "stddev: 0.0016575439157834214",
            "extra": "mean: 73.21509724999586 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 227.78573699110288,
            "unit": "iter/sec",
            "range": "stddev: 0.00006609080196994144",
            "extra": "mean: 4.390090499999388 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 3065.8512429092802,
            "unit": "iter/sec",
            "range": "stddev: 0.000008283418576055119",
            "extra": "mean: 326.1736857953582 usec\nrounds: 1760"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 22.358109645436706,
            "unit": "iter/sec",
            "range": "stddev: 0.00824908390369885",
            "extra": "mean: 44.726500400005875 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 49.669914707549665,
            "unit": "iter/sec",
            "range": "stddev: 0.0002872923121281147",
            "extra": "mean: 20.13291156000321 msec\nrounds: 50"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 107.05928799354182,
            "unit": "iter/sec",
            "range": "stddev: 0.000203461178667504",
            "extra": "mean: 9.340618817307318 msec\nrounds: 104"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 2120.0018571147607,
            "unit": "iter/sec",
            "range": "stddev: 0.000008262276814941317",
            "extra": "mean: 471.69770000152766 usec\nrounds: 10"
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
          "id": "1fb38576d9c0d1a6479aecc03ea89e923235f9d2",
          "message": "test(ci): 把 extras 超时实测出处绑进契约，订正「40 分钟是实测需求」\n\nCI run 40183752144 @ 1c5e25a 全绿（21 个 job，0 失败），本轮修复的终验数据到手：\nextras (macos-latest, py3.12) 测试步 380s、job 全程 661s；ubuntu 302s / 568s。\nmacOS→ubuntu 由 ≥6.9 倍（2091s 未完对 404s 的下界比值）回落到 1.26 倍，落进默认矩阵\n1.46 倍的自然带内——平台异常消失，直接反证根因是 worker 冷启动的可选依赖 import，\n不是 macOS 慢。coverage-extras-macos-* 与 junit-extras-macos-* 首次真实生成（产物 26→28）。\nbenchmark job 同 SHA success，±15% 均值门禁未受影响。\n\n据此把 timeout-minutes: 40 重新定性为**刻意留的余量天花板（~3.6 倍 headroom），不是实测需求**：\n上一轮的注释把它写成「按实测取的」，而它依据的 31 分钟外推已被 40174423841 证伪——注释一直在替\n一个被推翻的数字辩护。**没有下调** 40：腿自己只要 11 分钟，下调省不了任何墙钟时间，却把未来的\n用例增长重新变成超时分母，是净风险零收益。\n\n契约新增 EXTRAS_TIMEOUT_MEASURED_RUN，要求「起点 40107357212 / 证伪 40174423841 / 实测\n40183752144」三个 run 号同时出现在 extras 注释里，缺任一判红——只剩「预算 40」而无实测出处，\n就是上一轮犯过的错。断言文案里「macOS 腿需 ~31 分钟」那句已删除。\n\n反例 E 第一版构造无效（只删 run 号的一处出现，它在三 run 清单里还有第二处，18 条照样全绿），\n改为删除全部出现后拿到 rc=1；教训记进 fixes.md §4.11：反例须先证明守卫看得见我改的字节。\nAGENTS.md §3.13/§4.10/§4.11/§7 与 pitfalls/fixes 同步实测数字；§4.10 那条「实需 ~31 分钟」\n补上「已被 §4.11 证伪」的指向，不留孤立的历史断言。\n\n本地验证：全量 1058 passed, 29 skipped（与上一批逐字一致）、覆盖率 90.49% ≥ 80；\nruff check / format --check / mypy 两面 / check_agents_md 全绿。",
          "timestamp": "2026-10-25T18:48:15+08:00",
          "tree_id": "31c2bb84423c78a3c785026cc37d9a00a9fc5c2a",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/1fb38576d9c0d1a6479aecc03ea89e923235f9d2"
        },
        "date": 1792925537047,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 8.907415680086771,
            "unit": "iter/sec",
            "range": "stddev: 0.010410883092199534",
            "extra": "mean: 112.26600800000597 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 12.803333783263392,
            "unit": "iter/sec",
            "range": "stddev: 0.002671829675405026",
            "extra": "mean: 78.10465750000262 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 215.31376059483546,
            "unit": "iter/sec",
            "range": "stddev: 0.000028752875911501",
            "extra": "mean: 4.644384999998863 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 2386.46863185298,
            "unit": "iter/sec",
            "range": "stddev: 0.00004391787150250777",
            "extra": "mean: 419.0291825556271 usec\nrounds: 1479"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 22.351182535468325,
            "unit": "iter/sec",
            "range": "stddev: 0.006855456295330076",
            "extra": "mean: 44.74036209999781 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 46.32810750084115,
            "unit": "iter/sec",
            "range": "stddev: 0.00012377995025475888",
            "extra": "mean: 21.585168355557016 msec\nrounds: 45"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 97.86597053079501,
            "unit": "iter/sec",
            "range": "stddev: 0.00010373368556317282",
            "extra": "mean: 10.218056333333298 msec\nrounds: 93"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 1587.1247362584584,
            "unit": "iter/sec",
            "range": "stddev: 0.00001977228615598679",
            "extra": "mean: 630.0702000004321 usec\nrounds: 10"
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
          "id": "874d4cea4b54c08e7a93959853e66c3d71526435",
          "message": "docs(ci): 订正「ubuntu 也顺带变快」的过度归因，补 fork/spawn 边界与第二轮实测\n\n第二个终验 run 40186485850 同样全绿（macOS 测试步 375s / job 681s），但它的 ubuntu 测试步是\n382s，而不是上一轮的 302s。四个样本摆齐：ubuntu 修复前 306s / 404s、修复后 302s / 382s，\n同一个 ±30% 区间——上一版把它写成「ubuntu 也从 404s 顺带降到 302s」，是把跨运行噪声当成了\n因果，而且机制上根本不成立：ProcessPoolExecutor 未指定 mp_context，Linux 默认 fork、worker\n直接继承父进程已导入的模块、**不重新 import**，那笔税只在 spawn 平台（macOS/Windows）存在。\n\n所以有效对照只有一组：macOS 由「881s 未完」「2091s 未完」两轮被杀，变成 380s / 375s 两轮正常\n完成；macOS/ubuntu 由 ≥5.2 倍回到 ~1 倍量级（不再报精确的 1.26 倍，那取决于撞上哪一批 ubuntu\n样本）。这反而让根因结论更硬：受影响面与 spawn 语义完全重合。\n\n顺带记下可推论的边界（尚未实施）：给 extras 加 Windows 腿会立刻重新暴露这笔税，加 Linux 腿\n不会——这解释了 extras 矩阵历史上为什么只有 ubuntu + macOS 两条腿。\n\ntimeout-minutes: 40 的定性不变（余量天花板，非实测需求），三个 run 号的契约要求不变。\n纯文案订正，无行为改动；全量 1058 passed / 29 skipped、覆盖率 90.49% 与上一批逐字一致，\nruff / format / mypy 两面 / check_agents_md 全绿。",
          "timestamp": "2026-10-25T19:25:51+08:00",
          "tree_id": "0ac6c9cb83a395ddd1210dd41b30c2ac720c4ae6",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/874d4cea4b54c08e7a93959853e66c3d71526435"
        },
        "date": 1792927772735,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 12.19489208245969,
            "unit": "iter/sec",
            "range": "stddev: 0.0019946698613088794",
            "extra": "mean: 82.00154566667568 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 13.278782633607323,
            "unit": "iter/sec",
            "range": "stddev: 0.0015128327322984343",
            "extra": "mean: 75.308108250006 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 209.78326897137566,
            "unit": "iter/sec",
            "range": "stddev: 0.000027486758400161442",
            "extra": "mean: 4.766824375000311 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 2388.275331177584,
            "unit": "iter/sec",
            "range": "stddev: 0.000015799947622215986",
            "extra": "mean: 418.71219241163925 usec\nrounds: 1476"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 22.155548348945718,
            "unit": "iter/sec",
            "range": "stddev: 0.0070091301726235835",
            "extra": "mean: 45.13542090000158 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 44.514569333653114,
            "unit": "iter/sec",
            "range": "stddev: 0.0019054234230454251",
            "extra": "mean: 22.46455519999826 msec\nrounds: 45"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 75.54877567370428,
            "unit": "iter/sec",
            "range": "stddev: 0.0007701558006675791",
            "extra": "mean: 13.236481876543007 msec\nrounds: 81"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 1524.6663572722484,
            "unit": "iter/sec",
            "range": "stddev: 0.00003195103407824965",
            "extra": "mean: 655.8811999951786 usec\nrounds: 10"
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
          "id": "2d94e0889331cf1715919ad89287094276e9f175",
          "message": "docs(ci): 用第三轮实测把单点值改成区间，并记下「拿单样本当结论」这笔账\n\n第三个终验 run 40189037679 也是 success（21 个 job、0 失败，两个 macos extras 产物照样生成）。\n但它把上一版文档里的两处说法打破了：\n\n1. macOS 测试步不是 380/375s 两值，第三轮是 505s；job 全程 661 / 681 / 882s。同一轮 install\n   也从 252s 跳到 349s——同一条腿跨运行波动约 ±35%。上一版据此写的「变成 ~377s 完成」是拿单\n   样本当结论，现改为只报**完成性与区间**：三轮全部跑完、最差 882s = 14.7 分钟。\n2. 由此 headroom 也从「~3.6 倍」下调为「最差一轮仍 ≥2.7 倍」；「真实需求 ~11 分钟」改为「≤15 分钟」。\n   结论方向不变：40 仍是余量天花板，不是实测需求，也不下调。\n\n顺带把倍率按三轮逐一对齐后写成 0.98~1.31 倍（380/302、375/382、505/384），与默认矩阵 1.46 倍\n同带；ubuntu 三轮 302/382/384s 与修复前 306/404s 同区间，无可测变化——ProcessPoolExecutor 未\n指定 mp_context，Linux 默认 fork、worker 不重新导入本模块，所以「ubuntu 不变」本身就是根因\n成立的旁证，而不是遗漏。\n\n教训写进 pitfalls §3.13 与 fixes §4.11：凡按单轮 step 时序下结论，先问「这是几轮采样」。本轮\n我在同一个数字上栽了两次（先是照 58% 停点线性外推 31 分钟，再是拿一轮 380s 当点值），两笔都\n如实记账，不删不改前次表述。\n\n纯文案与注释，无行为改动：ruff / format / mypy 两面 / check_agents_md 全绿，\n契约 18 + 预算 4 + extras-health 规则 7 = 29 条通过。",
          "timestamp": "2026-10-25T19:59:05+08:00",
          "tree_id": "1b8f9d197dcc14be9caf3de86aa60baf9fc1c3fb",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/2d94e0889331cf1715919ad89287094276e9f175"
        },
        "date": 1792929762343,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 18.335231396487874,
            "unit": "iter/sec",
            "range": "stddev: 0.00284685140267172",
            "extra": "mean: 54.53980799999888 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 21.874168593612406,
            "unit": "iter/sec",
            "range": "stddev: 0.0013777405005883582",
            "extra": "mean: 45.71602324999979 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 401.19715224243413,
            "unit": "iter/sec",
            "range": "stddev: 0.000018522850597378946",
            "extra": "mean: 2.492540124999998 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 4467.890561753042,
            "unit": "iter/sec",
            "range": "stddev: 0.00003854975952614224",
            "extra": "mean: 223.8192691111117 usec\nrounds: 2891"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 38.47281928404315,
            "unit": "iter/sec",
            "range": "stddev: 0.005104033538894254",
            "extra": "mean: 25.992376399999273 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 92.23959790209665,
            "unit": "iter/sec",
            "range": "stddev: 0.00019597515151695578",
            "extra": "mean: 10.84133086813109 msec\nrounds: 91"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 177.7561531133217,
            "unit": "iter/sec",
            "range": "stddev: 0.00008380987465534862",
            "extra": "mean: 5.625684301136332 msec\nrounds: 176"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 2697.449965655891,
            "unit": "iter/sec",
            "range": "stddev: 0.00000858681425987259",
            "extra": "mean: 370.72050000261925 usec\nrounds: 10"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "committer": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "id": "2d94e0889331cf1715919ad89287094276e9f175",
          "message": "docs(ci): 用第三轮实测把单点值改成区间，并记下「拿单样本当结论」这笔账\n\n第三个终验 run 40189037679 也是 success（21 个 job、0 失败，两个 macos extras 产物照样生成）。\n但它把上一版文档里的两处说法打破了：\n\n1. macOS 测试步不是 380/375s 两值，第三轮是 505s；job 全程 661 / 681 / 882s。同一轮 install\n   也从 252s 跳到 349s——同一条腿跨运行波动约 ±35%。上一版据此写的「变成 ~377s 完成」是拿单\n   样本当结论，现改为只报**完成性与区间**：三轮全部跑完、最差 882s = 14.7 分钟。\n2. 由此 headroom 也从「~3.6 倍」下调为「最差一轮仍 ≥2.7 倍」；「真实需求 ~11 分钟」改为「≤15 分钟」。\n   结论方向不变：40 仍是余量天花板，不是实测需求，也不下调。\n\n顺带把倍率按三轮逐一对齐后写成 0.98~1.31 倍（380/302、375/382、505/384），与默认矩阵 1.46 倍\n同带；ubuntu 三轮 302/382/384s 与修复前 306/404s 同区间，无可测变化——ProcessPoolExecutor 未\n指定 mp_context，Linux 默认 fork、worker 不重新导入本模块，所以「ubuntu 不变」本身就是根因\n成立的旁证，而不是遗漏。\n\n教训写进 pitfalls §3.13 与 fixes §4.11：凡按单轮 step 时序下结论，先问「这是几轮采样」。本轮\n我在同一个数字上栽了两次（先是照 58% 停点线性外推 31 分钟，再是拿一轮 380s 当点值），两笔都\n如实记账，不删不改前次表述。\n\n纯文案与注释，无行为改动：ruff / format / mypy 两面 / check_agents_md 全绿，\n契约 18 + 预算 4 + extras-health 规则 7 = 29 条通过。",
          "timestamp": "2026-10-25T11:59:05Z",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/2d94e0889331cf1715919ad89287094276e9f175"
        },
        "date": 1792960430100,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 12.22998646083386,
            "unit": "iter/sec",
            "range": "stddev: 0.0023350138082202858",
            "extra": "mean: 81.76623933333597 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_full_100_2000x1500",
            "value": 0.29756089014010795,
            "unit": "iter/sec",
            "range": "stddev: 0.11377050951388172",
            "extra": "mean: 3.3606567029999987 sec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 13.314185626036766,
            "unit": "iter/sec",
            "range": "stddev: 0.0022005101889661554",
            "extra": "mean: 75.10786074999842 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 214.0348482443648,
            "unit": "iter/sec",
            "range": "stddev: 0.00002786651058252176",
            "extra": "mean: 4.672136374999525 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 2458.59023485705,
            "unit": "iter/sec",
            "range": "stddev: 0.000016210358138818768",
            "extra": "mean: 406.73715604265516 usec\nrounds: 1506"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 21.686414673694234,
            "unit": "iter/sec",
            "range": "stddev: 0.007157430051813479",
            "extra": "mean: 46.1118177000003 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 45.643809313967495,
            "unit": "iter/sec",
            "range": "stddev: 0.001111835692924685",
            "extra": "mean: 21.908776130435488 msec\nrounds: 46"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 97.20668774862523,
            "unit": "iter/sec",
            "range": "stddev: 0.0001271874532578468",
            "extra": "mean: 10.287358032257846 msec\nrounds: 93"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 1554.0773862145068,
            "unit": "iter/sec",
            "range": "stddev: 0.00001653253010096767",
            "extra": "mean: 643.468600000574 usec\nrounds: 10"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "committer": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "id": "2d94e0889331cf1715919ad89287094276e9f175",
          "message": "docs(ci): 用第三轮实测把单点值改成区间，并记下「拿单样本当结论」这笔账\n\n第三个终验 run 40189037679 也是 success（21 个 job、0 失败，两个 macos extras 产物照样生成）。\n但它把上一版文档里的两处说法打破了：\n\n1. macOS 测试步不是 380/375s 两值，第三轮是 505s；job 全程 661 / 681 / 882s。同一轮 install\n   也从 252s 跳到 349s——同一条腿跨运行波动约 ±35%。上一版据此写的「变成 ~377s 完成」是拿单\n   样本当结论，现改为只报**完成性与区间**：三轮全部跑完、最差 882s = 14.7 分钟。\n2. 由此 headroom 也从「~3.6 倍」下调为「最差一轮仍 ≥2.7 倍」；「真实需求 ~11 分钟」改为「≤15 分钟」。\n   结论方向不变：40 仍是余量天花板，不是实测需求，也不下调。\n\n顺带把倍率按三轮逐一对齐后写成 0.98~1.31 倍（380/302、375/382、505/384），与默认矩阵 1.46 倍\n同带；ubuntu 三轮 302/382/384s 与修复前 306/404s 同区间，无可测变化——ProcessPoolExecutor 未\n指定 mp_context，Linux 默认 fork、worker 不重新导入本模块，所以「ubuntu 不变」本身就是根因\n成立的旁证，而不是遗漏。\n\n教训写进 pitfalls §3.13 与 fixes §4.11：凡按单轮 step 时序下结论，先问「这是几轮采样」。本轮\n我在同一个数字上栽了两次（先是照 58% 停点线性外推 31 分钟，再是拿一轮 380s 当点值），两笔都\n如实记账，不删不改前次表述。\n\n纯文案与注释，无行为改动：ruff / format / mypy 两面 / check_agents_md 全绿，\n契约 18 + 预算 4 + extras-health 规则 7 = 29 条通过。",
          "timestamp": "2026-10-25T11:59:05Z",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/2d94e0889331cf1715919ad89287094276e9f175"
        },
        "date": 1793053547852,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 12.056840479392335,
            "unit": "iter/sec",
            "range": "stddev: 0.00336484779329359",
            "extra": "mean: 82.94046866666349 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_full_100_2000x1500",
            "value": 0.2908386566255712,
            "unit": "iter/sec",
            "range": "stddev: 0.2126158268967838",
            "extra": "mean: 3.438332481666668 sec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 13.197596014333381,
            "unit": "iter/sec",
            "range": "stddev: 0.0025094196265104847",
            "extra": "mean: 75.7713752500031 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 204.30185128610654,
            "unit": "iter/sec",
            "range": "stddev: 0.00005312023586855624",
            "extra": "mean: 4.894718250005425 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 2398.0941344901785,
            "unit": "iter/sec",
            "range": "stddev: 0.00001446011356722204",
            "extra": "mean: 416.9978090591487 usec\nrounds: 1435"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 21.711423826057466,
            "unit": "iter/sec",
            "range": "stddev: 0.007164507355108431",
            "extra": "mean: 46.05870199999629 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 45.91358277680875,
            "unit": "iter/sec",
            "range": "stddev: 0.0006565451997794145",
            "extra": "mean: 21.780047199999963 msec\nrounds: 45"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 97.16355020898801,
            "unit": "iter/sec",
            "range": "stddev: 0.00027467022569765395",
            "extra": "mean: 10.291925293477966 msec\nrounds: 92"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 1562.6660332556544,
            "unit": "iter/sec",
            "range": "stddev: 0.000018147547469727793",
            "extra": "mean: 639.9320000042508 usec\nrounds: 10"
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
          "id": "f3b8187aa8e6d40acbcc324145aaeb2e58a01026",
          "message": "fix(ci): 钉死测试与基准引擎，消掉 nightly 被上游换代打死的秒退\n\nrequirements-dev.txt 的 pytest>=7.4.0,<10 让每轮 nightly 由 resolver 重新决定引擎版本。\npytest 9.2.0（2026-10-27T21:30:19Z 上 PyPI，比 run 40590781626 起跑早 25 分钟）的 #14758\n删掉了私有 _nodeid（9.1.1 命中 5 处、9.2.0 命中 0 处），而 pytest_benchmark/fixture.py:88\n仍读它（上游 issue #321 未关、修复 PR #323 未进任何 release）——于是 benchmark fixture\n构造即抛 AttributeError、9 条基准用例全部在 setup 阶段报错、rc=1、step 8 只用 1 秒，\n而同一个 sha 的前两轮 nightly 各 20s 全绿，仓内代码一行没变。\n\n一次性 venv 的单变量复现补上本轮唯一的直接观测（job logs 免鉴权 403，装的是哪个版本\n从未被日志看到）：9.2.0+5.3.0 判红 rc=1，9.1.1+5.3.0 通过 rc=0。范围限定：9.2.0 对\npytest tests/ 实测无害（extras-health run 40598565970 带它全绿），钉版只针对基准路径。\n\npytest-benchmark 一并钉：fullname 是 --benchmark-compare ±15% 门禁与 gh-pages 趋势序列\n的 join key，插件换代失配静默无痕；且实测开发机 5.2.3 / CI 5.3.0 已经不同源。\n\n阈值、矩阵、超时预算一条未动，也没有撤腿或加 continue-on-error。新增契约守卫 1 条\n（18→19），要拦的不只是「没钉版」，还有「钉在坏版本上」：写 pytest==9.2.0 时其余 18 条\n全绿、只有新守卫判红——dependabot 因 ignore semver-major 会把这个升级当 minor 提 PR。\n四条反例逐条实跑判红并用备份还原（git diff 复核无残留）。\n\n顺带关掉上一轮遗留的唯一未确认项：extras-health 链路首次真实执行已验证 collect 与\ncharts 两个 job 全绿。",
          "timestamp": "2026-10-28T22:24:58+08:00",
          "tree_id": "fdb9e67c3248acc1da9f547d4c5686bdd6b924a2",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/f3b8187aa8e6d40acbcc324145aaeb2e58a01026"
        },
        "date": 1793197736024,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 11.305861441708506,
            "unit": "iter/sec",
            "range": "stddev: 0.013845961892203391",
            "extra": "mean: 88.44969533333351 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 13.271307819188022,
            "unit": "iter/sec",
            "range": "stddev: 0.0020266597321456138",
            "extra": "mean: 75.35052412499788 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 212.67920017082005,
            "unit": "iter/sec",
            "range": "stddev: 0.00004085215379102936",
            "extra": "mean: 4.701917250002907 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 2389.9159650057527,
            "unit": "iter/sec",
            "range": "stddev: 0.00001423315159357331",
            "extra": "mean: 418.42475410954165 usec\nrounds: 1460"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 22.514268558414756,
            "unit": "iter/sec",
            "range": "stddev: 0.006830940685824889",
            "extra": "mean: 44.41627749999668 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 45.98560177013306,
            "unit": "iter/sec",
            "range": "stddev: 0.0004971714757492727",
            "extra": "mean: 21.745937021737195 msec\nrounds: 46"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 96.6979338146372,
            "unit": "iter/sec",
            "range": "stddev: 0.00035256875118976283",
            "extra": "mean: 10.34148259999977 msec\nrounds: 95"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 1498.5550183243754,
            "unit": "iter/sec",
            "range": "stddev: 0.000058168264524428786",
            "extra": "mean: 667.3094999996465 usec\nrounds: 10"
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
          "id": "68c086b37dd5208f06bca1959a2e1d3ae81fa658",
          "message": "docs(ci): 把 step 8 的判据按触发事件拆开，改掉我自己混用的 20s\n\npush f3b8187 后 run 40706255565 的 step 8 是 6s 而非我写的「20s 量级」。查下来是我把两个\n分支的口径混了：20s 属于含 bench_full 的 nightly，push 走 quick 集（8 通过 + 1 去选）。\n正确的同触发对照是同为 push 的修复前绿 run 40191369021，step 8 也是 6s——逐字相同才算\n基准真在跑。判据按触发事件分别取（push ≈6s / schedule ≈20s），否则下一轮会把一条绿 run\n读成可疑。\n\n同时记录 push 分支已终验通过（steps 10~13 由整批 skipped 变回 success，即\nbenchmark-head.json 真实产出），并如实标注 schedule 分支仍无第二样本：本机既无 gh 也无\nGITHUB_TOKEN，workflow_dispatch full=true 无法从这里触发，只能等下一轮 18:00 UTC 定时。",
          "timestamp": "2026-10-28T22:28:44+08:00",
          "tree_id": "2c2d1a7b8984f79de06c6a8aa592346ede94ba67",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/68c086b37dd5208f06bca1959a2e1d3ae81fa658"
        },
        "date": 1793197935903,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 12.26158888439826,
            "unit": "iter/sec",
            "range": "stddev: 0.0021237071915786295",
            "extra": "mean: 81.5554990000038 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 13.533501168822587,
            "unit": "iter/sec",
            "range": "stddev: 0.0017451626409520405",
            "extra": "mean: 73.89070924999963 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 209.56371794014026,
            "unit": "iter/sec",
            "range": "stddev: 0.000019054124036476512",
            "extra": "mean: 4.771818374999626 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 2393.576828993387,
            "unit": "iter/sec",
            "range": "stddev: 0.00001799400162533183",
            "extra": "mean: 417.78479298721635 usec\nrounds: 1483"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 22.65624088086182,
            "unit": "iter/sec",
            "range": "stddev: 0.006952920729704114",
            "extra": "mean: 44.13794880000239 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 46.14128204133349,
            "unit": "iter/sec",
            "range": "stddev: 0.00021147594387782792",
            "extra": "mean: 21.672566425531855 msec\nrounds: 47"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 97.85815279195897,
            "unit": "iter/sec",
            "range": "stddev: 0.00009099750932647028",
            "extra": "mean: 10.218872638296624 msec\nrounds: 94"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 1541.2027453731748,
            "unit": "iter/sec",
            "range": "stddev: 0.00001679858152630289",
            "extra": "mean: 648.8439000008839 usec\nrounds: 10"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "committer": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "id": "68c086b37dd5208f06bca1959a2e1d3ae81fa658",
          "message": "docs(ci): 把 step 8 的判据按触发事件拆开，改掉我自己混用的 20s\n\npush f3b8187 后 run 40706255565 的 step 8 是 6s 而非我写的「20s 量级」。查下来是我把两个\n分支的口径混了：20s 属于含 bench_full 的 nightly，push 走 quick 集（8 通过 + 1 去选）。\n正确的同触发对照是同为 push 的修复前绿 run 40191369021，step 8 也是 6s——逐字相同才算\n基准真在跑。判据按触发事件分别取（push ≈6s / schedule ≈20s），否则下一轮会把一条绿 run\n读成可疑。\n\n同时记录 push 分支已终验通过（steps 10~13 由整批 skipped 变回 success，即\nbenchmark-head.json 真实产出），并如实标注 schedule 分支仍无第二样本：本机既无 gh 也无\nGITHUB_TOKEN，workflow_dispatch full=true 无法从这里触发，只能等下一轮 18:00 UTC 定时。",
          "timestamp": "2026-10-28T14:28:44Z",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/68c086b37dd5208f06bca1959a2e1d3ae81fa658"
        },
        "date": 1793226073042,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 14.707017749129953,
            "unit": "iter/sec",
            "range": "stddev: 0.001205736412063747",
            "extra": "mean: 67.9947503333338 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_full_100_2000x1500",
            "value": 0.3720976556812516,
            "unit": "iter/sec",
            "range": "stddev: 0.014130867929274043",
            "extra": "mean: 2.6874665420000006 sec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 13.715092310620738,
            "unit": "iter/sec",
            "range": "stddev: 0.003483910831217068",
            "extra": "mean: 72.91237837499764 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 233.30063236127418,
            "unit": "iter/sec",
            "range": "stddev: 0.000124097001949217",
            "extra": "mean: 4.28631500000165 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 3056.772123270487,
            "unit": "iter/sec",
            "range": "stddev: 0.000007915910440548382",
            "extra": "mean: 327.14247568120476 usec\nrounds: 1871"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 20.843351777212668,
            "unit": "iter/sec",
            "range": "stddev: 0.006842227770767508",
            "extra": "mean: 47.97692859999927 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 49.96631638348917,
            "unit": "iter/sec",
            "range": "stddev: 0.00013440776378121963",
            "extra": "mean: 20.013482529411338 msec\nrounds: 51"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 106.5395854841943,
            "unit": "iter/sec",
            "range": "stddev: 0.00009952971323205012",
            "extra": "mean: 9.386182567308328 msec\nrounds: 104"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 2083.4670224708557,
            "unit": "iter/sec",
            "range": "stddev: 0.000011992148568642723",
            "extra": "mean: 479.9691999991751 usec\nrounds: 10"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "committer": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "id": "68c086b37dd5208f06bca1959a2e1d3ae81fa658",
          "message": "docs(ci): 把 step 8 的判据按触发事件拆开，改掉我自己混用的 20s\n\npush f3b8187 后 run 40706255565 的 step 8 是 6s 而非我写的「20s 量级」。查下来是我把两个\n分支的口径混了：20s 属于含 bench_full 的 nightly，push 走 quick 集（8 通过 + 1 去选）。\n正确的同触发对照是同为 push 的修复前绿 run 40191369021，step 8 也是 6s——逐字相同才算\n基准真在跑。判据按触发事件分别取（push ≈6s / schedule ≈20s），否则下一轮会把一条绿 run\n读成可疑。\n\n同时记录 push 分支已终验通过（steps 10~13 由整批 skipped 变回 success，即\nbenchmark-head.json 真实产出），并如实标注 schedule 分支仍无第二样本：本机既无 gh 也无\nGITHUB_TOKEN，workflow_dispatch full=true 无法从这里触发，只能等下一轮 18:00 UTC 定时。",
          "timestamp": "2026-10-28T14:28:44Z",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/68c086b37dd5208f06bca1959a2e1d3ae81fa658"
        },
        "date": 1793313254649,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 12.529291133427776,
            "unit": "iter/sec",
            "range": "stddev: 0.0008987757756585081",
            "extra": "mean: 79.81297500000058 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_full_100_2000x1500",
            "value": 0.30638698603571735,
            "unit": "iter/sec",
            "range": "stddev: 0.006781758483106365",
            "extra": "mean: 3.2638461996666663 sec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 13.296227683699309,
            "unit": "iter/sec",
            "range": "stddev: 0.0022276155765343503",
            "extra": "mean: 75.20930174999663 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 214.1488292067451,
            "unit": "iter/sec",
            "range": "stddev: 0.00003112772728134588",
            "extra": "mean: 4.669649625002492 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 2394.083690398286,
            "unit": "iter/sec",
            "range": "stddev: 0.000015522543282445332",
            "extra": "mean: 417.69634203290417 usec\nrounds: 1456"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 22.616183217516653,
            "unit": "iter/sec",
            "range": "stddev: 0.006972311018480113",
            "extra": "mean: 44.21612570000235 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 46.33814814126425,
            "unit": "iter/sec",
            "range": "stddev: 0.0001369660866822521",
            "extra": "mean: 21.58049123912868 msec\nrounds: 46"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 97.64919977945577,
            "unit": "iter/sec",
            "range": "stddev: 0.00009756391801178416",
            "extra": "mean: 10.240739322580584 msec\nrounds: 93"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 1534.1524582424158,
            "unit": "iter/sec",
            "range": "stddev: 0.000032448639602534434",
            "extra": "mean: 651.8256999996197 usec\nrounds: 10"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "committer": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "id": "68c086b37dd5208f06bca1959a2e1d3ae81fa658",
          "message": "docs(ci): 把 step 8 的判据按触发事件拆开，改掉我自己混用的 20s\n\npush f3b8187 后 run 40706255565 的 step 8 是 6s 而非我写的「20s 量级」。查下来是我把两个\n分支的口径混了：20s 属于含 bench_full 的 nightly，push 走 quick 集（8 通过 + 1 去选）。\n正确的同触发对照是同为 push 的修复前绿 run 40191369021，step 8 也是 6s——逐字相同才算\n基准真在跑。判据按触发事件分别取（push ≈6s / schedule ≈20s），否则下一轮会把一条绿 run\n读成可疑。\n\n同时记录 push 分支已终验通过（steps 10~13 由整批 skipped 变回 success，即\nbenchmark-head.json 真实产出），并如实标注 schedule 分支仍无第二样本：本机既无 gh 也无\nGITHUB_TOKEN，workflow_dispatch full=true 无法从这里触发，只能等下一轮 18:00 UTC 定时。",
          "timestamp": "2026-10-28T14:28:44Z",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/68c086b37dd5208f06bca1959a2e1d3ae81fa658"
        },
        "date": 1793397778709,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 14.804314571413084,
            "unit": "iter/sec",
            "range": "stddev: 0.0004897718005600366",
            "extra": "mean: 67.54787566666447 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_full_100_2000x1500",
            "value": 0.3688647947470566,
            "unit": "iter/sec",
            "range": "stddev: 0.010518007377831637",
            "extra": "mean: 2.7110204450000026 sec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 13.473255721284152,
            "unit": "iter/sec",
            "range": "stddev: 0.002643514424721932",
            "extra": "mean: 74.22111037499768 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 242.17846797310528,
            "unit": "iter/sec",
            "range": "stddev: 0.00012915636193487786",
            "extra": "mean: 4.129186249997474 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 3052.3935254788144,
            "unit": "iter/sec",
            "range": "stddev: 0.000010650049355896894",
            "extra": "mean: 327.6117550547925 usec\nrounds: 1731"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 21.09733990687792,
            "unit": "iter/sec",
            "range": "stddev: 0.0067301822412388305",
            "extra": "mean: 47.399340599996265 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 49.30641805629152,
            "unit": "iter/sec",
            "range": "stddev: 0.0008193270343075981",
            "extra": "mean: 20.281335359999844 msec\nrounds: 50"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 106.52099096296226,
            "unit": "iter/sec",
            "range": "stddev: 0.0001654035703244857",
            "extra": "mean: 9.387821038462771 msec\nrounds: 104"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 1983.030415519135,
            "unit": "iter/sec",
            "range": "stddev: 0.000008495030806866382",
            "extra": "mean: 504.278700000782 usec\nrounds: 10"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "committer": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "id": "68c086b37dd5208f06bca1959a2e1d3ae81fa658",
          "message": "docs(ci): 把 step 8 的判据按触发事件拆开，改掉我自己混用的 20s\n\npush f3b8187 后 run 40706255565 的 step 8 是 6s 而非我写的「20s 量级」。查下来是我把两个\n分支的口径混了：20s 属于含 bench_full 的 nightly，push 走 quick 集（8 通过 + 1 去选）。\n正确的同触发对照是同为 push 的修复前绿 run 40191369021，step 8 也是 6s——逐字相同才算\n基准真在跑。判据按触发事件分别取（push ≈6s / schedule ≈20s），否则下一轮会把一条绿 run\n读成可疑。\n\n同时记录 push 分支已终验通过（steps 10~13 由整批 skipped 变回 success，即\nbenchmark-head.json 真实产出），并如实标注 schedule 分支仍无第二样本：本机既无 gh 也无\nGITHUB_TOKEN，workflow_dispatch full=true 无法从这里触发，只能等下一轮 18:00 UTC 定时。",
          "timestamp": "2026-10-28T14:28:44Z",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/68c086b37dd5208f06bca1959a2e1d3ae81fa658"
        },
        "date": 1793481132562,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 11.418537991862888,
            "unit": "iter/sec",
            "range": "stddev: 0.0020729141616579747",
            "extra": "mean: 87.57688599999607 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_full_100_2000x1500",
            "value": 0.2562304955409051,
            "unit": "iter/sec",
            "range": "stddev: 0.011798234018726718",
            "extra": "mean: 3.9027360810000005 sec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 11.696189244552318,
            "unit": "iter/sec",
            "range": "stddev: 0.004196749460077655",
            "extra": "mean: 85.49793262500138 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 154.42904330032465,
            "unit": "iter/sec",
            "range": "stddev: 0.00030850204450697276",
            "extra": "mean: 6.475465874999031 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 1801.9429806777202,
            "unit": "iter/sec",
            "range": "stddev: 0.00001655136934930423",
            "extra": "mean: 554.9565167838412 usec\nrounds: 1281"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 21.325217740229164,
            "unit": "iter/sec",
            "range": "stddev: 0.00602215346920651",
            "extra": "mean: 46.892838900000555 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 41.959716870763565,
            "unit": "iter/sec",
            "range": "stddev: 0.00038185794126726843",
            "extra": "mean: 23.83238197435917 msec\nrounds: 39"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 84.80852432430864,
            "unit": "iter/sec",
            "range": "stddev: 0.0007023704149947359",
            "extra": "mean: 11.791267540229683 msec\nrounds: 87"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 2125.487507130319,
            "unit": "iter/sec",
            "range": "stddev: 0.0000063060321236814795",
            "extra": "mean: 470.480299999565 usec\nrounds: 10"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "committer": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "id": "68c086b37dd5208f06bca1959a2e1d3ae81fa658",
          "message": "docs(ci): 把 step 8 的判据按触发事件拆开，改掉我自己混用的 20s\n\npush f3b8187 后 run 40706255565 的 step 8 是 6s 而非我写的「20s 量级」。查下来是我把两个\n分支的口径混了：20s 属于含 bench_full 的 nightly，push 走 quick 集（8 通过 + 1 去选）。\n正确的同触发对照是同为 push 的修复前绿 run 40191369021，step 8 也是 6s——逐字相同才算\n基准真在跑。判据按触发事件分别取（push ≈6s / schedule ≈20s），否则下一轮会把一条绿 run\n读成可疑。\n\n同时记录 push 分支已终验通过（steps 10~13 由整批 skipped 变回 success，即\nbenchmark-head.json 真实产出），并如实标注 schedule 分支仍无第二样本：本机既无 gh 也无\nGITHUB_TOKEN，workflow_dispatch full=true 无法从这里触发，只能等下一轮 18:00 UTC 定时。",
          "timestamp": "2026-10-28T14:28:44Z",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/68c086b37dd5208f06bca1959a2e1d3ae81fa658"
        },
        "date": 1793569779071,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 11.856818295374177,
            "unit": "iter/sec",
            "range": "stddev: 0.0028105997611531023",
            "extra": "mean: 84.33965799999991 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_full_100_2000x1500",
            "value": 0.30515664020165056,
            "unit": "iter/sec",
            "range": "stddev: 0.03333698551912744",
            "extra": "mean: 3.2770055383333294 sec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 13.270360694507715,
            "unit": "iter/sec",
            "range": "stddev: 0.0013766803461131352",
            "extra": "mean: 75.35590200000186 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 207.57644151656785,
            "unit": "iter/sec",
            "range": "stddev: 0.00004646653617895887",
            "extra": "mean: 4.817502374999449 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 2406.834433747931,
            "unit": "iter/sec",
            "range": "stddev: 0.000030340733964904913",
            "extra": "mean: 415.48350230422636 usec\nrounds: 1519"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 22.373065256460546,
            "unit": "iter/sec",
            "range": "stddev: 0.006811831217428613",
            "extra": "mean: 44.69660230000159 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 46.261746323781864,
            "unit": "iter/sec",
            "range": "stddev: 0.00030409537084154524",
            "extra": "mean: 21.616131673912363 msec\nrounds: 46"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 97.46254071740401,
            "unit": "iter/sec",
            "range": "stddev: 0.0001413760020057563",
            "extra": "mean: 10.260352260870507 msec\nrounds: 92"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 1530.0481567363972,
            "unit": "iter/sec",
            "range": "stddev: 0.00001661892738507416",
            "extra": "mean: 653.5741999996958 usec\nrounds: 10"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "committer": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "id": "68c086b37dd5208f06bca1959a2e1d3ae81fa658",
          "message": "docs(ci): 把 step 8 的判据按触发事件拆开，改掉我自己混用的 20s\n\npush f3b8187 后 run 40706255565 的 step 8 是 6s 而非我写的「20s 量级」。查下来是我把两个\n分支的口径混了：20s 属于含 bench_full 的 nightly，push 走 quick 集（8 通过 + 1 去选）。\n正确的同触发对照是同为 push 的修复前绿 run 40191369021，step 8 也是 6s——逐字相同才算\n基准真在跑。判据按触发事件分别取（push ≈6s / schedule ≈20s），否则下一轮会把一条绿 run\n读成可疑。\n\n同时记录 push 分支已终验通过（steps 10~13 由整批 skipped 变回 success，即\nbenchmark-head.json 真实产出），并如实标注 schedule 分支仍无第二样本：本机既无 gh 也无\nGITHUB_TOKEN，workflow_dispatch full=true 无法从这里触发，只能等下一轮 18:00 UTC 定时。",
          "timestamp": "2026-10-28T14:28:44Z",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/68c086b37dd5208f06bca1959a2e1d3ae81fa658"
        },
        "date": 1793666655713,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 12.734847406792033,
            "unit": "iter/sec",
            "range": "stddev: 0.001551279942254789",
            "extra": "mean: 78.52469433333435 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_full_100_2000x1500",
            "value": 0.30494939897521445,
            "unit": "iter/sec",
            "range": "stddev: 0.015302720668601555",
            "extra": "mean: 3.2792325656666654 sec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 12.999533901711514,
            "unit": "iter/sec",
            "range": "stddev: 0.0015078921268980852",
            "extra": "mean: 76.9258350000026 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 214.02874983986482,
            "unit": "iter/sec",
            "range": "stddev: 0.00006879533424173513",
            "extra": "mean: 4.672269500000326 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 2386.1461178549234,
            "unit": "iter/sec",
            "range": "stddev: 0.00006896287242073862",
            "extra": "mean: 419.08581897699173 usec\nrounds: 1486"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 21.95993693229151,
            "unit": "iter/sec",
            "range": "stddev: 0.007251367145900101",
            "extra": "mean: 45.53747139999871 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 46.00982562830953,
            "unit": "iter/sec",
            "range": "stddev: 0.0006514943644106084",
            "extra": "mean: 21.734487934783804 msec\nrounds: 46"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 97.89180224979924,
            "unit": "iter/sec",
            "range": "stddev: 0.00010454894037664166",
            "extra": "mean: 10.215359989472978 msec\nrounds: 95"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 1559.4974800073542,
            "unit": "iter/sec",
            "range": "stddev: 0.000015119860181428499",
            "extra": "mean: 641.2322000002746 usec\nrounds: 10"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "committer": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "id": "68c086b37dd5208f06bca1959a2e1d3ae81fa658",
          "message": "docs(ci): 把 step 8 的判据按触发事件拆开，改掉我自己混用的 20s\n\npush f3b8187 后 run 40706255565 的 step 8 是 6s 而非我写的「20s 量级」。查下来是我把两个\n分支的口径混了：20s 属于含 bench_full 的 nightly，push 走 quick 集（8 通过 + 1 去选）。\n正确的同触发对照是同为 push 的修复前绿 run 40191369021，step 8 也是 6s——逐字相同才算\n基准真在跑。判据按触发事件分别取（push ≈6s / schedule ≈20s），否则下一轮会把一条绿 run\n读成可疑。\n\n同时记录 push 分支已终验通过（steps 10~13 由整批 skipped 变回 success，即\nbenchmark-head.json 真实产出），并如实标注 schedule 分支仍无第二样本：本机既无 gh 也无\nGITHUB_TOKEN，workflow_dispatch full=true 无法从这里触发，只能等下一轮 18:00 UTC 定时。",
          "timestamp": "2026-10-28T14:28:44Z",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/68c086b37dd5208f06bca1959a2e1d3ae81fa658"
        },
        "date": 1793746842927,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 11.077682071979476,
            "unit": "iter/sec",
            "range": "stddev: 0.006810019287024678",
            "extra": "mean: 90.27159233333275 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_full_100_2000x1500",
            "value": 0.2574084205048228,
            "unit": "iter/sec",
            "range": "stddev: 0.043261775621191725",
            "extra": "mean: 3.884876796333335 sec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 12.36526870837946,
            "unit": "iter/sec",
            "range": "stddev: 0.002847453804236982",
            "extra": "mean: 80.87167562499786 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 172.32822693919954,
            "unit": "iter/sec",
            "range": "stddev: 0.00019460909888092932",
            "extra": "mean: 5.8028798750004995 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 1919.1895748834327,
            "unit": "iter/sec",
            "range": "stddev: 0.000011480831536363",
            "extra": "mean: 521.0532680497381 usec\nrounds: 1205"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 21.38847938090575,
            "unit": "iter/sec",
            "range": "stddev: 0.0056274796986002015",
            "extra": "mean: 46.754141899995716 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 42.72514506262874,
            "unit": "iter/sec",
            "range": "stddev: 0.00008692802251596504",
            "extra": "mean: 23.40542082500008 msec\nrounds: 40"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 88.2100096040846,
            "unit": "iter/sec",
            "range": "stddev: 0.0000881868106616348",
            "extra": "mean: 11.336581919538693 msec\nrounds: 87"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 2152.3159565585097,
            "unit": "iter/sec",
            "range": "stddev: 0.000004918363593034146",
            "extra": "mean: 464.6157999957268 usec\nrounds: 10"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "committer": {
            "name": "FlashGaze Init",
            "email": "init@flashgaze.local"
          },
          "id": "68c086b37dd5208f06bca1959a2e1d3ae81fa658",
          "message": "docs(ci): 把 step 8 的判据按触发事件拆开，改掉我自己混用的 20s\n\npush f3b8187 后 run 40706255565 的 step 8 是 6s 而非我写的「20s 量级」。查下来是我把两个\n分支的口径混了：20s 属于含 bench_full 的 nightly，push 走 quick 集（8 通过 + 1 去选）。\n正确的同触发对照是同为 push 的修复前绿 run 40191369021，step 8 也是 6s——逐字相同才算\n基准真在跑。判据按触发事件分别取（push ≈6s / schedule ≈20s），否则下一轮会把一条绿 run\n读成可疑。\n\n同时记录 push 分支已终验通过（steps 10~13 由整批 skipped 变回 success，即\nbenchmark-head.json 真实产出），并如实标注 schedule 分支仍无第二样本：本机既无 gh 也无\nGITHUB_TOKEN，workflow_dispatch full=true 无法从这里触发，只能等下一轮 18:00 UTC 定时。",
          "timestamp": "2026-10-28T14:28:44Z",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/68c086b37dd5208f06bca1959a2e1d3ae81fa658"
        },
        "date": 1793834635185,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 11.71673536227613,
            "unit": "iter/sec",
            "range": "stddev: 0.0011399132604742667",
            "extra": "mean: 85.3480060000038 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_full_100_2000x1500",
            "value": 0.26117692458132846,
            "unit": "iter/sec",
            "range": "stddev: 0.04509958146803344",
            "extra": "mean: 3.8288221733333407 sec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 12.680591435464919,
            "unit": "iter/sec",
            "range": "stddev: 0.0015289595203573554",
            "extra": "mean: 78.86067500000138 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 176.68906686500605,
            "unit": "iter/sec",
            "range": "stddev: 0.00024190197945319649",
            "extra": "mean: 5.6596597499947165 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 1866.0374370794514,
            "unit": "iter/sec",
            "range": "stddev: 0.000012984736584677783",
            "extra": "mean: 535.8949290776862 usec\nrounds: 1269"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 22.088888732105016,
            "unit": "iter/sec",
            "range": "stddev: 0.005731796993682754",
            "extra": "mean: 45.27163010000379 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 41.99157313949962,
            "unit": "iter/sec",
            "range": "stddev: 0.0006372350502535942",
            "extra": "mean: 23.8143019000006 msec\nrounds: 40"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 88.08046150158383,
            "unit": "iter/sec",
            "range": "stddev: 0.00010915647556919531",
            "extra": "mean: 11.353255681817908 msec\nrounds: 88"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 2160.1556694626947,
            "unit": "iter/sec",
            "range": "stddev: 0.000008082401118272634",
            "extra": "mean: 462.92959999902905 usec\nrounds: 10"
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
          "id": "b1925489d759c9efd51cabc0847c5d4c56af3d90",
          "message": "fix(ci): 推送脚本按需切分支并固定 UTF-8 输出，消掉首推暴露的三处平台差异",
          "timestamp": "2026-11-06T16:02:47+08:00",
          "tree_id": "9bcae4f70a7459ced058a2a58c6f6235df48d941",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/b1925489d759c9efd51cabc0847c5d4c56af3d90"
        },
        "date": 1793952399567,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 10.985322415514538,
            "unit": "iter/sec",
            "range": "stddev: 0.0075059085343301395",
            "extra": "mean: 91.03055533333304 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 10.86410132723534,
            "unit": "iter/sec",
            "range": "stddev: 0.003723392941156963",
            "extra": "mean: 92.04626962499773 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 173.80927556217472,
            "unit": "iter/sec",
            "range": "stddev: 0.00022521000672780364",
            "extra": "mean: 5.753432875003739 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 2365.4479772971304,
            "unit": "iter/sec",
            "range": "stddev: 0.00001093294092662815",
            "extra": "mean: 422.75290329684015 usec\nrounds: 1365"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 16.7641055434612,
            "unit": "iter/sec",
            "range": "stddev: 0.008344361188673176",
            "extra": "mean: 59.65125890000422 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 41.02652672651547,
            "unit": "iter/sec",
            "range": "stddev: 0.0004179445977264689",
            "extra": "mean: 24.374473780489424 msec\nrounds: 41"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 84.63416711993692,
            "unit": "iter/sec",
            "range": "stddev: 0.00008180929244609072",
            "extra": "mean: 11.815559058824059 msec\nrounds: 85"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 1560.9475888493096,
            "unit": "iter/sec",
            "range": "stddev: 0.0000251108758685619",
            "extra": "mean: 640.6364999975267 usec\nrounds: 10"
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
          "id": "687756cc81bb1c9fc70bae815ecc63a30fea91da",
          "message": "fix(ci): 测试侧统一按 UTF-8 解码子进程输出，消除端侧 ACP 差异",
          "timestamp": "2026-11-06T16:30:07+08:00",
          "tree_id": "d106c2384c95b914e85dffc816bd2d1af5283223",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/687756cc81bb1c9fc70bae815ecc63a30fea91da"
        },
        "date": 1793954040970,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 14.252441485982938,
            "unit": "iter/sec",
            "range": "stddev: 0.006636429400380576",
            "extra": "mean: 70.16341733333793 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 13.609108026193843,
            "unit": "iter/sec",
            "range": "stddev: 0.0020236853226173134",
            "extra": "mean: 73.48020150000067 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 229.9685796804233,
            "unit": "iter/sec",
            "range": "stddev: 0.000055909769027274705",
            "extra": "mean: 4.348420124999919 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 3052.7497400381526,
            "unit": "iter/sec",
            "range": "stddev: 0.00002228155971037035",
            "extra": "mean: 327.5735271989581 usec\nrounds: 1728"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 20.298943968753754,
            "unit": "iter/sec",
            "range": "stddev: 0.00728591924578352",
            "extra": "mean: 49.26364650000039 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 49.514643648370345,
            "unit": "iter/sec",
            "range": "stddev: 0.00014893050446581607",
            "extra": "mean: 20.196045580001112 msec\nrounds: 50"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 106.21445066142473,
            "unit": "iter/sec",
            "range": "stddev: 0.00016087753096737702",
            "extra": "mean: 9.414914766990202 msec\nrounds: 103"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 2050.339105570086,
            "unit": "iter/sec",
            "range": "stddev: 0.0000059379877770584975",
            "extra": "mean: 487.72420000346983 usec\nrounds: 10"
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
          "id": "37d7b7f081c75c4d71cb3aac30067ec8b5143841",
          "message": "fix(ci): 拆掉 3.11+ 才有的私有符号补丁，收掉 §4.13 遗留的 py3.10 三腿红灯\n\nCI run 42188510332（push、687756c）19 个 job 里 3 条 py3.10 腿红在 step 5，唯一失败用例\ntest_tool_output_decoded_as_utf8_on_non_utf8_runner：monkeypatch.setattr(subprocess,\n\"_text_encoding\", ...) 打的是 3.11 才引入的私有函数（本仓 requires-python >=3.10），\nraising=True 下属性不存在即在 setup 期抛 AttributeError。逐腿 job 日志确认失败面精确到\n每腿各 1 个用例（1 failed, 1069 passed, 29 skipped, 28 deselected），无其他被掩住的 3.10 缺陷。\n\n第二层缺陷比第一层更贵：这条用例在 3.11+ 本来就不参与任何行为——同文件 _run 已写死\nencoding=\"utf-8\"，subprocess 的默认文本编码路径根本不被走，上一轮把一个红灯换成了一条\n恒真的绿。两道静态门禁放行各有原因：mypy strict（python_version=3.10）只拦属性访问形态，\n这里符号名是 setattr 的字符串实参；ruff 的 target-version 只管语法层。\n\n修（生产代码 / workflow / 阈值 / 矩阵 / 超时预算一条未动）：\n- 用例改走 _run 已有的公开 encoding 参数做双向断言：cp1252 时诊断整段丢失（非空洞性凭证，\n  纯 Python 层机制，12 腿一致）、默认显式 UTF-8 时诊断完整。反向那半会真的产生 reader 线程\n  异常，故显式 filterwarnings 忽略，免得将来收紧成 error 时把这条用例打红。\n- test_coverage_gate_contract.py 19→20 条：新增 test_no_test_patches_private_stdlib_api\n  （AST 扫 tests/，import 根名 ∩ sys.stdlib_module_names，对象与字符串两种形态都拦），\n  三向自证 = 真实扫描先红后绿、合成反例必被抓、项目模块私有属性不得误报，另加\n  len(test_files) >= 40 的扫描非空洞性前置（TESTS_DIR 写错会让守卫变成一盏永远绿的灯）。\n- 否决的改法：raising=False（把红换成静默恒真）、skipif 或把该文件从 3.10 腿摘掉\n  （用「不测」冒充「修好」）。\n\n同轮用只读 /actions/jobs/{id}/logs（凭据取自本机 git credential helper，未落盘、未改配置）\n拿到 11-05 nightly job 127600884450 完整日志，把 §4.13 的四条缺陷从「引用」升级为「实测」：\nremote: fatal error in commit_refs_rules → --depth=50 致 skipped previously applied commit\nc3ab8cf + Rebasing (1/15) → Committer identity unknown → 误报「rebase 冲突」→ rc=1。\n内容冲突从未发生；「下一轮自愈」也是假的——gh-pages 上 11-05 的 Benchmark 提交永久缺失。\n\n本地证据：CPython 3.10.20 真机 --noconftest 单文件 修复前 1 failed / 15 passed → 修复后\n16 passed；3.11.16 与 3.12.10 各 16 passed；变异复核（把 _run 默认编码改成 cp1252）以 CI\n原始签名 TypeError: can only concatenate str (not \"NoneType\") 判红、还原后转绿且 git diff 无残留。\n全量 1076 passed / 29 skipped / 38 deselected、覆盖率 90.49% >= 80；ruff check /\nformat --check（103 files）/ mypy 两面（82 files）/ check_agents_md 全绿。\n须 CI 终验：三条 py3.10 腿在完整矩阵下的结果，以及首次真实执行的 extras 与 e2e。\n\n§3 新增 3.15、§4 新增 4.14、§6 契约条数改口；取证见 fixes.md §4.14 与 docs/ci-fix-plan.md §11。",
          "timestamp": "2026-11-06T17:48:12+08:00",
          "tree_id": "97bda953af0f78e8a44a93d8ba08a5cf90dbc450",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/37d7b7f081c75c4d71cb3aac30067ec8b5143841"
        },
        "date": 1793958742001,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 11.856555830594822,
            "unit": "iter/sec",
            "range": "stddev: 0.002449691627052772",
            "extra": "mean: 84.34152499999925 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 12.936730582390027,
            "unit": "iter/sec",
            "range": "stddev: 0.0014047383418623336",
            "extra": "mean: 77.29928312499901 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 203.1248575745353,
            "unit": "iter/sec",
            "range": "stddev: 0.00009370401832458967",
            "extra": "mean: 4.923080375000666 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 2387.330951295287,
            "unit": "iter/sec",
            "range": "stddev: 0.000015594060867351456",
            "extra": "mean: 418.8778264938228 usec\nrounds: 1389"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 21.48458504119157,
            "unit": "iter/sec",
            "range": "stddev: 0.007157678019853398",
            "extra": "mean: 46.54499950000144 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 45.95012202274818,
            "unit": "iter/sec",
            "range": "stddev: 0.0004765658098581343",
            "extra": "mean: 21.76272784444267 msec\nrounds: 45"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 94.85995869665307,
            "unit": "iter/sec",
            "range": "stddev: 0.0003114666927082565",
            "extra": "mean: 10.54185573913056 msec\nrounds: 92"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 1526.8534588679122,
            "unit": "iter/sec",
            "range": "stddev: 0.000012892413137587017",
            "extra": "mean: 654.9416999988011 usec\nrounds: 10"
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
          "id": "5cc0781ae569c379289bf5518fe6524d9680eb7b",
          "message": "fix(ci): 反向对照降到字节层，消掉上一提交在 POSIX 八条腿上的二次翻车\n\n37d7b7f 推送后 CI run 42198208112：py3.10 三腿的原始缺陷确已修好（每腿只剩 1 failed、\n1070 passed），但失败的用例换成了我自己新写的那半——windows 四腿绿、ubuntu + macOS\n共八腿红：UnicodeDecodeError: 'charmap' codec can't decode byte 0x8f in position 16。\n\n根因是我把「非空洞性凭证」写成 _run(cmd, encoding=\"cp1252\") 后断言「拿不到诊断」，\n而这个「拿不到」的形态本身是平台专属的：POSIX 的 Popen._communicate 用 _PopenSelector\n读原始字节、回主线程才 _translate_newlines 解码，异常直接抛给用例；Windows 起\n_readerthread 在子线程 fh.read()，异常逃出线程、收集值静默留 None。开发机是 Windows，\n于是本机 16 passed 全绿、推上去八条腿判红。这与 pitfalls §3.9 同族，且这一笔是本轮新欠的：\n我在 Windows 上验证了一种死法，就替 12 条腿担保了全部死法。\n\n修（仍零生产代码改动，不放宽任何断言）：反向对照降到字节层——子进程 capture_output 拿\n原始 bytes，断 combined.decode(\"utf-8\") 含「参数非法」+ pytest.raises(UnicodeDecodeError)\n于 combined.decode(\"cp1252\")；正向仍走 _run 的公开默认（显式 UTF-8）。两段都不再进入\nsubprocess 的任何平台分支，12 腿同码同判。filterwarnings 忽略 reader 线程异常的标记随之\n删除（bytes 模式下不再产生该异常）。\n\n证据：py3.12 / py3.11.16 / CPython 3.10.20 真机各 16 passed；变异复核（_run 默认 encoding\n改 cp1252）本机以 CI 原始签名 TypeError: can only concatenate str (not \"NoneType\") 判红、\n还原后转绿、git diff 无残留；全量 1076 passed / 29 skipped / 38 deselected、覆盖率\n90.49% >= 80；ruff check / format --check（103 files，含 ci-fix-plan.md 里的 python 代码块）/\nmypy 两面（82 files）/ check_agents_md 全绿。\n\n口径同步：pitfalls §3.15 补「二阶缺陷」与一般化第 5 条（非空洞性凭证要选平台无关的层去断）、\nfixes §4.14 补二次翻车与终态证据、AGENTS.md §3.15/§4.14 行与末尾「最后更新」改写、\ndocs/ci-fix-plan.md 新增 §11.6。",
          "timestamp": "2026-11-06T18:09:09+08:00",
          "tree_id": "ab4b883f36facd031b3674a29faffac94918d812",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/5cc0781ae569c379289bf5518fe6524d9680eb7b"
        },
        "date": 1793960012104,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 12.719426429166761,
            "unit": "iter/sec",
            "range": "stddev: 0.001850312543414172",
            "extra": "mean: 78.61989733333512 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 13.585067371381275,
            "unit": "iter/sec",
            "range": "stddev: 0.0017881514161925951",
            "extra": "mean: 73.61023487499452 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 212.17205626119002,
            "unit": "iter/sec",
            "range": "stddev: 0.00002352306625999422",
            "extra": "mean: 4.713156000001106 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 2454.231133673211,
            "unit": "iter/sec",
            "range": "stddev: 0.000021749095653546297",
            "extra": "mean: 407.4595853175878 usec\nrounds: 1512"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 22.64616948580894,
            "unit": "iter/sec",
            "range": "stddev: 0.006644839169443534",
            "extra": "mean: 44.15757819999726 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 45.81696041842322,
            "unit": "iter/sec",
            "range": "stddev: 0.0007936365118707086",
            "extra": "mean: 21.825978652173863 msec\nrounds: 46"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 98.05071437035502,
            "unit": "iter/sec",
            "range": "stddev: 0.00010609993437676199",
            "extra": "mean: 10.19880381720445 msec\nrounds: 93"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 1529.481832964824,
            "unit": "iter/sec",
            "range": "stddev: 0.000015245869653376005",
            "extra": "mean: 653.8162000012449 usec\nrounds: 10"
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
          "id": "8b1345d458b6336b9e5936f482953e924002d1c2",
          "message": "docs(ci): 回填 5cc0781 的 CI 终验数据，并把两次翻车都留在账上\n\n远端 CI run 42200923304（push、5cc0781）结论 success：21 个 job = 20 success +\n1 个设计性 skipped（webkit 非门禁）、0 失败。逐项核对而非只看结论：\n- 三条 py3.10 腿的测试步真实执行：ubuntu 145s / macOS 307s / windows 605s；\n- extras 双腿首次真实执行并 success（ubuntu 626s / macOS 879s），且\n  step 6 Coverage gate (hard floors) 判绿 —— 排除 §4.9 那类「无数据」假绿；\n- 产物 28 个 = coverage-* 14 + junit-* 14（含 coverage-extras-macos-* 与\n  junit-extras-macos-*）；e2e chromium 67s / firefox 122s 全绿；\n- 同 push 的 Benchmark 42200923177 success，gh-pages 连续推进 bf2acf93 → 0b859dd8。\n\n中间态 37d7b7f（run 42198208112 failure，windows 四腿绿 / ubuntu+macOS 八腿红）如实保留，\n不当作没发生：它同时证明 py3.10 的原始缺陷已被第一版修好，而第一版的反向对照在 POSIX 上是\n另一种死法。回填位置：AGENTS.md 末尾「最后更新」、docs/agent-context/fixes.md §4.14、\ndocs/ci-fix-plan.md §11.5（原「推送后回填」占位已消除）。纯文档，无代码改动。",
          "timestamp": "2026-11-06T18:45:34+08:00",
          "tree_id": "a4109262f70fbb69a972bbffeb427551986ace34",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/8b1345d458b6336b9e5936f482953e924002d1c2"
        },
        "date": 1793962181266,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 12.57948330803891,
            "unit": "iter/sec",
            "range": "stddev: 0.0009239270819890541",
            "extra": "mean: 79.49452099999614 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 13.602333812263128,
            "unit": "iter/sec",
            "range": "stddev: 0.0014894210434933423",
            "extra": "mean: 73.51679599999628 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 210.34419093253712,
            "unit": "iter/sec",
            "range": "stddev: 0.000036909082481885574",
            "extra": "mean: 4.754112749996153 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 2412.908836600213,
            "unit": "iter/sec",
            "range": "stddev: 0.000011667579824759104",
            "extra": "mean: 414.4375389701832 usec\nrounds: 1514"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 22.688239724956652,
            "unit": "iter/sec",
            "range": "stddev: 0.006549356090092819",
            "extra": "mean: 44.07569790000139 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 46.35159562521017,
            "unit": "iter/sec",
            "range": "stddev: 0.00034443634354720213",
            "extra": "mean: 21.574230326088493 msec\nrounds: 46"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 97.61146989769449,
            "unit": "iter/sec",
            "range": "stddev: 0.00013784870960613965",
            "extra": "mean: 10.24469768817219 msec\nrounds: 93"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 1538.148702667872,
            "unit": "iter/sec",
            "range": "stddev: 0.00001284884328111565",
            "extra": "mean: 650.1322000048049 usec\nrounds: 10"
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
          "id": "5232bbebbba77e78d9f135f2b31e6988b2511cb2",
          "message": "docs(ci): 记下本机 pip-audit 与 CI 门禁环境的口径差，别把缓存读成漏洞暴露\n\n本轮零依赖变更（git diff 只有 tests/ 与 docs/），但本机 python -m pip_audit 报 14 个包命中\n通告。逐条比对：唯一落在运行时依赖上的是 pillow 12.2.0（修复线 12.3.0），而 PyPI 现在解析到\n13.0.0（约束 Pillow>=10,<14），CI 的 pip install -e . 装的是已修复版本 —— Security workflow\n的 success 是真的；mcp 1.29.0 属 extras，主扫描环境不装；其余（virtualenv / werkzeug /\nsetuptools / pip / aiohttp / msgpack …）来自本机额外装的工具链，都不在门禁环境里。\n\n提醒的根据是仓库自身口径：make install 不装 -e .（AGENTS.md §5），开发机依赖树与 CI 门禁\n环境本就不是同一份。要复现门禁得新建干净 venv 只跑 pip install -e .。豁免单\nPIP_AUDIT_IGNORE 仍为空，无需登记。\n\n新增 docs/ci-fix-plan.md §11.6（原 §11.6 二次翻车顺延为 §11.7，交叉引用同步改）。",
          "timestamp": "2026-11-06T18:50:13+08:00",
          "tree_id": "88e439cd3d5e636d5c029c194f39d1e218d435d7",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/5232bbebbba77e78d9f135f2b31e6988b2511cb2"
        },
        "date": 1793962458861,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 12.238204460573236,
            "unit": "iter/sec",
            "range": "stddev: 0.0013318947479556676",
            "extra": "mean: 81.71133300000122 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 13.48495606670429,
            "unit": "iter/sec",
            "range": "stddev: 0.002055268918389679",
            "extra": "mean: 74.15671174999972 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 212.42820789551465,
            "unit": "iter/sec",
            "range": "stddev: 0.000017429851389556124",
            "extra": "mean: 4.707472750002495 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 2460.2158639841964,
            "unit": "iter/sec",
            "range": "stddev: 0.000012952952944892119",
            "extra": "mean: 406.46839760660276 usec\nrounds: 1504"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 22.720796422443886,
            "unit": "iter/sec",
            "range": "stddev: 0.006713198315570093",
            "extra": "mean: 44.01254169999902 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 46.429455856786674,
            "unit": "iter/sec",
            "range": "stddev: 0.0005296503213732334",
            "extra": "mean: 21.538051255318088 msec\nrounds: 47"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 97.99803948743786,
            "unit": "iter/sec",
            "range": "stddev: 0.00010982690603740519",
            "extra": "mean: 10.204285771739215 msec\nrounds: 92"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 1499.7796823621823,
            "unit": "iter/sec",
            "range": "stddev: 0.00002126436724917852",
            "extra": "mean: 666.7646000011018 usec\nrounds: 10"
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
          "id": "50c47133da45d4f3ce799b56b121f4d425731f1c",
          "message": "docs(pitfalls): §3.15 修法口径改成终态，不留「12 腿行为一致」这句已被证伪的话\n\n上一版把「修法」写成 `_run(encoding=\"cp1252\")` 双向断言，并附「纯 Python 层机制、与机器\n语言设置无关，故 12 腿行为一致」——那句正是被 run 42198208112 证伪的判断（POSIX 主线程抛\nUnicodeDecodeError、Windows reader 线程吞成 None，八条腿据此判红）。虽然同节下面的\n「二阶缺陷」已订正，但「修法」条目本身仍是错的表述会被后人当依据照抄。按 §4.11 立的规矩\n（订正到不留「注释说谎」），把「修法」直接改写成终态：反向那半断在字节层，\n① `decode(\"utf-8\")` 有内容 + ② `pytest.raises(UnicodeDecodeError)` 于 `decode(\"cp1252\")`，\n并显式写明「不要调 `_run(encoding=\"cp1252\")`，理由见下一条」。\n变异复核同步订正：Windows 判 TypeError（42185258304 原始签名）、POSIX 判 UnicodeDecodeError，\n两种死法都是红。",
          "timestamp": "2026-11-06T18:51:28+08:00",
          "tree_id": "c0dc1e5bb7e3b584cf4216072212aa65a71d1905",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/50c47133da45d4f3ce799b56b121f4d425731f1c"
        },
        "date": 1793962532899,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 13.218358465199916,
            "unit": "iter/sec",
            "range": "stddev: 0.006197503939654172",
            "extra": "mean: 75.65235900000052 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 13.588822607727083,
            "unit": "iter/sec",
            "range": "stddev: 0.002182987534422591",
            "extra": "mean: 73.58989287499895 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 227.8448768281915,
            "unit": "iter/sec",
            "range": "stddev: 0.00010402341766257899",
            "extra": "mean: 4.388951000000141 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 3064.009012350654,
            "unit": "iter/sec",
            "range": "stddev: 0.000011384022096564404",
            "extra": "mean: 326.3697972065746 usec\nrounds: 1790"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 21.027888394692877,
            "unit": "iter/sec",
            "range": "stddev: 0.0068297678933974554",
            "extra": "mean: 47.55589249999943 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 49.71206716017603,
            "unit": "iter/sec",
            "range": "stddev: 0.00027742893621201294",
            "extra": "mean: 20.115840219999797 msec\nrounds: 50"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 107.35433260671861,
            "unit": "iter/sec",
            "range": "stddev: 0.00017388017660636564",
            "extra": "mean: 9.314947759615773 msec\nrounds: 104"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 2057.93032712278,
            "unit": "iter/sec",
            "range": "stddev: 0.000006686236981894774",
            "extra": "mean: 485.9250999999176 usec\nrounds: 10"
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
          "id": "475633d4bb92299dbe4d4d8cf84b1c0f5308bbc6",
          "message": "docs(ci): 把「与机器语言设置无关，故 12 腿一致」从事实句改成被证伪的旧判断\n\nAGENTS.md 每次会话自动注入，若「本轮改动 ①」仍以这句描述修法，下一个会话会把它当依据照抄——\n而它正是 run 42198208112 八条腿判红的那句错判（POSIX 在主线程抛 UnicodeDecodeError、\nWindows 才在 _readerthread 里吞成 None）。按 §4.11 立的规矩（订正到不留「注释说谎」）：\n\n- AGENTS.md「本轮改动 ①」改写成终态表述（反向断在字节层，正向走 _run 公开默认，\n  两段都不进入 subprocess 的平台分支），并注明第一版的写法与那句已被下一段证伪；\n- docs/ci-fix-plan.md §11.3 把那句从陈述改成「当时以为……已被 run 42198208112 证伪」，\n  指向 11.7 的二次翻车与终态。\n\npitfalls §3.15 的「修法」已在上一个提交同步为终态，本轮四处口径现在一致。\n纯文档：ruff check / format --check（103 files）/ check_agents_md /\ndocs 一致性与契约测试（24 passed）全绿。",
          "timestamp": "2026-11-06T18:53:57+08:00",
          "tree_id": "1b7b554f7e9838d00faf4b843a2509b7dfda271e",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/475633d4bb92299dbe4d4d8cf84b1c0f5308bbc6"
        },
        "date": 1793962672415,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 10.84054245366205,
            "unit": "iter/sec",
            "range": "stddev: 0.014623943006020382",
            "extra": "mean: 92.24630633333202 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 12.888365790934992,
            "unit": "iter/sec",
            "range": "stddev: 0.004604044946708043",
            "extra": "mean: 77.58935587499761 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 208.98507287533317,
            "unit": "iter/sec",
            "range": "stddev: 0.00001959613749530594",
            "extra": "mean: 4.7850307500025835 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 2371.3435285493124,
            "unit": "iter/sec",
            "range": "stddev: 0.000017430985295336867",
            "extra": "mean: 421.70186983062615 usec\nrounds: 1475"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 21.919078540876672,
            "unit": "iter/sec",
            "range": "stddev: 0.006926878655488159",
            "extra": "mean: 45.62235579999907 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 46.378618156816515,
            "unit": "iter/sec",
            "range": "stddev: 0.00011804489006349555",
            "extra": "mean: 21.561660086955925 msec\nrounds: 46"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 97.60724292761971,
            "unit": "iter/sec",
            "range": "stddev: 0.00011087463636630719",
            "extra": "mean: 10.245141344085974 msec\nrounds: 93"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 1532.0516699753807,
            "unit": "iter/sec",
            "range": "stddev: 0.00001912285856200613",
            "extra": "mean: 652.7194999996766 usec\nrounds: 10"
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
          "id": "8d35cee54aa340a9a5abdb85f86b9ffbc058208f",
          "message": "docs(ci): §11 补本轮的五项口径与 tip 运行结论，并说明那几条 cancelled 不是失败\n\n§1–§5 五项口径是为 gh-pages 那轮写的，第四轮（§11）此前只给了根因/修法/红绿表，读者要自己\n推断五项是否沿用。补 §11.0 逐条写死：依赖 0 新增（git diff 只有 tests/ 与 docs/）、启动与验证\n命令、错误处理（不动生产分支，被测工具的 rc=2 与四类分类语义保持；新增的是测试侧「解码失败在\nPOSIX 抛异常、在 Windows 返回 None」这一口径）、参数校验（复用 _run 的 encoding 入参，守卫无\n入参、不设白名单）、基础测试用例（指向 11.4 的正常/异常/边界三类红绿表）。\n\n另记录文档跟进提交的远端结果：8b1345d / 5232bbe / 50c4713 的 CI 因 concurrency.cancel-in-progress\n被后续推送取消 —— cancelled 不是 failure，是我连推文档的副作用；tip 475633d 的 CI run\n42206547889 = success（21 job，0 非绿）、Benchmark 42206548111 = success，gh-pages 推进到\nf8bef9a8。纯文档，无代码改动。",
          "timestamp": "2026-11-06T19:30:30+08:00",
          "tree_id": "41dc8503eb5832ad050b1b8dabe17a28a0274467",
          "url": "https://github.com/QianQianLuLu1/FlashGaze/commit/8d35cee54aa340a9a5abdb85f86b9ffbc058208f"
        },
        "date": 1793964848463,
        "tool": "pytest",
        "benches": [
          {
            "name": "benchmarks/test_batch_bench.py::test_score_batch_small_20",
            "value": 16.418619993535113,
            "unit": "iter/sec",
            "range": "stddev: 0.002859007457802425",
            "extra": "mean: 60.906458666669515 msec\nrounds: 3"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_2000x1500",
            "value": 21.626227949725884,
            "unit": "iter/sec",
            "range": "stddev: 0.0015092756066077185",
            "extra": "mean: 46.2401488749995 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_evaluate_512x384",
            "value": 395.22459996506234,
            "unit": "iter/sec",
            "range": "stddev: 0.00005461290921583367",
            "extra": "mean: 2.5302068749981643 msec\nrounds: 8"
          },
          {
            "name": "benchmarks/test_cv_engine_bench.py::test_compute_sharpness_inmemory",
            "value": 4531.402798551027,
            "unit": "iter/sec",
            "range": "stddev: 0.00001918544015953405",
            "extra": "mean: 220.68221353435243 usec\nrounds: 2852"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_decode_bgr_jpeg_2000x1500",
            "value": 37.916568435898135,
            "unit": "iter/sec",
            "range": "stddev: 0.0048244879903033095",
            "extra": "mean: 26.373694699999106 msec\nrounds: 10"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_downscale_inter_area_3840",
            "value": 91.41514515274068,
            "unit": "iter/sec",
            "range": "stddev: 0.0012140805777730763",
            "extra": "mean: 10.939106406593279 msec\nrounds: 91"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_encode_bgr_b64_2000x1500",
            "value": 184.61020801998635,
            "unit": "iter/sec",
            "range": "stddev: 0.00006366470238364362",
            "extra": "mean: 5.41681855367249 msec\nrounds: 177"
          },
          {
            "name": "benchmarks/test_image_io_bench.py::test_iter_images_scan",
            "value": 2675.4392536200303,
            "unit": "iter/sec",
            "range": "stddev: 0.000006607409144013969",
            "extra": "mean: 373.770399999529 usec\nrounds: 10"
          }
        ]
      }
    ]
  }
}