# 覆盖率门禁纳入主门槛与 extras 硬门槛修复计划（审查项 M-12）

> 状态：**已完成（2026-09-06）**。每个子任务「红灯 → 改 → 绿灯」闭环后才进下一步；本文档为唯一执行依据，「执行结果（实测）」表已回填。
> 原则：只改与问题直接相关的代码与文档；不改动任何产品代码、不改 MCP 工具签名（mcp_server.py:45-48 对外契约）；主门禁 `fail_under = 80` 数值不变；不新增第三方依赖。
> 任务出处：`docs/review/代码质量与架构审查报告.md` M-12（L728-738 正文、L1717 回填表）；方案经用户确认**两者都做**——① `mcp_server.py`、`webui/app.py` 移出 omit 纳入主 80% 门禁（主 CI 矩阵加装 mcp extra）；② extras job 改为阻塞式硬门槛（总 fail_under=50 + 逐模块下限），杜绝「只报告不设门」。
> 类型标注：缺陷修复类（门禁失效）+ 增强类（test_cleanup 守卫、契约测试）。

## 一、现状摸底（开工前只读核实）

**结构清单**：项目根 `D:\Qoder项目\SaiTu skill`（非 git 仓库）。`flashgaze/` 36 个 .py 约 11,193 行；被 `.coveragerc:18-23` omit 的五模块合计 2,227 行（约 20%）：

| 模块 | 行数 | 依赖 | import 副作用 | 既有测试 |
|---|---|---|---|---|
| mcp_server.py | 897 | mcp（硬 import :24） | 实例化 FastMCP + 注册 5 工具，无服务启动 | test_mcp_server.py（1461 行，importorskip mcp）+ test_cleanup.py 8 用例（**裸导入无守卫**） |
| webui/app.py | 963 | gradio（懒加载 :248/:924） | 无 | test_webui*.py（主矩阵跑纯逻辑部分） |
| core/xlsx_exporter.py | 86 | openpyxl（硬 import） | 实例化样式常量（良性） | test_xlsx_exporter.py（200 行，importorskip） |
| core/deduplicator.py | 172 | imagededup（try/except 软探测） | 无 | test_dedup.py（362 行，stub 契约用例无守卫照跑） |
| core/portrait_engine.py | 109 | face_recognition（软探测）；cv2/numpy 为基础依赖 | 无 | test_portrait.py（111 行，降级路径无守卫） |

**对外契约（门禁现状）**：主门禁 `.coveragerc:27` `fail_under=80`，由 ci.yml test job（3 OS × 4 Python）的 pytest-cov 消费（ci.yml:49-54，命令行无 --cov-fail-under）；extras job（ci.yml:161-226，ubuntu/macos × py3.12）装全部 extras，`--cov-config=.coveragerc-extras` 只报告；其 `--fail-under=50`（ci.yml:226）仅在 sentinel 锁 `.github/extras-strict.lock` 存在时执行——**锁文件当前不存在，且 job 级 `continue-on-error`（ci.yml:166）吞掉一切失败 → 实际零门禁**。`.coveragerc-extras` 无 fail_under，source 恰为 5 模块（必须保留 5 模块：tools/extras_health.py:36-42 的 MODULES 与 extras-health.yml 夜间任务依赖它）。codecov.yml patch/core（informational:false，target 80%）排除同样 5 模块（L24-28）。夜间 extras-health 按 R1-R5 管理 sentinel（tools/extras_health.py:54-63 与 docs/extras-governance.md L34-38 一致）。

**依赖方（口径消费方）**：ci.yml 三个 job、extras-health.yml、codecov.yml、README:565/:1220、docs/extras-governance.md（L8/L48/L83）、审查报告 L1717 回填表。

**验证能力**：pytest 9.x + pytest-cov（有）；ruff、mypy（严格，**必须无参**）门禁（有）；e2e 用 `-m "not e2e"` 排除（口径见 docs/plans/门禁与回归验证计划.md）；Makefile 无 test/coverage 目标（缺失，不新增）。本地 py3.12.10 已装 mcp/gradio/openpyxl/pytest/pytest-cov/coverage，**未装 imagededup/face_recognition**（dedup/portrait 的依赖相关行为覆盖只能在 CI extras job 出现——本地无法验证项如实标注）。pyproject extras：`mcp`(:71)/`gui`(:83)/`xlsx`(:87)/`dedup`(:75)/`portrait`(:74)；`all` 刻意不含 mcp 与 portrait（pyproject:90 注释），本次不改 pyproject。

**历史约束**：governance 5.3「主门禁 fail_under=80 与 5 模块 omit 规则一律不变」→ 本次按用户决策变更 omit，须同步修改该文档；CHANGELOG 为 Keep a Changelog，破坏性行为变更记入 `[未发布] ### 变更`。

## 二、实施步骤（红灯 → 改 → 绿灯闭环）

| 步骤 | 动作与文件 | 红灯/绿灯判定 |
|---|---|---|
| T0 | 本计划文件落库；基线：`python -m pytest tests/ -m "not e2e"`、`python -m ruff check .`、`python -m mypy`（无参） | 基线全绿才继续；数字记入实测表 |
| T1 | 修改 `tests/test_cleanup.py`：8 处裸 import（L576/601/634/874/901/1029/1129/1171）前加 `pytest.importorskip("mcp")`（对齐 test_mcp_server.py:20 先例） | 增强类红灯：临时阻断插件（PYTHONPATH 注入 `-p` 插件，置 `sys.modules['mcp']=None`）模拟无 mcp 环境 → 修复前 8 用例 error；修复后变 skip 且 0 error；正常环境 8 用例照常 pass |
| T2 | 本地度量（仓库文件不动，rc 放 %TEMP%）：a) 模拟新主矩阵（阻断 gradio、mcp 可用）+ 临时 rc（omit=3）全量覆盖率 → 主门禁新总率与 mcp_server/app 实测率；b) 无阻断跑 extras 口径 → 5 模块实测率 | 决策规则：主矩阵安装集 = `.[mcp]`；总率 <80 → `.[mcp,gui]` 重测；仍 <80 → tests/test_webui.py 追加 app.py 纯逻辑函数单测后重测；仍 <80 → 停止上报实测数字（**不降低 80**）。逐模块下限：T_i = int(实测_i) − 5，下限 55，且 ≤ 实测−2 |
| T3 | 新增 `tests/test_coverage_gate_contract.py`（纯 stdlib configparser + 文本断言） | 缺陷修复类红灯：对旧配置运行 → 多组断言失败，记录输出 |
| T4 | 配置四件套：① `.coveragerc` omit 删 mcp_server.py、webui/app.py + L14-17 注释改写；② `.coveragerc-extras` 加 `fail_under = 50` + 头注释改写（source 保持 5 模块）；③ ci.yml：test job 安装 `pip install -e ".[mcp]"`（或 T2 决策的 `.[mcp,gui]`）；extras job 删 L166 job 级 continue-on-error、pytest 步骤加步级 `continue-on-error: true`、新增无条件 `Coverage gate (hard floors)` 步骤（总 50 + 逐模块 --include/--fail-under 三行）、L224 sentinel 严格步骤原样保留；④ codecov.yml 删 L24-25 两行排除 | 契约测试转绿；全量 pytest 复跑无回归 |
| T5 | 门禁生效实证（.coverage.main/.coverage.extras + --data-file 切换）：主 rc 报告 exit 0 且含 mcp_server/app 行；extras rc 总报告 exit 0；`--include=flashgaze/mcp_server.py --fail-under=99` 反例非零退出 | 三条命令退出码符合预期 |
| T6 | 文档同步：README:565/:1220（及 L572/L1227 若涉及）；docs/extras-governance.md L8/L48/L83；审查报告 L1717 M-12 标 ✅ + 证据（L1784 索引同查）；CHANGELOG [未发布]###变更 两条（均标破坏性） | grep 无「只报告不设门/report-only」对 mcp_server/app 的残留 |
| T7 | 全量回归：pytest `-m "not e2e"` 0 failed；ruff=0；mypy（无参）=0；契约测试随套件通过 | 全绿；失败当场修复或如实报告 |

## 三、依赖声明

| 依赖 | 用途 | 来源 | 说明 |
|---|---|---|---|
| Python 3.12.10（本机） | 运行时 | pyproject requires-python >=3.10 | 已装 |
| pytest/pytest-cov/coverage | 回归 + 度量 | requirements-dev.txt | 已装 |
| ruff / mypy | lint / 类型门禁 | requirements-dev.txt | 已装；mypy 必须无参 |
| mcp>=1.2.0,<2.0.0 | mcp_server 可导入 | pyproject extra `mcp`（CI 主矩阵新增安装；本机已装） | 纯 Python 包 |
| imagededup / face_recognition | dedup/portrait 完整行为覆盖 | extras `dedup`/`portrait` | **本地不装**（torch/dlib 过重），CI extras job 才有——相关验收标注「待 CI 确认」 |

**无新增第三方依赖**：契约测试只用 stdlib（configparser + 文本断言）；阻断插件为临时 stdlib 文件放 %TEMP%，不入仓库。

## 四、启动说明

```bash
# 工作目录 = D:\Qoder项目\SaiTu skill
python --version            # 3.12.10
python -m pytest --version && python -m ruff --version && python -m mypy --version

# 全量回归唯一口径（不带 --cov，避免与门禁验证互相干扰）
python -m pytest tests/ -m "not e2e"

# 门禁验证（T5；数据文件由 T2 度量产出）
python -m coverage report --rcfile=.coveragerc --data-file=.coverage.main
python -m coverage report --rcfile=.coveragerc-extras --data-file=.coverage.extras
python -m coverage report --rcfile=.coveragerc-extras --data-file=.coverage.extras --include="flashgaze/mcp_server.py" --fail-under=99   # 反例，应非零退出
```

## 五、错误处理
- ci.yml 语法风险：改后若本机 pyyaml 可用则 YAML 解析自检，否则标注「语法自检未验证，依赖契约测试文本断言 + CI 首跑」。
- 门禁触发时的用户可见信息：coverage report 开 `show_missing`，失败输出直接列未覆盖行；契约测试失败消息注明「改门槛/omit 必须同步更新本测试与 README/extras-governance 文档」。
- 降级：T2 决策规则走到「仍 <80」终点即暂停上报，不弱化门槛、不静默回退。

## 六、参数校验
契约测试内置：fail_under 为 int 且主=80、extras≥50；T_i 为 int 且 55 ≤ T_i ≤ 实测−2；ci.yml 断言逐行锚定（extras job 片段内不得出现 job 级 `continue-on-error`；gate 步骤不得被 `if: ...strict` 条件化）。

## 七、契约测试用例（正常/异常/边界/反例）
- 正常：新配置全部断言通过（主 fail_under=80；omit={xlsx_exporter,deduplicator,portrait_engine}；extras fail_under≥50 且 source 含 5 模块；ci.yml 安装含 `.[mcp]`；gate 步骤存在且无条件；codecov 不再排除 mcp_server/app）。
- 异常：extras fail_under 缺失或 <50 → 失败；gate 步骤被 strict 条件化 → 失败；job 级 continue-on-error 回归 → 失败。
- 边界：T_i = 55 / 实测−2 合法。
- 反例（不应命中）：`flashgaze/core/cleanup.py` 等核心模块出现在 omit → 失败（防主门禁被掏空）；mcp_server/app 回到 omit → 失败（防本修复被静默回退）。

## 八、影响面与兼容性
破坏性（工作流层面，记 CHANGELOG）：① 主矩阵 12 腿新增安装 mcp（轻量）；若 T2 决策选中 `.[mcp,gui]` 再增 gradio（+~1min/腿）；② mcp_server/app 纳入主 80% 考核与 Codecov patch/core 强制状态；③ extras job 从「失败不阻塞」变「低于硬下限即阻塞」（下限=实测−5，当前 HEAD 必然通过，即过渡方案）；extras 测试自身不稳定仍不阻塞（步级 continue-on-error 保留），sentinel/夜间机制语义不变。不破坏：产品代码零改动、MCP 工具签名零改动、pyproject 与 `all` extra 语义零改动、check-strict/extras-health/codecov flags 结构不变。部署前提（本地无法验证，如实标注）：CI 首跑确认 mcp 在 py3.10–3.13 可安装、CI 总覆盖率达标、extras gate 通过；建议管理员将 extras job 设为 required check。

## 执行结果（实测）

> | 任务 | 验收命令 | 结果 |
> |---|---|---|
> | T0 基线 | pytest 全量 / ruff / mypy | **1031 passed, 28 skipped, 0 failed（7:40）**；ruff 0 错；mypy 0 错（76 文件）✅ |
> | T1 守卫 | 阻断插件模拟无 mcp（`-p no_mcp_blocker`）+ 正常环境复跑 | 修复前 **8 failed**（ModuleNotFoundError，红灯）；修复后无 mcp 环境 **73 passed, 8 skipped, 0 error**、正常环境 **81 passed**（8 用例照常通过，既有场景未失效）✅ |
> | T2 度量 | 两口径全量覆盖率 | 主矩阵模拟（阻断 gradio + omit=3 临时 rc）：**86.62% ≥ 80**（990 passed, 33 skipped）→ 按决策规则主矩阵安装集定为 `.[mcp]`，无需 gui；extras 口径（全部测试激活）行覆盖：`mcp_server` **87.71%** / `webui.app` **85.77%** / `xlsx_exporter` **100%** / `deduplicator` 52.33% / `portrait_engine` 47.62%（后两者本地缺 imagededup/face_recognition，CI extras 会更高）；逐模块下限按 int(rate)−5 定为 **82 / 80 / 95** |
> | T3 红灯 | `pytest tests/test_coverage_gate_contract.py`（对旧配置） | **6 failed, 2 passed**（omit 含 5 模块 / extras 无 fail_under / 主矩阵未装 mcp / job 级 continue-on-error 存在 / 无硬门禁步骤 / codecov 未收窄）✅ |
> | T4 绿灯 | 同上（对新配置） | **8 passed** ✅（中途两轮断言自修正：gate 步骤 marker 精确到 `- name:` 行避免撞注释、`if: always()` 判定为无条件保障而非条件化）；ci.yml/codecov.yml 经 pyyaml 6.0.3 语法自检通过 |
> | T5 门禁实证 | `coverage report --data-file` 各退出码 | 主门禁（fail_under=80）**EXIT=0**（总 87%，`mcp_server` 86% / `webui\app` 22%（主矩阵模拟无 gradio，符合预期）均入报告）；extras 总下限 50（5 模块 include）**EXIT=0**；逐模块 82/80/95 全 **EXIT=0**；反例 `--fail-under=99`：mcp_server **EXIT=2**、webui/app **EXIT=2**（`Coverage failure: total of 86 is less than fail-under=99`，门禁真实失败）✅ |
> | T6 文档 | grep 旧口径残留 | README 中英双语「Testing/测试」门禁段改写；`docs/extras-governance.md` 防线表（新增硬门槛行）/闭环图/5.3 blast radius 改写；审查报告 L1717 回填行与 L1784 索引行标 ✅；CHANGELOG `[未发布] ### 变更` 新增一条（按既有风格合并为一个改动包，标破坏性变更）；grep 确认无残留（security.yml 的 report-only 属 dev 依赖安全审计语境，与覆盖率门禁无关）✅ |
> | T7 回归 | pytest / ruff / mypy | **1039 passed, 28 skipped, 0 failed（7:41）**（基线 1031 passed 全部保持 + 新增 8 条契约测试；28 skipped 与基线一致）；ruff check 0 错；ruff format（新文件）合规；mypy **0 错（77 文件）** ✅ |
>
> ### 未验证项（如实标注）
> - **GitHub Actions 实跑**：本地无法执行远端 CI。待推送后首跑确认：① `mcp>=1.2.0,<2.0.0` 在 py3.10–3.13 全矩阵可安装；② CI 环境总覆盖率 ≥80（本地模拟 86.62% 有 6.6pt 余量）；③ extras job 硬门禁步骤在 ubuntu/macos 通过。
> - **deduplicator / portrait_engine 完整行为覆盖**：本地未装 imagededup/face_recognition（torch/dlib 过重），二者依赖相关行为测试只能在 CI extras job 激活；本地实测 52.33% / 47.62% 仅为降级路径口径，故未设逐模块下限（由总下限 50 + 夜间 R1/R4 治理兜底，后续可按 CI 观测上调）。
> - **required check 设置**：extras job 现为阻塞门禁，但是否已加入 GitHub 分支保护 required checks 属仓库设置，仓库内无法设置/验证，需管理员确认。
