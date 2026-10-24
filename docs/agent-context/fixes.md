# FlashGaze 历史修复经验（重要 PR/Issue）

> 本文件从 `AGENTS.md` §4 拆分而来，承载完整的修复经验细节。
> AGENTS.md 保留摘要与导航链接。

---

## 4.1 M-12：覆盖率门禁收紧（extras job 阻塞化）

- **问题**：`.coveragerc` 把 5 个模块（mcp_server / webui/app / xlsx_exporter / deduplicator / portrait_engine）排除在 `fail_under=80` 主门禁外，extras job 默认 `continue-on-error`，mcp_server 实际零门禁
- **修复**：
  - 主门禁收窄 omit 至 3 个重依赖模块（xlsx_exporter / deduplicator / portrait_engine）
  - mcp_server + webui/app 纳入 80% 总门禁
  - extras job 删除 job 级 `continue-on-error`，新增无条件 `Coverage gate (hard floors)` 步骤
  - 逐模块下限：mcp_server 82 / webui.app 80 / xlsx_exporter 95（按 2026-09-06 实测基线 int(rate)-5 冻结）
- **契约测试**：`tests/test_coverage_gate_contract.py`（8 条断言锁定防退化）
- **教训**：`continue-on-error` 会让门禁静默放行，必须用契约测试锁定

## 4.2 M-11：配置文件层三入口一致生效

- **问题**：`build_config` 的 `file_cfg` 参数只由 CLI `--config-file` 传入，MCP 与 WebUI 跳过配置文件层且无提示
- **修复**：新增环境变量 `FLASHGAZE_CONFIG_FILE`（`defaults.py`），`build_config` 内部加载 file 层，三入口行为一致
- **优先级链**：CLI 参数（MCP 工具参数）> 环境变量 > 配置文件 > 默认值
- **教训**：多入口配置必须下沉到共享函数，不能依赖各入口手动传参

## 4.3 M-05：BrisqueIntegrityError 供应链安全信号

- **问题**：`_cmd_score` 的 `except Exception` 只包住 `score_paths`，构造期异常穿透到解释器，进程以裸 traceback 终结并返回 Python 默认码 1（与 PARAM_ERROR 重叠）
- **修复**：
  - `make_scorer` 与 `score_paths` 合入同一异常收敛块，用相位标志区分
  - 构造期失败（非 BRISQUE 成因，如端点被 SSRF 拒绝）→ 记「评分器构造失败」+ `CONFIG_ERROR(6)`；评分期失败 → 记「评分失败」+ `IMAGE_ERROR(4)`
  - 新增 `except BrisqueIntegrityError` 分支（**必须排在 `except Exception` 与 `except RuntimeError` 之前**，它是 RuntimeError 子类），构造期与评分期**一律**记「模型完整性校验失败」+ `IMAGE_ERROR(4)`——该分支优先于上一条的相位判定，所以哈希不符不会走 `CONFIG_ERROR(6)`
  - `main()` 分发层新增 `except Exception` 最后防线 → `INTERNAL_ERROR(8)`
- **教训**：供应链安全信号的辨识度靠**专属日志标签 + 顺序敏感的 except 分支**承载，退出码仍复用 `IMAGE_ERROR(4)`（测试 `tests/test_cli_main.py` 四处钉死：`rc == ExitCode.IMAGE_ERROR` 且日志含「模型完整性校验失败」、不含「评分失败」）。别把它记成「专属退出码」——那会让人误等一个不存在的码，正是要防的错标（普通「评分失败」）在码值上无法区分的表现。

## 4.4 M-17：裸跑 pytest 默认口径校验

- **问题**：`pyproject.toml` 的 `addopts` / `testpaths` 默认过滤可能被悄悄回退
- **修复**：CI 新增 `Bare pytest default gate (collect-only)` 步骤，验证裸跑 collect-only 输出不含 e2e/benchmarks 节点 ID
- **教训**：默认口径必须用 CI 守卫，不能依赖开发者自觉

## 4.5 H-10/H-11/H-12：MCP 删除/导出/读取面高危审查

- **H-10**：MCP cleanup 删除失败时返回成功（已修复：返回部分失败清单）
- **H-11**：MCP export 路径未做 containment 校验（已修复：relative_to 边界）
- **H-12**：MCP allowed_roots 未生效（已修复：配置层强制）
- **教训**：MCP 工具是 AI Agent 主用入口，安全护栏必须比 CLI 更严格

## 4.6 CI 覆盖率产物复核：跨腿不确定覆盖与不可诊断产物（2026-10-23，非审查编号项）

- **问题**：用户下载 `coverage-{ubuntu,macos,windows}-latest-py3.1{0,1,2,3}.zip`
  要求定位问题。逐份解析后**没有任何门禁失败**（12 腿总行覆盖 90.68%–90.87%，
  门槛 `fail_under=80`；33 个被统计文件在 12 腿完全一致，无缺模块、无重复 class、
  无 XML 解析异常）。真正暴露的是四类问题，且**产物结构上只有 `coverage.xml` 一个
  文件**，所以「失败测试/错误栈/测试摘要」一类问题根本读不出来：
  1. `core/hybrid_scorer.py` 的「terminate 未生效 → 升级 kill」（974/978）只在
     **1/12** 腿上被覆盖——唯一驱动它的 `@pytest.mark.slow` 真进程池用例断言的是
     墙钟有界，从不检查强杀是否发生，删掉 `proc.kill()` 也不会变红；
  2. `score_one` 单图看门狗超时分支（1314-1323/1349-1350）在 macos-py3.10 与
     windows-py3.10 未覆盖，其余 10 腿覆盖；**下一轮已定性**（见 §4.7）：那两条腿上是
     `test_score_one_cv_hang_returns_error` 自身失败——挂起桩 `time.sleep(1e9)` 在
     CPython 3.10 的 Windows/macOS 上立即抛错而非挂起，分支随用例失败一起缺失；
  3. `utils/atomic_write.py` 109/110/116/118 与 `utils/image_io.py` 148/149 这两组
     `except OSError` 兜底在 **12/12** 腿未覆盖（`os.chown`/`os.lstat` 从未被任何
     测试打过）；
  4. 测量引擎分裂（见 §3.7）+ extras 投递给 Codecov 的 flag 名与 `codecov.yml`
     声明名错配（`extras-ubuntu-latest` vs `extras-ubuntu`，声明的
     carryforward/informational 全部落空）。
- **修复**：
  - **假池桩取代计时偶然**：`tests/test_hybrid_scorer.py` 新增 `_FakeProc`，并给
    `_install_fake_pool` 增加特殊键 `__procs__`（缺省空表，生产代码对「无
    `_processes` 属性」与「空表」同样安全跳过，故既有 ~10 条假池用例行为逐字节不变）。
    两条新用例不打 `slow`，12 腿与 `make test` 都跑；其中 `join_timeout ==
    _TERMINATE_JOIN_SEC` 顺带钉住「join 必须带上界」这条契约，且假 `join()` 不等待，
    5 秒常量零成本。
  - **异常兜底确定性化**：`tests/test_atomic_write.py` 补 `preserve_mode` chmod 失败
    与 chown 失败两条（后者 `skipif` 非 POSIX）；`tests/test_image_io.py` 用
    `monkeypatch.setattr(image_io, "os", …)` **注入假 os 命名空间**而非全局改
    `os.name`（posixpath/shutil/pytest 上报都读 `os.name`，全局改写爆炸半径不可控），
    把 lstat 竞态与 reparse tag 三态一次打全。
  - **产物可诊断**：test job 的 pytest 补 `--junitxml=junit.xml`，junit 单独成
    `junit-<os>-py<ver>` 产物（**不塞进 coverage-***，保住「coverage 产物只含
    coverage.xml」这一跨腿比对前提），并新增逐腿摘要步骤把 FAILED/ERROR 与计数写进
    job summary、逐条发 `::error::`。
  - **聚合与口径**：extras 的 `flags` 改为 `fromJSON` 查表（新增腿未登记即判红）；
    `requirements-dev.txt` 钉死 `coverage[toml]==7.16.2`。
  - **契约测试**：`tests/test_coverage_gate_contract.py` 由 8 条增至 11 条——flag 对齐、
    逐腿 junit、引擎钉版。红灯实证：逐条回退对应配置，三条新用例各实测 FAILED，
    回退文件还原后逐字节一致。
- **教训**：
  - 「覆盖率里有几行只在 1/12 条腿上命中」是**测试稳定性**信号，不是覆盖率噪声：
    它意味着该行为实际上没有断言保护，回归不会变红。
  - 产物内容决定可诊断范围。只上传覆盖率时，「这条腿为什么红」只能靠猜——本轮
    问题 2 当时无法定性（失败/报错/未跑三种可能在产物里不可区分），只能交给新落地的
    junit 下一轮给答案；下一轮（run 39909374394）的 junit + 逐条 `::error::` 注解即把它
    定性为「用例失败」并顺带查出另外 7 类跨平台/跨版本问题（§4.7）。
    **证据不足时如实标注，不猜改生产代码。**
  - 依赖未钉版时，上游一次发布就能让同一次 CI 运行内出现两个测量引擎；`coverage`
    这类「只经间接依赖引入」的工具同样要显式钉。

## 4.7 CI 跨平台/跨版本红灯：8 类报错一次性收口（2026-10-23，非审查编号项）

- **问题**：run 39909374394（`main` @ `e837d50`）的 `ruff` 与 `mypy` 两个 job 红，
  12 条 `test` 腿红 10 条（仅 windows-py3.12/py3.13 绿），`e2e` 与 `extras` 因依赖
  `test` 被连带跳过。开发机（Windows + py3.12）上 `ruff check` / `ruff format --check`
  / `mypy` / 全量测试**全绿**——本地绿不等于 CI 绿。
- **取证**：`e837d50` 落地的逐腿 `::error::` 注解给出 12 腿的失败用例名与首行错误；
  Actions 原始日志给出两个静态 job 的报错原文；`junit-macos-latest-py3.13` 给出完整
  traceback；两份 POSIX `coverage.xml` 给出覆盖率基线与缺失行清单。三类证据交叉，
  8 类根因全部定位到行。
- **修复**（8 类，按「本地可逐字复现 → 只能按平台语义论证」排序）：
  1. `EXE001` × 2：删 `tools/check_agents_md.py`、`tools/extras_health.py` 的 shebang
     （两脚本从未被直接执行；仓库 0 个 `100755` 跟踪文件），并在各自 docstring 留
     「勿加 shebang」的原因注释。
  2. `mypy` 的 `_winapi.CreateJunction`：`tests/test_image_io.py` 改
     `getattr(_winapi, "CreateJunction", None)` + 缺属性即 `pytest.skip`。取证口径：
     `python -m mypy --platform linux` 在 Windows 开发机上逐字复现 CI 那条错（同样
     78 source files），修复后两面（默认 win32 与 `--platform linux`）均 0 错误。
  3. POSIX 只读目标（F3）：给 `test_readonly_target_rejected_leaves_no_tmp` 补
     `skipif(_IS_POSIX)`，与同文件既有的 POSIX 镜像用例构成反向守卫对。覆盖率中性有
     实证：两条 POSIX 腿的 `atomic_write.py` 缺失行是 152/162/164/168/170（C-18 陈旧
     tmp 段），`:100-132` 一行不缺——该段早被镜像用例覆盖。
  4. macOS 3 核钳制（F1）：5 条 `test_build_config_*` 补
     `monkeypatch.setattr(os, "cpu_count", lambda: 16)`，沿用 `tests/test_cli_parser.py:93-94`
     既有口径；**不动** `tests/test_mcp_server.py:88-94`（它按真实核数验钳制，是
     `config.py` 钳制分支的唯一覆盖来源）。本地以 `os.cpu_count=lambda:3` 逐字复刻出
     CI 的 5 条 `assert 3 == 4`，修复后 3 核与 2 核模拟均 6 passed。
  5. py3.10 挂起桩（F5）：`time.sleep(1e9)` → `threading.Event().wait(30)`（本文件
     `_hang_thread_stub` 既有口径）。附带收益：§4.6 问题 2 那两条腿的看门狗分支转为覆盖。
  6. PTY 合流（F4）：`_extract_json` 改 `json.JSONDecoder().raw_decode` 只取第一个完整
     JSON 文档 + 结构断言（伪锚点必须响亮失败而非静默返回错文档）。不动 CLI：
     「stdout 只输出 JSON」是 `_emit_json` 的既有契约，合流是测试载具属性。
  7. 真实池连带判死（F6）：断言范围对齐实现真正保证的范围（不钉「good1 必须出分」，
     改钉「不得被整批判死」+ `phase1_stats["rebuilds"] >= 1` 指纹），强断言迁到 12 腿都
     跑的确定性假池用例；根因与产品缺口另立 §3.10。
     **否决**「把 `PER_IMAGE_TIMEOUT_SEC` 由 15s 提到 30s」：结构问题（同代共享 deadline）
     不因阈值翻倍而消失，却让 12 条腿从 ~49s 涨到 ~95s 一起付墙钟。
  8. 跨解释器权重漂移（F2）：`utils/config.py` 两处 `sum` → `math.fsum`。**改产品而非给
     测试加容差**：容差只让测试闭嘴，`config.weights` 在 3.10/3.11 与 3.12+ 上仍不相等，
     与 `tests/test_reproducibility.py` 的立场冲突。取证：本机 3.11.16 实跑得
     `sum=0.9999999999999999` → 二次归一化 `0.39999999999999997`，`fsum` 两面皆 `0.4`；
     3.12 上 `fsum` 与现状逐位相同（238 条权重/parser/config/webui/reproducibility 用例
     全绿）。反例：只改前一处得 `0.4000000000000001`（更偏）。
- **防复发**：`ruff==0.16.10` / `mypy==1.20.2` / `types-requests==2.33.0.20261006` 钉死
  单版本（同 §3.7 的 coverage 逻辑），`Makefile` 新增 `typecheck-posix` 并并入 `check`，
  `tests/test_coverage_gate_contract.py` 由 11 条增至 12 条。**诚实标注**：本轮两个静态
  job 的根因是平台盲区而非版本漂移，钉版消除的是归因成本而非这两类红灯本身——该订正
  发生在日志到手之后（最初曾误归因于「CI 解析到更新的 ruff/types-requests」）。
- **教训**：
  - **静态门禁跑在哪个平台，就必须在那个平台的视角下自检一次**。mypy 有
    `--platform linux` 这个开关可以在任意机器上复现 CI 那一面；ruff 的 exec 位类规则
    没有等价开关，只能靠「不写做不到的承诺」+ CI 兜底。
  - 测试桩的**原语选择本身就是跨平台契约**：`sleep(巨值)`、`chmod(0o444)`、
    `cpu_count()` 派生的期望值、整段尾部 `json.loads`，四种写法都能在开发机上绿。
  - 断言只能覆盖实现真正保证的范围。真实进程池里「排队好图必定出分」不是保证项，
    把它写在依赖轮询粒度与集合迭代顺序的用例上，就是一枚定时红灯。
  - 请求自带的前提（「是版本漂移」）要在证据到位后复核并公开订正，不能顺着写进计划。

## 4.8 §4.7 的独立复验：双向证据与仍不可本地证明项（2026-10-23）

- **前置**：本地 venv 与钉版不一致（实测 `ruff 0.16.4`、`types-requests 2.33.0.20260712`），必须先
  `pip install -r requirements-dev.txt` 对齐到 `0.16.10` / `20261006` 再验——否则「本地全绿」并不覆盖
  被钉版本那一面，等于没验。
- **取证方法**：§4.7 的全部改动只存在于工作区，`git stash` 与 `git checkout e837d50 -- <path>` 都可能毁掉
  唯一副本；改用 `git worktree add --detach <tmp> e837d50` 拿未修复副本对照，用完 `git worktree remove`。
  附带查实：editable 安装记录指向一个**已不存在**的目录（`D:\WorkBuddy\SaiTu skill`），而
  `tests/__init__.py` 使 pytest 把仓库根插入 `sys.path`，实测两个目录各自 `import flashgaze` 落到自己的
  副本（worktree 里 `math.fsum` 命中数为 0、工作区为 5），故对照有效。
- **双向证据（修复前失效 → 修复后通过）**：

  | 类 | 修复前（`e837d50` 副本） | 修复后（工作区） |
  |---|---|---|
  | ② mypy 平台盲区 | Windows 上 `mypy --platform linux` 逐字复现 `tests\test_image_io.py:97:9: Module has no attribute "CreateJunction"` + `checked 78 source files` | 默认与 `--platform linux` 两面皆 `Success: no issues found in 78 source files` |
  | ④ macOS 3 核钳制 | `os.cpu_count=lambda:3` 下复现 5 条 `assert 3 == 4`（`-k worker` 3 条 + `-k "1e999 or infinity"` 2 条，与 CI 的 5 条逐一对应） | 16 / 3 / 2 核模拟皆 `7 passed`（含 `test_cli_parser.py` 同口径用例） |
  | ⑤ PTY 合流 | 同一合成缓冲（JSON + 尾部 INFO）旧 `_extract_json` 抛 `JSONDecodeError: Extra data` | 取回正确文档；结构合法但非报告 → `"summary" in data` 判红；伪锚点 → `JSONDecodeError`（两种都响亮失败，不静默返回错文档） |
  | ⑦ 权重末位漂移 | 真实 py3.11.16 下 `build_config(weights=…)` 得 `0.39999999999999997` | 同一解释器得恰好 `0.4`；四组合实测「只改一处」为 `0.4000000000000001`（更偏），印证两处必须同改 |

- **反例**：把 `_POOL_REBUILD_LIMIT` 归零后
  `test_phase1_real_pool_hung_worker_teardown_bounded[5]` 判红，日志给出「重建代数(0)已耗尽」→
  重建路径与新增的 `rebuilds >= 1` 指纹都确实在断言东西。如实记录：该反例先撞上 `:1662` 的逐图隔离断言，
  没有单独隔离到 `:1684` 的 `rebuilds` 断言；后者由「用例整体通过 ⇒ 内含断言为真」传递证明。
- **本地基线**：`ruff check` 通过、`ruff format --check` 97 files、两面 mypy 各 78 files、
  `python -m tools.check_agents_md` PASS、`pytest tests/` **1038 passed / 29 skipped / 38 deselected
  （7 分 25 秒，严格串行）**。
- **仍只能由 CI 终验**（不以本地绿冒充）：ubuntu 的 `EXE001`（已实测同版 ruff 在带 shebang 的 `e837d50`
  副本上于 NTFS 恒不报，盲区坐实）、POSIX 只读语义、真实 PTY（本机整类 skip）、py3.10 的 `Sleep`/`select`
  （本机只有 3.11/3.12，无 3.10 解释器）、macos-latest 真实核数、真实 spawn 池在 macOS 负载下的代际拆分。
- **顺带订正两处表述**：① `.qoder/` 被 `.gitignore` 忽略且 `git ls-files .qoder` 为空，§4.6/§4.7
  「口径同步」把 `.qoder/rules/*` 列为同步对象属不实（CI 与同事拿不到），已就地标注并在 AGENTS.md §9.5
  补「反向情形」；② 默认口径的 38 条 deselected = `tests/e2e` 10 + `tests/test_cli_e2e.py` 28
  （`:19` 有 `pytestmark = [pytest.mark.e2e]`，由 `0d5aab1` 引入），README 的日期快照与此一致，
  CHANGELOG 里 M-17 那条「`test_cli_e2e.py` 仍被默认收集」属当时成立、现已被 marker 改写的历史记录。
- **教训**：本地全绿的前提是「工具链与被钉版本同源」+「对照副本真的是未修复的那一份」。两者任一没核实，
  「我复现了 CI 的红灯」就只是自证。

## 4.9 extras 腿与趋势图双红灯：可选依赖 import 期 quit() + action 入参名错配（2026-10-24，非审查编号项）

- **远端状态**：`main @ 9659ad5` 的 CI run `39986414762` 里 12 条 `test` 腿、`ruff`、`mypy`、
  `agents-md-integrity`、`check-strict`、`e2e chromium/firefox` 全绿，只红
  `extras (ubuntu-latest, py3.12)` 与 `extras (macos-latest, py3.12)`；另有定时 run
  `40031692874`（extras-health，**该 workflow 的首次运行**）红在 `publish trend charts`。
- **初判被证伪并订正**：拿日志前先假设「2026-09-06 冻结的逐模块下限 82/80/95 与当前真实
  覆盖率第一次对撞」。用户提供 raw log 后证实**根本没有任何覆盖率数据可言**——门禁第一步就
  `No data to report.` exit 1，因为上一步 pytest 在收集阶段 `INTERNALERROR`（exit 3）。
  根因是 `face_recognition` import 期 `quit()` 抛 `SystemExit` 穿透了只兜 `ImportError` 的
  守卫（详见 pitfalls §3.11）。教训与 §4.7「请求自带的前提要在证据到位后复核并公开订正」同源，
  且这次证伪的是**我自己**写下的假设。
- **三处一次性修复**：
  1. `flashgaze/core/portrait_engine.py` 的探测守卫改 `except (ImportError, SystemExit)`，
     新增 `tests/test_portrait_import_guard.py`（2 条：主用例 + 「退出码 0 不可作判据」反例）。
  2. `.github/workflows/extras-health.yml` 的 charts 步骤：`raw-data-file` →
     `output-file-path`，并删掉 `output-storage`（两者都不是
     `rhysd/github-action-benchmark` 的入参；runner 原文
     `Unexpected input(s) 'output-storage', 'raw-data-file'` +
     `Invalid value for 'output-file-path' input: … is not a file`）。
     同仓库 `benchmark.yml:174` 用的是 `output-file-path` 且长期成功，是现成参照物。
  3. 同文件 `Evaluate health` 步骤的 `python - <<'PY'` 里 `open("$GITHUB_OUTPUT", …)`：
     引号定界符使 bash **不展开变量**，Python 打开的是字面叫 `$GITHUB_OUTPUT` 的文件、
     进程 0 退出，`steps.eval.outputs.*` 永远为空 → 写/清 sentinel 锁与建/关 tracking Issue
     四处步骤**从未执行过一次**，extras-governance §4 的 R4 熔断链路整条是死的。
     改 Python 侧 `os.environ["GITHUB_OUTPUT"]`（保留引号定界符，不把整段脚本暴露给 shell）。
- **防复发**：`tests/test_coverage_gate_contract.py` 由 12 条增至 **14 条**——
  ① benchmark action 的 `with:` 必须含 `output-file-path` 且不含 `raw-data-file`/
  `output-storage`；② 任何 workflow 的引号 heredoc 体内不得出现 `$GITHUB_OUTPUT`/
  `$GITHUB_ENV`。两条都带内置反例（删键/换回误用名/合成 heredoc 必须被抓到，
  `os.environ` 写法与 ci.yml/benchmark.yml/release.yml 的块外直写不得误伤）。
  守卫落地时即被**自己的注释**打回一次（heredoc 内的说明文字里写了 `$GITHUB_OUTPUT`），
  顺带证明它不是恒真断言。
- **门禁可诊断化（阈值零变更）**：ci.yml `Coverage gate (hard floors)` 加「`.coverage` 存在且
  非空」前置检查 + 4 条命令各一行标签，使「无数据」与「未达标」在日志里可分。用 `-s` 而非 `-f`：
  空的数据文件同样无数据，本地反例已证 `-f` 会漏、`-s` 抓到（两条都跑出 exit 1）。不改
  `continue-on-error`、不把 `if-no-files-found` 改成 `error`——按既有原则
  （§4.7 与 `test_ci_test_job_uploads_junit_per_leg` 的护栏）**不让诊断步骤制造第二条红**。
- **本地双向证据**：
  - 失效→通过：新回归用例修复前 `F.`（子进程 `exit=0`、stdout 只有 pip 提示、无成功标记，
    即 CI INTERNALERROR 的确定性复现），修复后 2 条全绿。
  - 契约守卫失效→通过：先落测试 → `2 failed, 12 passed`（真文件里就是坏的）；改完 workflow
    → `14 passed`。
  - 本地基线：extras 口径 5 模块总覆盖 **78%**（逐模块 mcp_server 86% / webui.app 85% /
    xlsx_exporter 100% / deduplicator 48% / portrait_engine 44%），四条硬门禁命令逐条 EXIT=0。
- **仍然只能由 CI 终验**（不以本地绿冒充远端绿）：`82/80/95` 三条逐模块下限此前**从未在 CI 上
  真实比对过**（extras 每次都被 `needs: test` 连带 skip），本轮第一次产出数据后能否守住须看
  run 结果；`charts` 两步转绿、`gh-pages/dev/extras-health/` 由 404 变存在；
  ubuntu/macos 上 `face_recognition` 是否还有别的 import 期动作。
- **⚠️ 修好之后的新行为（必须知会）**：链路一旦接通，夜间 `collect` 会第一次真跑到 R1/R4。
  按 pitfalls §3.11 的本地口径，`portrait_engine` 44% 与 `deduplicator` 48% 都低于 R1 的 60%，
  且 `portrait_engine` 低于 R4 的 50% 临界线 → `decision=critical` → `write_lock=true`，
  即**下一次定时运行会真的往 `main` 提交 `.github/extras-strict.lock` 并开 Issue**。
  后果是 `check-strict` 输出 `strict=true`、extras 的 5 模块总下限从 50 抬到 60
  （本地 78% 仍过，不会新增红灯，但锁与 Issue 是真实产物）。这属治理机制的设计本意第一次生效，
  不是新缺陷；若不希望它立即接管，须先让 deduplicator/portrait_engine 脱离「降级路径」口径
  （装 `setuptools` 真跑 face_recognition，或补这两模块的降级路径用例）。
  **待排期的口径冲突**：extras-governance §2.1 明确接受 dedup/portrait 的降级路径数字
  （故不设逐模块 floor），而 §4 的 R1/R4 是按「任一模块」绝对线判定的——两条规则对这两个
  模块的口径本就不一致，此前被「数据恒为空」掩盖着。
