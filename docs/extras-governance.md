# FlashGaze 可选模块长期监控与治理规范

> 配套文件：`.github/workflows/extras-health.yml`、`tools/extras_health.py`、`codecov.yml`、`ci.yml`（`check-strict` job）。
> 适用范围：5 个可选模块 `mcp_server` / `webui.app` / `core.xlsx_exporter` / `core.deduplicator` / `core.portrait_engine`。

## 1. 为什么要治理可选模块

主 CI 的 `test` 门禁（`fail_under=80`）只 `omit` 依赖重型/可选包的 **3 个模块**（`core.xlsx_exporter`、`core.deduplicator`、`core.portrait_engine`）；`mcp_server` 自 2026-09 起随主矩阵加装 `mcp` extra 纳入主门禁，`webui/app`（gradio 懒加载、无重依赖）同批纳入（M-12 修复）。这 3 个重依赖模块由 `extras` job **硬门槛**强制：`.coveragerc-extras` `fail_under=50` 总下限 + `ci.yml` 逐模块下限，覆盖率不达标**阻塞合并**。

这套硬门槛保障了主流程交付效率，但历史教训是：`extras` job 曾长期「只报告不设门」（`continue-on-error` 吞掉一切失败），可选模块的覆盖率下滑被静默忽略。因此在本门槛之上叠加**旁路定时治理流水线**，实现「看得见、可告警、能升级、会自愈」。

## 2. 三道防线总览

| 防线 | 机制 | 是否阻塞 PR | 触发频率 |
|---|---|---|---|
| 可视化 | Codecov `extras-*` flag（informational）+ gh-pages 趋势图 + 每周 Issue 摘要 | 否 | 每次 PR / 每日 / 每周一 |
| 告警 | `extras-health.yml` 判定命中 → 自动建/更新清理 Issue（标签 `extras-health`） | 否 | nightly |
| 硬门槛 | `extras` job `Coverage gate (hard floors)`：5 模块总下限 50% + 逐模块下限（M-12） | **是（始终）** | 每次 PR |
| 加严升级 | 临界命中 → 写 `.github/extras-strict.lock` → `ci.yml` 读锁后 strict 步骤把总下限抬到 60 | **是（临时）** | nightly |

定时治理线通过单一事实 `.github/extras-strict.lock` 解耦：定时任务**写锁**，`ci.yml` 的 `check-strict` job **读锁**，互不耦合、可独立演进；硬门槛防线不依赖锁，`tests/test_coverage_gate_contract.py` 锁定其配置契约防退化。

## 3. 趋势监控与可视化（不阻塞合并）

1. **Codecov 独立 flag（informational）**：`extras-ubuntu` / `extras-macos` 两个 flag 在 `codecov.yml` 中设 `informational: true` + `carryforward: true`，仅用于看板趋势，不参与 PR 合并判定。`status.patch.core` 对核心代码强制（informational:false，target 80%），可选模块 patch 保持 informational。
2. **gh-pages 长期趋势图**：`extras-health.yml` 的 `charts` job 复用 `benchmark.yml` 的 `rhysd/github-action-benchmark` 模式，把每模块覆盖率写入 `gh-pages/dev/extras-health/`，渲染折线图（与 `dev/bench/` 同处一处，统一运维心智）。访问路径：`https://<org>.github.io/<repo>/dev/extras-health/`。
3. **每周 Issue 摘要**：每周一（cron `9 9 * * 1`）`weekly-report` job 把关键指标（各模块覆盖率、趋势箭头、失败用例）评论到固定 tracking Issue（环境变量 `EXTRAS_HEALTH_ISSUE`）。

## 4. 劣化熔断与升级机制（阈值规则）

判定集中在 `tools/extras_health.py` 的 `evaluate()`，阈值常量在 `DEFAULT_CONFIG`（可用 `--config` 覆盖）。当前默认：

| 规则 | 条件 | 级别 | 动作 |
|---|---|---|---|
| **R1** 绝对下限 | 任一模块 line 覆盖率 `< 60%` | warning | 建/更新 Issue |
| **R2** 连续劣化 | 任一模块周环比降 `≥5pp` 且连续 `3` 个快照 | warning | 建/更新 Issue |
| **R3** 持续失败 | 同一测试 nodeid 在 `3` 个连续运行中失败 | warning | 建/更新 Issue |
| **R4** 临界 | 任一模块 `< 50%`，或 R2/R3 触发后未修复再持续 `2` 个快照 | **critical** | 建 Issue + **写 sentinel 锁** |
| **R5** 恢复 | 所有模块 `≥70%` 且连续 `2` 快照无失败 | recovered | **清锁** + 关闭 Issue |

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
- **blast radius（M-12 修复后）**：主 `test` 门禁 `fail_under=80` 数值不变，但 omit 从 5 模块收窄为 3 个（`mcp_server`/`webui.app` 已纳入主门禁，主矩阵加装 `mcp` extra）；`extras` job 默认即阻塞（`.coveragerc-extras` `fail_under=50` + `ci.yml` 逐模块下限），sentinel 锁仅在锁存在时把总下限加严到 60。`tools/extras_health.py`、`extras-health.yml`、codecov flags 结构零触碰；extras 配置的 source 仍为 5 模块（`MODULES` 依赖）。契约由 `tests/test_coverage_gate_contract.py` 锁定。

## 6. 故障排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 趋势图不更新 | gh-pages 未启用或 `charts` job 权限不足 | 检查 Settings→Pages 与 `permissions: contents: write` |
| 每周摘要未发 | `EXTRAS_HEALTH_ISSUE` 为空 | 填入 tracking Issue 编号 |
| 告警 Issue 刷屏 | 同一周多次 nightly 均 warning | 脚本已复用本周 open Issue 追加评论，不会重复建；确认标签过滤 |
| 锁误触发 | 覆盖率数据异常（如某模块源码被整文件 omit） | 检视 `coverage.xml` 是否被 `.coveragerc-extras` 正确 source；必要时人工清锁并记录 |
