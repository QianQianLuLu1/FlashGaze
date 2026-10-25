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

## 4.10 §4.9 的连带后果：extras 超时、rc=2 断电、stdout 污染（2026-10-25，非审查编号项）

- **远端状态**（`main @ dcf8c59`，与本地 HEAD 一致）：
  - CI run `40107357212` 结论 `cancelled`——21 个 job 里 20 个绿（12 条 `test` 腿、`ruff`、
    `mypy`、`agents-md-integrity`、`check-strict`、`e2e chromium/firefox`、
    **`extras (ubuntu)` 首次带真实数据转绿**，82/80/95 逐模块下限第一次真实通过，
    证明 §4.9 的守卫修复有效），唯一红是 `extras (macos-latest, py3.12)`。
  - extras-health run `40134963461` 结论 `failure`，红在 `collect` 的 `Evaluate health`；
    `charts` 因 `needs: collect` 被跳过，`Publish sentinel state` / 建 Issue / 关 Issue 三处
    `skipped`。`.github/extras-strict.lock` 在 main 上仍是 404（已核实）。
- **取证通道**：Actions 的 job **logs 与 annotations 端点免鉴权返回 403/404**、artifact zip
  端点 401，因此由用户从浏览器下载两份 job 日志 + `extras-health-out` +
  `coverage-extras-ubuntu-latest-py3.12` 四个产物后分析。runs/jobs/steps 时序与产物清单
  （含每个 step 的起止时间）公开 API 即可取，「哪一步红、红多久」全部由此定位。
- **三条结论**：
  1. **macOS extras 不是卡死，是预算错配**。同一停点（前 628 条用例结果行，pytest 自报 58%）
     ubuntu **97s** vs macOS **824s = 8.5 倍**，而默认矩阵的 ubuntu→macOS 只有 1.46 倍；
     单条最慢 `test_score_batch_is_deterministic_without_vlm` **145.6s**，
     `test_hybrid_scorer.py` 合计 457s（55%）、`test_cli_main.py` 271s（33%）。被杀时无任何
     stuck 单点，成本集中在真进程池用例（macOS 用 `spawn` 且只有 3 核，见 §3.9）。
     job 前 5m33s 是 setup+install → 外推 pytest ≈24.8 分钟、整 job ≈31 分钟 > `timeout-minutes: 20`。
     派生红：`Coverage gate (hard floors)`（`if: always()`）因 `.coverage` 未写出而报
     「无覆盖率数据」——**这条红不是覆盖率不达标**，是超时的下游症状。
  2. **`Evaluate health` 被脚本自己的退出码打死**。`tools/extras_health.py` 的 `main()` 用
     `return 2` 表达 critical，步骤未兜非零码 → 步骤红 → 三处下游（无 `if: always()`）skipped，
     §4.9 第 3 条刚接通的 outputs **一次也没被消费**。`decision.json` 实测
     `decision=critical`、`actions.write_lock=true`、criticals 仅一条 R4（portrait 47.62%）；
     `gh-pages` 上 `dev/extras-health/history.json` 为 404 ⇒ 历史为空，R2/R3/R4-lag 不可能触发，
     临界只能来自绝对线（独立用 CI 真实 coverage.xml 重算 5 模块 = 87.71/85.77/100/83.72/**47.62**，
     与产物逐字一致）。详见 pitfalls §3.12。
  3. **4 条用例失败的真因是 stdout 被第三方 `print()` 污染**（§4.9 只修了「进程被打死」那一半）。
     失败者恰为全部「子进程跑 CLI + 严格 `json.loads(stdout)`」用例：
     `test_cli_terminal_e2e.py:98/:116/:160` + `test_reproducibility.py:163`，报错统一
     `Expecting value: line 1 column 1 (char 0)`。旁证三条：同文件用容错 `_extract_json` 的
     4 条 `TestPtyTerminal` 全绿；`assert returncode == 0` 在 `json.loads` 之前且通过；
     `tests/test_cli_e2e.py` 被 `pytestmark = e2e` 全程去选（日志中出现 0 次），故不构成反例。
     本地直接抓到子进程 stdout 形态为「两行 pip 提示 + 完整 JSON」。**注意 §4.9 新增的守卫
     用例当时把「提示出现在 stdout」写成了断言**，等于把污染钉住。
- **修复（阈值一条未改）**：
  1. `flashgaze/core/portrait_engine.py`：探测块用 `contextlib.redirect_stdout/redirect_stderr`
     把第三方 import 期输出整段吞掉（静默丢弃，不投 logger——`set_verbose` 在
     `cli/entry.py:58` 才生效、晚于模块级探测；WARNING 级默认输出又会在 `--json 2>&1`
     合流时重新污染 JSON）。
  2. `tests/test_portrait_import_guard.py`：假包改为「stdout 打提示 + stderr 打提示」，
     非空洞性凭证换成**独立落盘的哨兵文件**，主用例断言方向翻为 `hint not in stdout`；
     「退出码 0 不可作判据」那条反例原样保留（它刻意裸 import，必然看到提示，与主用例互为反向）。
  3. `.github/workflows/extras-health.yml` `Evaluate health`：`|| rc=$?` + 只在
     `rc ∉ {0, 2}` 时按原码退出，rc=2 打 `::warning::` 后继续（真崩溃仍然是红）。
  4. `tools/extras_health.py`：新增 `JUDGED_MODULES`（逐字等于 ci.yml 带 `--fail-under` 的
     3 个模块），R1/R2/R4 绝对线按它过滤，**R5 同步收敛**（否则「能加锁、永远解不掉」，
     自愈会因 portrait 的降级口径而永久失效）；`MODULES` 全集继续进 snapshot /
     benchmark.json / Issue 表格，Issue 里给观测项显式标注「不参与判定」。R3 与 rc=2 语义不动。
  5. `.github/workflows/ci.yml` extras job `timeout-minutes: 20 → 40`，注释绑定 run
     `40107357212` 的实测数字（沿用本仓库「门禁数字与取证 run 绑定」的惯例）。
  6. 同 job 补 `--junitxml=junit.xml` + 产物 `junit-extras-<os>-py<ver>`：extras 腿此前无
     junit，`continue-on-error` 吞掉的失败完全不可见（本次 4 条能被发现纯粹因为旁路
     extras-health 恰好带 junit）。产物名必须带 `extras` 前缀——extras 与 test 两 job 的
     matrix 名完全相同，`upload-artifact@v4` 在同 run 内会因重名报错。**未**复制 test job
     那 55 行 heredoc 摘要实现：两处各一份迟早漂移，属 §4.6/§4.9「配了但没接线」同族风险；
     逐腿 job summary 仍只在 test job 提供（已知残余缺口，见下）。
- **防复发**：`tests/test_coverage_gate_contract.py` 由 14 条增至 **17 条**——
  ① `JUDGED_MODULES` 与 ci.yml 逐模块 floor 集合双向相等（放宽判定集 / 删一条 floor 行都判红）；
  ② `Evaluate health` 必须「只容忍 rc=2」（缺 `|| rc=$?`、`rc -ne 0` 一律失败、`|| true`、
  改回步级 `continue-on-error` 四种写法都判红，另断言采集步骤的 `continue-on-error` 仍在，
  防反例失去对照）；③ extras job `timeout-minutes >= 40` 且注释含 run 号。
  ①② 用纯文本正则解析（不 import `tools/`、不装 PyYAML），与本文件既有范式一致。
  另新增 `tests/test_extras_health_rules.py` **7 条**：`tools/extras_health.py` 的 R1-R5 此前
  **零单测**，用例按 CI 真实 coverage.xml 的（覆盖, 总）行数构造、子进程真实调用脚本，
  同时断言 decision 与**退出码**。
- **本地双向证据**：
  - F3：`PYTHONPATH` 前置「print 提示 + quit()」假包 → 修复前 `3 failed`（Windows 上 SIGINT
    那条 skip，故 3 而非 4），报错与 CI 逐字相同；修复后 `3 passed, 1 skipped`；守卫用例
    翻断言后先 `1 failed`（stdout 里确有提示）再转绿。
  - F2/口径：同一份 CI 真实 coverage.xml，`git show HEAD:tools/extras_health.py` 跑出
    `decision=critical` + **rc=2**，工作区版跑出 `decision=ok` + **rc=0**、`write_lock=false`。
  - rc 管道：用 stub 分别产 0/2/1/3，确认 `set -e` 下 0 与 2 走到达后续步骤、1/3 按原码退出；
    另确认未初始化 `rc` 时 `${rc:-0}` 路径正常。
  - 全量基线：`ruff check` / `format --check` / `mypy`（本机 + `--platform linux` 两面，80 files）/
    `tools.check_agents_md` 全绿；`pytest tests/ -q` = **1052 passed, 29 skipped, 38 deselected**
    （改动前 1038 passed 基线之上的增量来自本次新增 7 + 3 条与 §4.9 的 2 条守卫用例；
    未见任何原通过用例转红）。
- **仍然只能由 CI 终验**（不以本地绿冒充远端绿）：
  - macOS extras 的 40 分钟是否够用：31 分钟是**在 58% 进度处的线性外推**，非实测；剩余 42%
    含 gradio/webui 用例，若仍被杀则下一步是真去治 `test_hybrid_scorer` 的 spawn 成本，
    而不是继续加预算。
  - `charts` 与 `weekly-report` 在 `collect` 转绿后**首次真实执行**：`gh-pages/dev/extras-health/`
    能否落地、`weekly-report` 往 tracking Issue #11（已核实 open 且带 `extras-health` 标签）
    发评论是否正常。下一个触发点是周一 cron `9 9 * * 1`（2026-10-27）。
  - `Close resolved Issue` 只在 `recovered`（判定集全 ≥70% 且连续 2 快照无失败）时触发，
    当前 portrait 47.62% 下不可能命中，故不会误关 Issue #11；R5 收敛后该路径由
    `test_recovery_only_needs_judged_modules` 覆盖。
  - `junit-extras-*` 重名风险已按命名规避，但同 run 内两 job 产物的实际落地仍需 CI 验证。
- **已知残余缺口（如实标注，不在本次处理）**：
  1. **Codecov 从未收到任何数据**：每条腿都报
     `Upload queued for processing failed: {"message":"Token required - not valid tokenless upload"}`，
     即 `secrets.CODECOV_TOKEN` 缺失或失效；`fail_ci_if_error: false` 使其恒绿。§4.8/`e837d50`
     修的 flag 名对齐因此仍无实际收益——`extras-ubuntu`/`extras-macos` 的
     carryforward/informational 继续落空。属仓库 secret 配置项，需人工处理，**不改代码绕过**。
  2. extras 腿仍无逐腿 job summary（只有 junit 产物），且 **job 被 timeout 杀掉时 junit
     不会写出**，超时类问题仍需原始日志。
  3. macOS extras 的真实性能杠杆在 `test_hybrid_scorer` 的 spawn 池成本（单条 145.6s），
     属独立性能议题，本次刻意不与门禁混在一起处理。
  4. dedup / portrait 改为只观测后，二者真实劣化不再自动告警（方向② 的已知代价）。

## 4.11 extras macOS 腿超时：31 分钟外推被证伪，根因是 worker 冷启动的可选依赖税（2026-10-25，非审查编号项）

- **触发**：`main @ 7288d7d` 的 CI run 40174423841 结论 `cancelled`。21 个 job 里 20 个绿，唯一
  异常是 `extras (macos-latest, py3.12)`：测试步独自跑到 **2091s** 仍未结束，job 全程 2428s 撞上
  `timeout-minutes: 40`；随后 `if: always()` 的 `Coverage gate (hard floors)` 打「无覆盖率数据」
  ——与 §4.10 完全同形的**派生红**，且 `coverage-extras-macos-*` / `junit-extras-macos-*` 两个产物
  跨这两次 run 均未生成（公开 API 的产物清单可查，无需下载）。
- **先说结论：上一轮那条「外推整 job ≈31 分钟」是错的**，且错在方法而非算术。31 分钟来自
  「20 分钟杀在 58% 进度」的线性外推，但 pytest 进度按**用例条数**走、耗时按**用例种类**分布：
  后半程集中了真进程池用例，单条成本是前半段的量级差异项。据此，40 分钟不是「留了余量」，
  而是仍然低于真实需求——只是差多少当时不可知。
- **根因取证（不是推测）**：同一条命令 ubuntu 测试步 404s、macOS >2091s（≥5.2 倍），而默认 12 腿
  矩阵的 ubuntu→macOS 只有 1.46 倍。差额只能是「extras 装上之后才出现的每 worker 成本」。
  逐项查导入闭包：`ProcessPoolExecutor` 的 worker 按 `module+qualname` 重导入
  `flashgaze/core/hybrid_scorer.py`，而该文件在模块顶层导入了 `deduplicator`（模块级
  `from imagededup.methods import PHash`）、`portrait_engine`（模块级 `import face_recognition`）、
  `vlm_client`（模块级 `import litellm` + `litellm.exceptions`）。放大项是「池代数 × worker 数」：
  `tests/test_hybrid_scorer.py` 的 `test_score_batch_is_deterministic_without_vlm` 一条就是
  10 次 `score_batch` × 4 worker = 40 次 spawn。旁证是同文件 `:267` 的 PHash 编码**早就是**函数内
  导入且有 `enable_dedup` 守卫、`tests/test_dedup.py` 还专门断言「被测代码是函数内导入」——
  仓库本来就有正确形态，只是被模块顶层导入整个抵消掉了。
- **修复（阈值/矩阵/预算一条未改）**：`hybrid_scorer.py` 改按需导入——`PortraitEngine` /
  `VLMClient` 的类型引用移入 `if TYPE_CHECKING:`（`VLMClient` 全文件只有注解用途，真实构造点在
  `core/factory.py`）；`HybridScorer.__init__` 的两个构造点改为函数体内导入但**保持无条件**；
  worker 侧人像构造收进 `if enable_portrait:`。不改三个探测块（§3.11 刚修好的
  `except (ImportError, SystemExit)` + `redirect_stdout/stderr` 原样留在原位）。
- **双向证据（本地可证部分）**：
  - 修复前失效：`tests/test_worker_import_budget.py` 4 条中 **3 红 1 绿**（绿的必须是非空洞性
    对照），失败消息直接给出 `['imagededup', 'litellm', 'face_recognition']`。0.76s 跑完。
  - 修复后通过：同 4 条全绿；`tests/test_coverage_gate_contract.py` 17→**18** 条全绿。
  - 四条反例实跑判红并已还原（逐条 `git diff` 复核无残留）：A 把 `Deduplicator` 导回第 0 列 →
    动态与静态两侧同时判红；B 把 worker 人像改成「永不加载」→ 开启侧判红（堵「拿删功能换绿」）；
    C 把装配点构造条件化 → 探针侧判红（堵「覆盖率来源被偷偷搬走」）；D 删掉证伪 run 号 → 契约判红。
  - 反例 E（终验后随「实测 run 号」守卫一起加）**第一版构造无效**：只把 run 号从注释正文那一处
    删掉，而它在「起点/证伪/实测」清单里还有第二处，`in extras_job` 仍为真、18 条全绿——反例什么
    也没测到。改成删除**全部**出现后才拿到 rc=1。教训：反例必须先证明「守卫能看见我改的这个字节」，
    否则它只证明了「我改的地方不是守卫看的地方」，与 §4.8「对照副本真的是未修复那一份」同族。
    还原由独立复核确认（run 号计数回到 2、契约 18 条回绿），不依赖脚本自述。
  - 本地全量基线：`pytest tests/ -q --cov=flashgaze` = **1058 passed, 29 skipped, 38 deselected**、
    覆盖率 **90.49%** ≥ 80；跳过数 **29 与改动前基线逐字相同**——这条不变量证明「收集期探测时机」
    没被改坏（若 extras 相关的 skip 集合发生变化，说明依赖守卫被移动了位置，属越界）。
    增量 6 条 = 本条新增的 4（worker 导入预算）+ 1（契约静态兜底）+ 1（进程内人像分支）。
    `ruff check` / `ruff format --check` / `mypy`（本机 + `--platform linux` 两面）/
    `tools.check_agents_md` 全绿，提交时 4 个 pre-commit hook 全过。
- **CI 终验结果（run 40183752144 @ `1c5e25a`，结论 success，21 个 job 全绿）**：
  - `extras (macos-latest, py3.12)`：修复后连续两轮全绿——run 40183752144 测试步 **380s** /
    job 全程 **661s**，run 40186485850 测试步 **375s** / job **681s**；对比修复前两轮
    「881s 未完」与「2091s 未完」双双被 runner 杀掉。`Coverage gate (hard floors)` 真实通过（1s）。
  - **ubuntu 侧无可测变化，且本来就不该有**（本条初稿写成「ubuntu 也从 404s 顺带降到 302s」，
    是把跨运行噪声当成了因果，已订正）：四个样本 ubuntu 测试步依次为 306 / 404（修复前）、
    302 / 382（修复后），同一个 ±30% 区间。机理正是 **Linux 默认 fork、worker 不重新导入本模块**，
    那笔 import 税只在 spawn 平台（macOS/Windows）存在——所以「ubuntu 也变快」在机制上不成立，
    而「macOS 从跑不完变成 375~380s 完成」才是本次修复的唯一有效对照。
  - **倍率回归**：macOS→ubuntu 由 ≥5.2 倍（2091s 未完对 404s 的下界比值）回到 **~1 倍量级**
    （380/302 = 1.26、375/382 = 0.98，两批 ubuntu 样本本身就在飘）。平台异常消失，佐证根因
    定位正确：从来不是「macOS 慢」，而是「装上 extras 之后每个 spawn worker 多付一遍 import」。
  - `coverage-extras-macos-latest-py3.12` 与 `junit-extras-macos-latest-py3.12` **首次真实生成**
    （该 run 产物 26 → 28 条），macOS 侧可选模块覆盖率自此可比、可取证。
  - `benchmark` job（同 SHA）结论 **success**：±15% 均值回归门禁未被本次改动触发。
  - **预估 vs 实测（如实记账）**：预估「测试步 ~10 分钟」，实测 380s = 6m20s，**偏保守约 1.6 倍**；
    预估「倍率回落到 ~1.46 倍」，实测 1.26 倍，方向正确、幅度更优。据此把 40 分钟重新定性为
    **刻意留的余量天花板（约 3.6 倍 headroom），不是实测需求**——`ci.yml` 注释与契约常量文案已按此
    订正，并要求「起点 40107357212 / 证伪 40174423841 / 实测 40183752144」三个 run 号同时在场，
    缺任何一个判红。**未**下调 `timeout-minutes`：下调省不了任何墙钟时间（腿自己只要 11 分钟），
    却会把未来的用例增长重新变成超时分母——那是净风险、零收益。
- **仍然只能由 CI 终验**（不以本地绿冒充远端绿）：
  - 承接 §4.10：extras-health 链路（rc 管道 + `charts` + `weekly-report`）的首次真实执行仍是
    今晚 19:17 UTC 定时的观察项，与本条独立。
- **需如实记下的口径变化**：可选依赖探测时机从「import 期」推迟到「装配 `HybridScorer` 时」。
  §3.11 的代价没有消失，只是从「收集期打死 session」变成「运行期崩在评分入口」；
  `tests/test_portrait_import_guard.py` 与 `portrait_engine.py` 里描述崩溃链的注释已同步订正，
  不留「注释说谎」。

