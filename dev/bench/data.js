window.BENCHMARK_DATA = {
  "lastUpdate": 1792960430458,
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
      }
    ]
  }
}