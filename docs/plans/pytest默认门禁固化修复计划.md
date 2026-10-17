# pytest 默认门禁固化修复计划（审查项 M-17）

> 状态：已完成（2026-09-06，实测记录见文末「执行结果」）
> 任务类型：增强类（默认过滤此前不存在，新增用例在改动前因功能不存在而失败）
> 背景：审查报告 `docs/review/代码质量与架构审查报告.md:847` M-17——默认 `pytest` 不排除 e2e / slow / bench_full，CI 与本地口径靠手工参数维持；:857 修复方向、:1722 汇总表建议的 CI 裸跑校验一并落地。
> 来源标注：该审查报告为本地一次性产物，被 `.gitignore` 的 `/docs/review/` 规则忽略、不随仓库分发；引用的行号（:847/:857/:1722）在报告本地版本上成立。落地证据以 `pyproject.toml` addopts、ci.yml 裸跑门禁步骤与 `CHANGELOG.md` M-17 条目为准。
> 批注（2026-10-17）：本文「执行结果（实测）」表里的 `1076/1086 collected (10 deselected)` 与 §5 第 121 行的反例已过时——`tests/test_cli_e2e.py` 现已加模块级 `pytestmark = [pytest.mark.e2e]`（`tests/test_cli_e2e.py:19`），默认口径下排除数由 10 增至 38（现值 `1058/1096 collected (38 deselected)`）；同段的另一反例 `tests/test_cli_terminal_e2e.py` 仍无 marker、仍被默认收集（7 项），该反例成立。原文按其完成日期保留，不改写。

## 〇、结论先行

在 `pyproject.toml` 固化 `addopts = '-m "not e2e"'` 与 `testpaths = ["tests"]`，使「裸跑 pytest = tests/ 全量且不含浏览器 e2e / benchmarks」成为机器可执行的单一定义；同步给 `ci.yml` 两个 e2e job 补 `-m "e2e"`、加 Makefile `test`/`test-all` 入口、加 CI collect-only 裸跑门禁、同步 README/CHANGELOG。**不采用 M-17:857 原文示例**（`not bench_full` + `--ignore=tests/e2e`），原因见「一、5」与「八」。

## 一、现状摸底

### 1. 结构清单
- `pyproject.toml:125-130`：`[tool.pytest.ini_options]` 仅有 `markers`（slow/e2e/bench_full），**无 addopts、无 testpaths**。L132-134 注明覆盖率配置刻意留在 `.coveragerc`，不进 pyproject。
- `tests/`：conftest.py + 34 个 test_*.py + `tests/e2e/`（conftest.py + test_webui_e2e.py，无 `__init__.py`）。顶层另有独立 `benchmarks/`（3 个 bench 文件）。
- `.github/workflows/`：ci.yml、benchmark.yml、release.yml、extras-health.yml、security.yml。`Makefile`（48 行，无 test 目标）。`docs/plans/`（10 份正式计划）、`docs/review/代码质量与架构审查报告.md`。非 git 仓库。

### 2. 对外契约（测试调用口径，全部带出处）
- **marker 分布**：`e2e` 仅 `tests/e2e/test_webui_e2e.py:32`（模块级 `pytestmark = [pytest.mark.e2e]`，共 10 例，tests/e2e 之外零使用）；`slow` 全仓 7 处（test_hybrid_scorer.py:1013/1486/1559、test_webui.py:202、test_webui_components.py:480/499/510）；`bench_full` 全仓仅 `benchmarks/test_batch_bench.py:47`。
- **e2e 收集防护**：`tests/e2e/conftest.py:18-19` 顶层 `pytest.importorskip("gradio")` / `importorskip("pytest_playwright")`——无 e2e 依赖时整个目录在收集期优雅跳过。
- **文档口径**：README.md:560/1215 `pytest tests/ -v --cov=flashgaze --cov-report=term-missing`；README.md:581-584/1236-1239 e2e 显式命令与 `pytest tests/ -m "not e2e"`；README.md:591/1246 `pytest benchmarks/ -m "not bench_full"`；README.md:594/1249 明言「pytest tests/ never collects benchmarks/」；docs/plans/门禁与回归验证计划.md:46-48「三条门禁唯一口径」；docs/bench/README.md:70。

### 3. 依赖方（谁在调用 pytest、改动会影响谁）
- ci.yml:54-57 主矩阵与 extras-health.yml:63-68：`pytest tests/ ...` **不带 -m**——e2e 目前靠 importorskip 跳过；加默认 `-m "not e2e"` 后变为 deselected，结果/覆盖率等价，**无需改动**。
- ci.yml:289/324 e2e job：`pytest tests/e2e --browser X` 不带 -m——加默认后 10 例全部 deselected → exit 5 → **job 假红，必须补 `-m "e2e"`**（CLI `-m` 后者覆盖前者，语义确定）。
- benchmark.yml:93/106/113 非 nightly 传 `-m "not bench_full"`（CLI 覆盖默认，不变）；**benchmark.yml:107-110 nightly 分支 `MARKER_ARGS=()` 刻意传空以包含 bench_full**——若默认含 `not bench_full` 会静默废掉 nightly；且 benchmarks/ 无 e2e marker，`-m "not e2e"` 对其零影响 → 本方案下 nightly 零改动。
- release.yml:243 `-m "not slow and not e2e"`：CLI 覆盖默认，不变。
- README 双语 e2e 显式命令（581-583/1236-1238）：加默认后裸跑 `pytest tests/e2e` 将 0 selected（exit 5）→ **需补 `-m "e2e"` 并说明默认口径**。

### 4. 验证能力
- **A 档**：pytest 存在（pyproject.toml:125-130），本机有 pytest 运行痕迹（.pytest_cache/、_pytest_full.log）。ruff/mypy/pre-commit 均配置（pyproject:139-211、.pre-commit-config.yaml）。pytest-timeout **缺失**（门禁计划:55 明文未安装，用例自带看门狗，与本改动无关）。GitHub Actions 无法本地执行 → CI 改动只能静态验证，如实标注。
- 环境注意：中文路径工作区，pytest 全量须带 `PYTHONIOENCODING=utf-8`（Windows 中文环境下控制台默认 GBK 编码，pytest 回显含中文的用例名/断言信息会抛 `UnicodeEncodeError`，跑全量前先设该环境变量；此约定原记于本地一次性 M16 计划文档，该文档存放于 gitignore 的 `_plans/`，2026-10-17 已归档摘除，不随仓库分发）。

### 5. 历史约束 / 偏离 M-17 原文示例的理由
- **弃用原文示例的两个硬约束**：① `--ignore` 一旦写入 addopts 无法用 CLI 旗标解除（只能 `-o addopts=` 整体重写），且其对「显式传入路径」是否生效依版本而定，会波及 README/CI 的 e2e 直跑命令；② `not bench_full` 进 addopts 会静默破坏 benchmark.yml:109 nightly（该分支不传 -m）。而 bench_full 只在顶层 benchmarks/，`pytest tests/` 永不收集，裸跑 pytest 触及 benchmarks 的问题由 `testpaths=["tests"]` 兜住 → 默认只需 `-m "not e2e"`。
- `slow` **不进默认排除**：ci.yml 主矩阵现无任何过滤，slow 用例参与覆盖率门禁（fail_under=80），默认排除可能击穿 80% 门禁；保持现状（显式 `-m "not slow"` 按需排除），与现有唯一口径一致。
- `.codebuddy/plans/PLAN-H10-*.md:80` 曾出现「默认 addopts 已排除」的预期表述——本次是兑现该预期。

## 二、子任务分解（增强类：改动前用例因功能不存在而失败，红灯证据即 Node 1 基线）

**Node 0：计划落盘** —— 新增本文件。验收：文件存在且含现状摸底/子任务/验收标准全部章节。

**Node 1：基线采集（红灯证据，只读不改）**
- 运行并记录：`python -m pytest tests/ --collect-only -q`（预期含 10 条 tests/e2e 条目）、`python -m pytest --collect-only -q`（无参，预期混入 benchmarks/ 条目）、`python -m pytest benchmarks/ --collect-only -q`（含 bench_full）。同时验证 `python -m pytest --version` 环境可用。
- 验收：三类输出落盘；e2e 条目在默认收集中出现 = 红灯成立。

**Node 2：pyproject.toml 固化默认**
- 修改 `pyproject.toml:125-130`：在 markers 前新增（TOML 字面量字符串）：
  ```toml
  # 默认门禁口径（审查项 M-17）：裸跑 pytest 只收集 tests/ 且排除 e2e；
  # 显式跑 e2e 用 -m "e2e"（CLI -m 覆盖本默认）；解除默认过滤用 -o addopts=。
  # benchmarks/ 为顶层独立目录，tests/ 收集永不触及；bench_full 由 benchmark.yml 自行过滤。
  addopts = '-m "not e2e"'
  testpaths = ["tests"]
  ```
- 转绿验收：① 无参 `pytest --collect-only -q` 输出零 e2e、零 benchmarks 条目；② `pytest tests/ --collect-only -q` 条目数 = 基线 − e2e 数；③ `pytest tests/e2e --collect-only -q -m "e2e"` = 10 条；④ `pytest benchmarks/ --collect-only -q`（无 -m，模拟 nightly）仍含 `test_score_batch_full_100`；⑤ `pytest tests/ -m "not slow and not e2e" --collect-only -q`（模拟 release）正常；⑥ 反例：`tests/test_cli_e2e.py`、`tests/test_cli_terminal_e2e.py`（名字带 e2e 但无 marker）仍被默认收集。

**Node 3：ci.yml e2e job 补 marker + 裸跑门禁**
- 修改 `.github/workflows/ci.yml:289`、`:324`：命令追加 `-m "e2e"`（置于 `--browser` 前），并同步 :294-295 的本地注释行。
- 在 test job 覆盖率步骤后新增（复用 :61 的单腿条件写法）：
  ```yaml
      # M-17：裸跑 pytest 默认口径校验——空参收集必须不含 e2e/benchmarks，
      # 防止 addopts/testpaths 默认过滤被悄悄回退（collect-only 秒级）。
      - name: Bare pytest default gate (collect-only)
        if: matrix.os == 'ubuntu-latest' && matrix.python-version == '3.13'
        run: |
          python -m pytest --collect-only -q > /tmp/bare-collect.txt
          ! grep -q "tests/e2e" /tmp/bare-collect.txt
          ! grep -q "benchmarks" /tmp/bare-collect.txt
  ```
- 验收：grep 确认两处 e2e 命令含 `-m "e2e"`、新 step 存在；YAML 语法用 PyYAML 解析校验（不可用则如实标注「语法未本地校验，人工核对」）。CI 实际执行标注「未验证（需 CI 首跑）」。

**Node 4：Makefile 统一入口**
- 修改 `Makefile`：`.PHONY` 加 `test test-all`；新增：
  ```make
  test:
  	python -m pytest tests/ -q

  test-all:
  	python -m pytest tests/ -q -o addopts=
  ```
  头部注释清单（:6-14）补两行说明。`test-all` 用 `-o addopts=` 清空默认过滤 → e2e 依赖缺失时经 importorskip 优雅跳过（exit 0）。
- 验收：`make -n test` / `make -n test-all` 输出正确命令；`python -m pytest tests/ --collect-only -q -o addopts=` 含 e2e 10 条（证明 override 生效；若不生效，回退为 `-m ""` 并在此记录）。

**Node 5：文档同步（README 双语 + CHANGELOG）**
- 修改 `README.md:576-584` 与中文镜像 `1211-1239`：e2e 三条命令补 `-m "e2e"`；`pytest tests/ -m "not e2e"` 行注明「此为内置默认，显式写出仅为兼容旧口径」；560 命令块后补默认口径说明（addopts/testpaths、覆盖方法 `-m`/`-o addopts=`、`make test`/`make test-all`）。
- 修改 README.md:563 / 1218 测试规模句：以 Node 6 实测数字改写（默认收集数、e2e 10 例改由 `pytest tests/e2e -m "e2e"` 单独运行）。
- 修改 README.md Local Code Quality Guard 节（约 :637/:1292）：补 make test / test-all 提及。
- 修改 `CHANGELOG.md`：按既有格式在 Unreleased/Fixed 下加 M-17 条目。
- 验收：文档中每条示例命令逐条实跑或 `--collect-only` 验证可复现（C 档样例回放标准，≥3 条含 1 条反例）。

**Node 6：全量回归 + 记录回填**
- `PYTHONIOENCODING=utf-8 python -m pytest tests/ -q`（默认口径全量实跑，与 Node 1 基线比对）。
- `PYTHONIOENCODING=utf-8 python -m pytest tests/ -q --cov=flashgaze --cov-report=term-missing`（README 口径，验证 fail_under=80 仍通过）。
- `python -m ruff check .`、`python -m ruff format --check .`、`python -m mypy`（无参，唯一口径）。
- 验收：全部通过或如实标注环境性缺失；执行结果（实测）回填本文件与 Node 1 基线对照表。

## 三、依赖声明
无新增外部/平台依赖，无版本变更。前置环境：本机 Python + requirements-dev 已装（Node 1 首验 `python -m pytest --version`；缺失则停在该节点如实报告，不伪造）。

## 四、启动说明
环境准备：无需新装任何东西。验证方式（A 档为主）：collect-only 断言（Node 2 五项+反例）→ 全量实跑 + 覆盖率门禁 + ruff/mypy（Node 6）；CI yml/Makefile 为静态验证并如实标注。全仓命令统一加 `PYTHONIOENCODING=utf-8`。

## 五、错误处理
- TOML 语法错误：pytest 启动即报错，Node 2 的 collect-only 天然覆盖。
- YAML 语法：本地 PyYAML 解析 best-effort，不可用则标注人工核对 + CI 首跑兜底。
- `-o addopts=` 若实测不覆盖 addopts：回退 `-m ""`（空 markexpr 不过滤），在本文档记录。
- exit 5（no tests collected）语义写进 README 提示：`pytest tests/e2e` 忘加 `-m "e2e"` 时即出现，属预期防护而非故障。
- 日志：无新增日志面；验证输出记录于本文档「执行结果（实测）」。

## 六、参数校验
本次仅改 pytest 配置与文档，无运行时入参。固化值校验：`addopts` 必须是 TOML 字面量字符串（单引号包双引号）；`testpaths` 相对 rootdir；覆盖规则明示——CLI `-m` 最后生效（覆盖默认时需自带全部排除项，如 release.yml 现有写法）、`-o addopts=` 整体清空、无路径参数时 testpaths 才生效。

## 七、基础测试用例（A 档，全部为 collect-only/实跑断言）
1. 正常：无参 `pytest --collect-only -q` 只含 tests/ 且无 e2e/benchmarks 条目。
2. 正常：`pytest tests/e2e --collect-only -q -m "e2e"` = 10 条（CI e2e job 等价路径）。
3. 边界：`pytest benchmarks/ --collect-only -q`（无 -m，模拟 nightly）仍含 `test_score_batch_full_100`。
4. 边界：`pytest tests/ -m "not slow and not e2e" --collect-only -q`（模拟 release）slow 7 例被排除、其余不变。
5. 反例：`tests/test_cli_e2e.py`、`tests/test_cli_terminal_e2e.py` 名含 e2e 但无 marker，必须仍被默认收集（防将来误用文件名过滤）。
6. 反例：`pytest tests/e2e`（不带 -m）→ 0 selected / exit 5，作为预期行为变更点记录于文档。

## 八、影响面与兼容性
- 定性：**非破坏性行为增强** + 两处必须的配套修正（ci.yml e2e job、README e2e 命令），无接口/签名变化，无文件删除。
- 逐项：ci.yml 主矩阵与 extras-health 行为等价（e2e skip→deselect，覆盖率不变）；release.yml/benchmark.yml/门禁文档命令经 CLI 覆盖语义均不变；nightly 全量基准不受影响；benchmarks 独立目录承诺不变。
- 新增行为契约：本地脚本若用自定义 `-m`（如 `-m slow`）会连默认排除一起覆盖，需自行写全排除项——README 明示；`make test-all` 提供全量逃生口。
- 防退化：Node 1 全部基线断言在 Node 6 复跑必须保持；README 规模句以实测数字为准，不沿用旧计数。

## 执行结果（实测）

环境：Windows + Git Bash，Python 3.12，pytest 9.1.1（Node 1 实测 `python -m pytest --version`）。全量命令均带 `PYTHONIOENCODING=utf-8`。

| Node | 结果 | 实测证据 |
|---|---|---|
| 0 计划落盘 | ✅ | 本文件创建，含全部章节 |
| 1 基线（红灯） | ✅ 红灯成立 | `pytest tests/` 收集 **1086** 条，其中 **10 条 tests/e2e**（`test_page_loads[chromium]` 等）；无参裸跑收集 **1095** 条 = tests/ + **9 条 benchmarks/**（含 `test_score_batch_full_100_2000x1500`）；`pytest benchmarks/` 收集 9 条含 bench_full —— 增强类红灯：默认过滤不存在时 e2e/benchmarks 均可被裸跑触达 |
| 2 pyproject 固化 | ✅ 全部转绿 | ① 无参裸跑：`1076/1086 tests collected (10 deselected)`，e2e 条目 grep=0、benchmarks 条目 grep=0；② `pytest tests/`：1076 条（=基线 1086−10）；③ `pytest tests/e2e -m "e2e"`：**10 条**；④ `pytest benchmarks/` 无 `-m`（模拟 nightly）：9 条仍含 bench_full；⑤ `-m "not slow and not e2e"`（模拟 release）：1068 条（18 deselected = 10 e2e + 8 slow 条目）；⑥ 反例a：`test_cli_e2e.py`/`test_cli_terminal_e2e.py`（名含 e2e 无 marker）仍被默认收集；⑥ 反例b：`pytest tests/e2e` 不带 `-m` → `no tests collected (10 deselected)`，**exit=5**（预期防护） |
| 3 ci.yml | ✅（静态） | 两处 e2e run 命令（ci.yml:300、:335）与两处本地等价命令注释均含 `-m "e2e"`；`Bare pytest default gate (collect-only)` step 落位于 test job（:84-90，断言收紧为节点 ID 形态 `tests/e2e/.*::`，兼容无 e2e 依赖环境的 importorskip 输出）；PyYAML 解析通过且断言 3 处结构成立；门禁 bash 逻辑本地模拟通过。**CI 实跑未验证（需 CI 首跑）** |
| 4 Makefile | ✅（部分静态） | `test`/`test-all` 目标新增，recipe TAB 缩进与原文件 CRLF 风格一致（cat -A 核对）；`-o addopts=` 覆盖机制实测生效：`pytest tests/ --collect-only -q -o addopts=` = **1086 条（含 e2e 10）**，无需回退 `-m ""`。**本机无 make（command not found），`make -n` 干跑未验证**（Makefile:17 已注明该场景的替代用法） |
| 5 文档同步 | ✅ | README 中英双语 Testing 节、Makefile 段与 CHANGELOG「修复」条目在会话内完成主体（默认口径段、1076/1048/28 实测数字、e2e 命令补 `-m "e2e"`、覆盖规则）；本会话补齐 README:431 英文口径句（`--browser` 传给 `pytest tests/e2e -m "e2e"`）。注：README 双语主体与 CHANGELOG 条目系执行期间在会话外同步完成（与实测数字一致，逐条核对无误），非本会话逐字产出 |
| 6 全量回归 | ✅ | ① 默认口径全量实跑：**1048 passed / 28 skipped / 10 deselected，7:30**（collect 集合 = 基线 − e2e 10 条，未触碰的 .py 为零，通过集合无退化）；② 覆盖率门禁（README 口径 `--cov=flashgaze --cov-report=term-missing`）：**总覆盖 90.32%，Required test coverage of 80.0% reached，exit=0**，7:41；③ `ruff check .` All checks passed；④ `python -m mypy`（无参）Success: no issues found in 77 source files |

ruff format --check 说明：报告 44 处待重排，全部位于 `.codebuddy/plans/*.md`、`.zcode/plans/*.md` 与既有 `docs/plans/删除不可逆修复计划.md` 等本地 markdown 内嵌代码块——本次改动未触碰任何 .py 文件，也未触碰上述任何文件，属改动前既有状态，与本次无关。

未验证项（如实标注）：
- GitHub Actions 实跑（ci.yml e2e job 的 `-m "e2e"`、裸跑 collect-only 门禁步骤、主矩阵行为）——本地无法执行，待 CI 首跑确认；
- `make -n test` / `make -n test-all` 干跑——本机无 make；
- pytest-timeout 缺失（既有状态，本改动不涉及）。

防退化对照：Node 1 全部基线断言在改动后复验保持（基线1→验收②：集合恒等仅减 e2e；基线3→验收④：benchmarks 收集与 bench_full 在场不变）；既有文档口径 `pytest tests/ -m "not e2e"`、`pytest benchmarks/ -m "not bench_full"`、release.yml `-m "not slow and not e2e"` 经 CLI 覆盖语义逐条实测有效。
