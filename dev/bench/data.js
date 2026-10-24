window.BENCHMARK_DATA = {
  "lastUpdate": 1792873617151,
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
      }
    ]
  }
}