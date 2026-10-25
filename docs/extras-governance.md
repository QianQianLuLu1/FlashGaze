# FlashGaze 可选模块长期监控与治理规范

> 配套文件：`.github/workflows/extras-health.yml`、`tools/extras_health.py`、`codecov.yml`、`ci.yml`（`check-strict` job）。
> 适用范围：5 个可选模块 `mcp_server` / `webui.app` / `core.xlsx_exporter` / `core.deduplicator` / `core.portrait_engine`。

## 1. 为什么要治理可选模块

主 CI 的 `test` 门禁（`fail_under=80`）只 `omit` 依赖重型/可选包的 **3 个模块**（`core.xlsx_exporter`、`core.deduplicator`、`core.portrait_engine`）；`mcp_server`、`webui/app`（含 `exif_writer`）自 2026-09 起随主矩阵加装 `mcp,gui,exif,heic` 轻量 extras 纳入主门禁（M-12 修复；缺依赖时对应测试跳过、门禁失真，实测仅装 `mcp` 时总覆盖率 79.31% 不达标，故其运行依赖一并进主矩阵）。这 3 个重依赖模块由 `extras` job **硬门槛**强制：`.coveragerc-extras` `fail_under=50` 总下限 + `ci.yml` 逐模块下限，覆盖率不达标**阻塞合并**。

这套硬门槛保障了主流程交付效率，但历史教训是：`extras` job 曾长期「只报告不设门」（`continue-on-error` 吞掉一切失败），可选模块的覆盖率下滑被静默忽略。因此在本门槛之上叠加**旁路定时治理流水线**，实现「看得见、可告警、能升级、会自愈」。

## 2. 三道防线总览

| 防线 | 机制 | 是否阻塞 PR | 触发频率 |
|---|---|---|---|
| 可视化 | Codecov `extras-*` flag（informational）+ gh-pages 趋势图 + 每周 Issue 摘要 | 否 | 每次 PR / 每日 / 每周一 |
| 告警 | `extras-health.yml` 判定命中 → 自动建/更新清理 Issue（标签 `extras-health`） | 否 | nightly |
| 硬门槛 | `extras` job `Coverage gate (hard floors)`：5 模块总下限 50% + 逐模块下限（M-12） | **是（始终）** | 每次 PR |
| 加严升级 | 临界命中 → 写 `.github/extras-strict.lock` → `ci.yml` 读锁后 strict 步骤把总下限抬到 60 | **是（临时）** | nightly |

定时治理线通过单一事实 `.github/extras-strict.lock` 解耦：定时任务**写锁**，`ci.yml` 的 `check-strict` job **读锁**，互不耦合、可独立演进；硬门槛防线不依赖锁，`tests/test_coverage_gate_contract.py` 锁定其配置契约防退化。

### 2.1 逐模块下限取值基线（M-12 硬门槛溯源）

`ci.yml` 的 `Coverage gate (hard floors)` 里 `--fail-under=82 / 80 / 95` 三行不是自选数字，规则是 **T_i = int(实测_i) − 5**（下限 55，且 ≤ 实测−2）。基线实测如下：

| 模块 | 2026-09-06 实测行覆盖率 | 冻结下限 | 备注 |
|---|---|---|---|
| `flashgaze/mcp_server.py` | 87.71% | **82** | |
| `flashgaze/webui/app.py` | 85.77% | **80** | |
| `flashgaze/core/xlsx_exporter.py` | 100% | **95** | |
| `flashgaze/core/deduplicator.py` | 52.33% | 不设逐模块下限 | 本地缺 `imagededup`，52.33% 只是降级路径口径（CI run 40107357212 的 ubuntu extras 腿真装 imagededup 后实测 **83.72%**）。夜间治理按 §4 方向② **只观测不判死** |
| `flashgaze/core/portrait_engine.py` | 47.62% | 不设逐模块下限 | 本地缺 `face_recognition`（torch/dlib 过重），同上。CI 侧虽装了 `.[portrait]`，但 py3.12 venv 无 `pkg_resources` → import 期 `quit()` 被守卫兜住后仍走降级路径，实测 **47.62%**（与本地数字巧合相同，见 §4 口径冲突）；夜间同样**只观测** |

- **实测环境**：本地 Python 3.12.10，extras 口径全量测试激活（`--cov-config=.coveragerc-extras`，source 为上表 5 个模块）。门禁本身也做过实证：逐模块 `coverage report --fail-under` 全部 EXIT=0，反例 `--fail-under=99` 时 `mcp_server` 与 `webui.app` 均 EXIT=2，证明门槛真实生效而非只报告。
- **主矩阵安装集后续已扩围**：这批下限冻结于主矩阵只装 `.[mcp]` 之时；2026-09 起 `ci.yml` 的 `test` job 实装 `.[mcp,gui,exif,heic]`（见 §1）。扩围只改变主门禁哪些模块被真实考核，不影响上表逐模块下限的数值。
- **改阈值的同步义务**：上调/下调任一 floor，必须同时更新 `ci.yml` 的 `--fail-under` 行、`tests/test_coverage_gate_contract.py::PER_MODULE_FLOORS` 与本小节表格——三处不一致时契约测试会失败并指回本小节。
- **上表数字直到 2026-10-24 才第一次在 CI 上被真实比对**（2026-10-24 补注）：extras job 自 M-12
  起虽为阻塞门禁，但此后每次 CI run 都被 `needs: test` 连带 `skipped`，且真的跑起来时 pytest 在
  收集阶段就被 `face_recognition` 的 import 期 `quit()` 打死（`SystemExit` 穿透了只兜
  `ImportError` 的守卫），门禁只拿到 `No data to report.`。因此上表的「2026-09-06 实测」一直是
  **唯一口径来源**，从未与 CI 数据对过账。修复与逐条取证见 `docs/agent-context/fixes.md` §4.9、
  `docs/agent-context/pitfalls.md` §3.11。

## 3. 趋势监控与可视化（不阻塞合并）

1. **Codecov 独立 flag（informational）**：`extras-ubuntu` / `extras-macos` 两个 flag 在 `codecov.yml` 中设 `informational: true` + `carryforward: true`，仅用于看板趋势，不参与 PR 合并判定。`status.patch.core` 对核心代码强制（informational:false，target 80%），可选模块 patch 保持 informational。
   - **flag 名对齐（2026-10-23 修复）**：`ci.yml` 曾写 `flags: extras-${{ matrix.os }}`，实际投递 `extras-ubuntu-latest` / `extras-macos-latest`——与上面两个声明名永不相交，`carryforward`/`informational` 对声明 flag 全程落空，可选模块的滚动覆盖率从未真正聚合，而 CI 侧完全无感。现改为 `fromJSON` 查表（`{"ubuntu-latest":"extras-ubuntu","macos-latest":"extras-macos"}[matrix.os]`），并由 `tests/test_coverage_gate_contract.py::test_ci_extras_job_posts_declared_codecov_flags` 双向钉住：投递名未声明 → 红；extras 矩阵新增腿未登记 → 红。教训与 §2 R 系列同源——「配置写了但没人校验」等于没写。
   - **2026-10-25 复核：flag 名对齐了，但投递从未成功**。CI run 40107357212 的**每一条腿**
     都报 `Upload queued for processing failed: {"message":"Token required - not valid tokenless upload"}`，
     即 `secrets.CODECOV_TOKEN` 缺失或失效；`fail_ci_if_error: false` 让这一步恒绿，所以
     §5.1 checklist 第 3 条「确认 `secrets.CODECOV_TOKEN` 可用」实际从未被核实。后果：
     上面花力气对齐的两个 flag 依然没有任何数据进来，carryforward/informational 继续落空，
     本节的「可视化防线」第一层仍是死的。**属仓库 secret 配置项，需人工处理**，
     不应靠放宽 `fail_ci_if_error` 或改投递方式来掩盖。
2. **gh-pages 长期趋势图**：`extras-health.yml` 的 `charts` job 复用 `benchmark.yml` 的 `rhysd/github-action-benchmark` 模式，把每模块覆盖率写入 `gh-pages/dev/extras-health/`，渲染折线图（与 `dev/bench/` 同处一处，统一运维心智）。访问路径：`https://<org>.github.io/<repo>/dev/extras-health/`。
   - **2026-10-24 前从未落盘**：`charts` 步骤把入参名写成 `raw-data-file`（并多写一个
     `output-storage`），两者都不是该 action 的入参；唯一的必填项 `output-file-path` 于是回退成
     仓库目录，runner 报 `Invalid value for 'output-file-path' input: … is not a file`，
     趋势图从未成功发布（`gh-pages` 存在，`dev/extras-health/` 404）。且因为 `collect` 腿对
     缺失 `coverage.xml` 是「按无数据处理」的优雅降级，`benchmark.json` 一直是 `[]` 而 job 恒绿，
     R1-R4 从未真跑过。现由 `tests/test_coverage_gate_contract.py` 钉注入参名与
     `$GITHUB_OUTPUT` 两类「配了但没接线」的缺陷。
3. **每周 Issue 摘要**：每周一（cron `9 9 * * 1`）`weekly-report` job 把关键指标（各模块覆盖率、趋势箭头、失败用例）评论到固定 tracking Issue（环境变量 `EXTRAS_HEALTH_ISSUE`）。

## 4. 劣化熔断与升级机制（阈值规则）

判定集中在 `tools/extras_health.py` 的 `evaluate()`，阈值常量在 `DEFAULT_CONFIG`（可用 `--config` 覆盖）。当前默认：

| 规则 | 条件 | 级别 | 动作 |
|---|---|---|---|
| **R1** 绝对下限 | 判定集内任一模块 line 覆盖率 `< 60%` | warning | 建/更新 Issue |
| **R2** 连续劣化 | 判定集内任一模块周环比降 `≥5pp` 且连续 `3` 个快照 | warning | 建/更新 Issue |
| **R3** 持续失败 | 同一测试 nodeid 在 `3` 个连续运行中失败 | warning | 建/更新 Issue |
| **R4** 临界 | 判定集内任一模块 `< 50%`，或 R2/R3 触发后未修复再持续 `2` 个快照 | **critical** | 建 Issue + **写 sentinel 锁** |
| **R5** 恢复 | 判定集内所有模块 `≥70%` 且连续 `2` 快照无失败 | recovered | **清锁** + 关闭 Issue |

> **「判定集内」= `JUDGED_MODULES`（`mcp_server` / `webui.app` / `xlsx_exporter`，即 ci.yml 里
> 带逐模块 `--fail-under` 的那 3 个）**。`deduplicator` / `portrait_engine` 只观测不判死，
> 理由与代价见本节下方的口径说明。R3 不设模块范围。

> **✅ 与 §2.1 的口径冲突（2026-10-24 记录 → 2026-10-25 已采方向②收口）**：§2.1 明确接受
> `deduplicator` / `portrait_engine` 的**降级路径**数字（52.33% / 47.62%，因本地缺
> `imagededup` / `face_recognition`），故**不给它们设逐模块 floor**；而本表的 R1/R4 原是按
> 「任一模块」的绝对线判定的。链路接通后这条冲突立即生效：CI run `40134963461` 的
> `decision.json` 实测 `decision=critical`，criticals 唯一一条即 R4 `portrait_engine 47.62%`
> ——一个**测量口径问题伪装成质量临界**，并且要把 `.github/extras-strict.lock` 真的推进 `main`。
>
> **采方向②**：R1/R2/R4/R5 的判定集合限定为 `JUDGED_MODULES` = 「已设逐模块 floor 的 3 个
> 模块」（`mcp_server` / `webui.app` / `xlsx_exporter`），另两模块**只观测不判死**——仍进
> `snapshot.json` / `benchmark.json` / 趋势图，Issue 表格里逐行标注「（观测项，不参与
> R1/R2/R4/R5 判定）」，避免读 Issue 的人把「没告警」误读成「没数据」。
> - **判定集与 floor 表锁死**：`tests/test_coverage_gate_contract.py::
>   test_extras_health_judged_modules_match_ci_floors` 双向相等，将来给 dedup/portrait 补
>   逐模块 floor 却忘了同步判定集（或反过来）立即判红。
> - **R5 必须同步收敛**（否则口径不一致会往另一个方向坏）：恢复条件若仍按全集判，
>   portrait 的降级口径会让「锁一旦写上就永远解不掉」，自愈机制形同虚设。
>   由 `tests/test_extras_health_rules.py::test_recovery_only_needs_judged_modules` 钉住。
> - **R3 不受影响**：用例持续失败是平台无关的质量信号，仍对全部测试生效。
> - **代价（须知情）**：dedup / portrait 真实跌破 60% 甚至 50% 都不再自动告警、开 Issue
>   或加锁，需人工看趋势图。方向①（extras 腿补 `setuptools` 让 `face_recognition` 真跑起来，
>   从根上脱离降级口径）仍是更彻底的解，但它改变 CI 侧的**测量口径**、且会翻转
>   `tests/test_portrait.py` 的双向 skipif 判定，风险独立评估，不与本次红灯收口混做。
>
> **同时修掉的管道缺陷**：`tools/extras_health.py` 用退出码 2 表达 critical，而
> `Evaluate health` 步骤未兜非零码 → 步骤判红 → 下方「写锁 / 建 Issue / 关 Issue」三处
> （均无 `if: always()`）整批 skipped，即 R4 熔断**被自己的退出码第二次掐断**（第一次是
> 引号 heredoc 里 `$GITHUB_OUTPUT` 不展开，见 §4.9）。现步骤只放行 rc=2、其它非零码原样退出。
> 详见 pitfalls §3.12 与 fixes §4.10。

**退出码语义（调用方必读）：**

| rc | 含义 | 调用方应做 |
|---|---|---|
| 0 | `ok` / `warning` / `recovered` | 继续执行下游步骤 |
| 2 | `critical`（R4 命中） | **不是崩溃**：继续执行，由写锁 / 建 Issue 步骤落实动作 |
| 其它 | 脚本崩溃 / 输入异常 | 步骤判红，需查脚本或输入文件 |


**升级为阻塞合并的闭环：**

```
nightly 采集 → extras_health.py 判定
   ├─ critical → git commit .github/extras-strict.lock（推回分支）
   │             ↓ 下次任意 PR
   │     ci.yml check-strict job 检出锁 → strict=true
   │             ↓
   │     extras job strict 步骤：5 模块总下限在无条件 hard floors（50%）之上
   │     加严到 60（治理 R1 告警线）
   │             ↓
   │     覆盖率未修回标线的 PR 被阻塞，强制修复
   └─ recovered → git rm .github/extras-strict.lock → extras 恢复基础硬门槛
```

锁文件由定时任务自动提交/删除，**零人工值守**。开发者在锁存在期间只需把可选模块覆盖率修回 ≥70%（或修复持续失败用例），`extras-health.yml` 下一轮 nightly 即自动清锁。

**推送健壮性（防并发冲突）**：写/清锁为幂等直推默认分支——已锁不重写、已清不重删，避免重复提交；推送被拒（评测期间分支被其他提交推进）时自动 `fetch + rebase` 后线性退避重试（最多 5 次），彻底失败则步骤报错、交由下一轮 nightly 自愈，告警 Issue 不受影响。同工作流并发（nightly 与手动触发）由工作流级 `concurrency` 组排队串行化。趋势数据推送（本工作流与 benchmark.yml 共写 `gh-pages`）同样采用手动推送 + 同款重试；两者写不同目录，不产生内容冲突。若仓库未来对默认分支启用"必须经 PR 合并"的强制保护，机器人直推会被拒，届时需改走 PR 方案。

> sentinel 必须被 git 跟踪（不被 `.gitignore` 忽略）才能被 PR checkout 读到——它由 CI 提交进仓库，天然满足。

## 5. 工程落地与日常规范

### 5.1 落地 checklist（一次性）

1. 创建固定 tracking Issue（标题含 `[extras-health]`），将其编号填入 `extras-health.yml` 的 `env.EXTRAS_HEALTH_ISSUE`。
2. 确认仓库已启用 **Settings → Pages**，源分支 `gh-pages`（benchmark.yml 已在使用，通常已就绪）。
3. 确认 `secrets.CODECOV_TOKEN` 与 `secrets.GITHUB_TOKEN` 可用（默认提供）。
4. 在 `tools/extras_health.py` 的 `MODULE_OWNERS` 填入各模块实际负责人（GitHub 用户名/团队 slug），使清理 Issue 能正确指派。
5. 把本方案相关文件（`codecov.yml`、`extras-health.yml`、`ci.yml`、`tools/extras_health.py`、`docs/extras-governance.md`）合并入 `main`。

### 5.2 开发者日常规范

- **改可选模块必跑 extras 本地校验**：`pip install -e ".[cv-enhanced,dedup,vlm-multi,gui,exif,xlsx,portrait]" && pip install "mcp>=1.2.0,<2.0.0" && pytest tests/ -v --cov=flashgaze --cov-config=.coveragerc-extras`。
- **关注每周摘要 Issue**：趋势下滑或新增告警时优先处理，避免在 R4 临界后被锁阻塞。
- **dependabot / 升级后**：重型依赖（gradio、mcp、face_recognition）版本变动可能拉低覆盖率或引入失败，留意 `extras-health` Issue。
- **被锁阻塞时**：不要手动删除 `.github/extras-strict.lock`（会被下一轮 nightly 重写），而是修复可选模块质量使其回到 R5 恢复条件，等待自动清锁（最长一个 nightly 周期）。
- **紧急放行**：若锁误触发且需立即放行，可由 maintainer 手动删除锁文件并说明（属例外操作，应在 Issue 记录）。注意：人工改锁后若恰逢下一轮自动推送，最坏会产生一次 rebase 冲突导致该轮推送中止（日志可见 `::error::`），属预期，下一轮自愈。

### 5.3 维护成本与边界

- 定时任务仅 nightly（1 次）+ 每周一（1 次），双腿（ubuntu/macos × py3.12）runner 占用极低，不影响日常 PR 时长。
- `tools/extras_health.py` 纯标准库、无新依赖，逻辑与 I/O 分离，可本地单测（`pytest tools/` 或手动构造 coverage.xml/junit.xml 验证 `evaluate`）。
- 阈值参数集中在 `DEFAULT_CONFIG`，调参无需改工作流；如需更激进/宽松，改常量或传 `--config` 即可。
- **blast radius（M-12 修复后）**：主 `test` 门禁 `fail_under=80` 数值不变，但 omit 从 5 模块收窄为 3 个（`mcp_server`/`webui.app` 已纳入主门禁，主矩阵加装 `mcp,gui,exif,heic` 轻量 extras 使其测试真实执行）；`extras` job 默认即阻塞（`.coveragerc-extras` `fail_under=50` + `ci.yml` 逐模块下限），sentinel 锁仅在锁存在时把总下限加严到 60。`tools/extras_health.py`、`extras-health.yml`、codecov flags 结构零触碰；extras 配置的 source 仍为 5 模块（`MODULES` 依赖）。契约由 `tests/test_coverage_gate_contract.py` 锁定。

## 6. 故障排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 趋势图不更新 | gh-pages 未启用或 `charts` job 权限不足 | 检查 Settings→Pages 与 `permissions: contents: write` |
| 每周摘要未发 | `EXTRAS_HEALTH_ISSUE` 为空 | 填入 tracking Issue 编号 |
| 告警 Issue 刷屏 | 同一周多次 nightly 均 warning | 脚本已复用本周 open Issue 追加评论，不会重复建；确认标签过滤 |
| 锁误触发 | 覆盖率数据异常（如某模块源码被整文件 omit） | 检视 `coverage.xml` 是否被 `.coveragerc-extras` 正确 source；必要时人工清锁并记录 |
