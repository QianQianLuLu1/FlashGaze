# CI 无故变红：诊断结论与实施计划

- 诊断日期：2026-11-06
- 仓库（本机绝对路径）：`D:\Zcode项目\SaiTu skill`
- 远端：`https://github.com/QianQianLuLu1/FlashGaze`（本机 remote 为 `ssh://git@ssh.github.com:443/QianQianLuLu1/FlashGaze.git`，同一仓库）
- 诊断时 `HEAD` = `origin/main` = `68c086b37dd5208f06bca1959a2e1d3ae81fa658`（工作区干净）
- 本轮性质：**只做诊断与计划**，未修改任何代码、workflow 或依赖；本文件是唯一新增产物，且未提交、未推送。

> 本机另有一个同远端克隆 `D:\Qoder项目\SaiTu skill`，其最新提交停留在 2026-10-11 且落后于 `main`，不作为本次修复的落点。全部结论以 `D:\Zcode项目\SaiTu skill` 与其远端真实运行数据为准。

---

## 0. 结论摘要（先给答案）

1. **没有任何人推送代码，CI 却变红，是因为有一条 `schedule`（cron）工作流在跑**，不是 push 触发的。红的那次是 `Benchmark` run `42129078042`，`event=schedule`，`head_sha=68c086b`，与 10-28 最后一次推送的 sha **完全相同**；同一 sha 在 11-04 的同类 nightly 是绿的。
2. **失败点是趋势数据推送**（`benchmark.yml` 的 `Push gh-pages with retry`），不是编译、不是测试、不是依赖解析。GitHub 服务端返回 `remote: fatal error in commit_refs_rules`（平台侧内部错误），仓库没有规则集（`rulesets=0`）、`gh-pages` 也未被保护。
3. **一次平台瞬时错误被放大成整轮红，责任在我们自己的重试代码**，有三个可根治缺陷：
   - 重试路径未配置 git 提交身份 → `git rebase` 直接以 `Committer identity unknown` 失败，却被脚本误报成“rebase 冲突”；
   - `git fetch --depth=50` 制造浅历史 → 日志出现 `Rebasing (1/15)`（把 15 个提交当成待重放），存在改写 gh-pages 历史的真实风险；
   - 不区分错误类型，任何 push 失败都走同一条重试路径，平台瞬时错误因此变成确定性红灯。
4. 10-27 的另一次 nightly 红（run `40590781626`）**根因不同且已修复**：pytest 9.2.0 与 pytest-benchmark 5.3.0 不兼容（`AttributeError: 'Function' object has no attribute '_nodeid'`）。修复提交 `f3b8187` 已在 `requirements-dev.txt` 钉死引擎版本；此后同 sha 的 7 轮 nightly 全绿，可视为该问题已闭环，本次不再重复处理。
5. 实施方向（唯一确定路径，无待确认项）：
   - 修复直接推 `main`；
   - 把推送逻辑抽成可测试的 Python 脚本，先写红灯测试再改；
   - 用“完整 fetch + 显式身份 + 错误分类 + 有界退避”替换两处内联重试脚本；
   - **不对测试使用 skip / xfail / 自动重试 / 加大超时**；本次不稳定性来源是外部平台错误与自身残缺的重试实现，处理方式是消除自身不确定性，而不是掩盖。

---

## 附录 A：证据链（真实运行数据）

### A.1 数据来源与鉴权状态（如实记录）

- `gh.exe` 存在：`C:\Program Files\GitHub CLI\gh.exe`，但 `gh auth status` 返回 **You are not logged into any GitHub hosts**，因此 `gh run list` / `gh run view --log-failed` 不可用。
- 为拿到与 `gh` 等价的真实证据，改用 GitHub REST API（只读），鉴权来自本机 git credential helper 中已存的 GitHub 凭据（账号 `QianQianLuLu1`）。**未写入、未修改任何 gh/git 配置文件**，也未在仓库内留下凭据。
- 使用的只读端点：`/actions/runs`、`/actions/runs/{id}/jobs`、`/check-runs/{id}/annotations`、`/actions/jobs/{id}/logs`、`/branches/gh-pages`、`/commits/{sha}`、`/rulesets`。

### A.2 运行清单（2026-10-28 → 2026-11-06，按创建时间）

| 创建时间 (UTC) | workflow | event | 结论 | run id | head sha |
|---|---|---|---|---|---|
| 2026-10-28T14:31:37Z | CI | push | success | 40706802208 | `68c086b` |
| 2026-10-28T14:31:37Z | Benchmark | push | success | 40706802235 | `68c086b` |
| 2026-10-28T22:20:19Z | Benchmark | schedule | success | 40779184797 | `68c086b` |
| 2026-10-29T22:33:18Z | Benchmark | schedule | success | 40966745648 | `68c086b` |
| 2026-10-30T22:02:02Z | Benchmark | schedule | success | 41135315649 | `68c086b` |
| 2026-10-31T21:11:19Z | Benchmark | schedule | success | 41242405867 | `68c086b` |
| 2026-11-01T21:48:48Z | Benchmark | schedule | success | 41353917600 | `68c086b` |
| 2026-11-03T00:43:22Z | Benchmark | schedule | success | 41554860664 | `68c086b` |
| 2026-11-04T23:23:01Z | Benchmark | schedule | success | 41933275935 | `68c086b` |
| **2026-11-05T23:24:43Z** | **Benchmark** | **schedule** | **failure** | **42129078042** | `68c086b` |
| 2026-11-05T23:46:51Z | Security | schedule | success | 42131979825 | `68c086b` |
| 2026-11-06T00:15:04Z | extras-health | schedule | success | 42135439089 | `68c086b` |

关键对照：**红的那次（42129078042）与最近一次绿的那次（41933275935）sha 完全相同，都是 `68c086b`；两次都是 schedule**。`main` 最后一次推送是 10-28，之后没有任何 push 运行。所谓“没人推送却变红”，触发源就是 `benchmark.yml` 的 `cron: '0 18 * * *'`（UTC 18:00，实际因 GitHub 调度队列延迟到 23:24 才起跑）。

### A.3 失败运行 42129078042 的真实报错

- 事件：`schedule`；`run_attempt=1`；job `benchmark (ubuntu, py3.12)`；`started 23:24:45Z → completed 23:25:45Z`。
- 失败 step：**13. Push gh-pages with retry**（前面的 checkout、安装、基准运行、趋势图生成、gh-pages 检查全部 success）。
- Check-run 注解（GitHub 原始输出）：
  - `::warning::` `gh-pages 推送被拒，同步最新远端后重试（第 1 次）`
  - `::error::` `gh-pages rebase 冲突，本次趋势数据推送中止，下一轮运行自愈`
  - `::error::` `Process completed with exit code 1.`
  - 另有一条与失败无关的既有告警：`Node.js 20 is deprecated ... actions/cache@v4`
- Job 日志原文（关键行，已去掉时间戳前缀）：
  ```
  remote: fatal error in commit_refs_rules
  To https://github.com/QianQianLuLu1/FlashGaze
   ! [remote rejected] gh-pages -> gh-pages (fatal error in commit_refs_rules)
  error: failed to push some refs to 'https://github.com/QianQianLuLu1/FlashGaze'
  ##[warning]gh-pages 推送被拒，同步最新远端后重试（第 1 次）
  warning: skipped previously applied commit c3ab8cf
  Rebasing (1/15)
  Committer identity unknown
  fatal: empty ident name (for <runner@...>) not allowed
  ##[error]gh-pages rebase 冲突，本次趋势数据推送中止，下一轮运行自愈
  ##[error]Process completed with exit code 1.
  ```

### A.4 gh-pages 侧证据（证明不是权限/保护/内容冲突）

- `GET /repos/QianQianLuLu1/FlashGaze/rulesets` → **0 条规则集**；`GET /branches/gh-pages` → `protected=false`。因此 `commit_refs_rules` 不是仓库规则命中，而是 GitHub 服务端在一次 ref 规则求值中内部出错。
- gh-pages 最近提交：
  | commit | 时间 (UTC) | 内容 |
  |---|---|---|
  | `0353378` | 2026-11-06T00:28:15Z | extras-health 写 `dev/extras-health/data.js`（成功） |
  | `27d5ac0` | 2026-11-05T00:33:31Z | extras-health 写 `dev/extras-health/data.js`（成功） |
  | `a3d01c8` | 2026-11-04T23:23:55Z | benchmark 写 `dev/bench/data.js`（成功） |
  | `961c32b` | 2026-11-04T00:11:30Z | extras-health 写 `dev/extras-health/data.js`（成功） |
- 11-05 的 benchmark 推送失败 → **当天的 `dev/bench/data.js` 数据点永久缺失**（日志里“下一轮运行自愈”的说法不成立，这不属于下一轮能补回的内容，见 3.3 已知限制）。
- 两个工作流写的是不同文件（`dev/bench/data.js` vs `dev/extras-health/data.js`），正常情况下 rebase 不会内容冲突；11-05 的 rebase 失败是**缺少提交身份**导致的，不是文件冲突。

### A.5 更早的失败（10-27，已闭环，不重复处理）

- run `40590781626`，`event=schedule`，sha `2d94e08`，失败 step 是 **8. Run head benchmarks with regression gate**。
- 日志：`benchmarks/test_image_io_bench.py EEEE`，`AttributeError: 'Function' object has no attribute '_nodeid'`（`pytest_benchmark/fixture.py:88`）。
- 根因：requirements 当时用区间 `pytest<10,>=7.4.0`，2026-10-27 解析到刚发布的 pytest 9.2.0；pytest-benchmark 5.3.0 仍访问私有 `node._nodeid`。
- 已修复：提交 `f3b8187` 在 `requirements-dev.txt` 钉死 `pytest==9.1.1`、`pytest-benchmark==5.3.0`、`coverage[toml]==7.16.2`、`mypy==1.20.2`、`types-requests==2.33.0.20261006`、`ruff==0.16.10`。10-28 起 7 轮 nightly 基准全绿（见表），证明该修复有效。

### A.6 证据缺口（不足以定性的部分，必须写明）

1. `commit_refs_rules` 的具体触发条件：GitHub 未公开该内部错误的成因；仓库侧无规则集、分支未保护，只有一个样本（11-05），相邻日同命令均成功。**结论只能定性为“平台侧瞬时内部错误”**，无法在仓库内证明其触发机制。
2. `Rebasing (1/15)` 中“15”的精确来源：失败时未打印 rebase 前的 `git rev-list --count origin/gh-pages..gh-pages` 与 `git merge-base`，事后无法复原当时本地分支状态。已确认的机制是 `--depth=50` 引入浅历史导致提交计数异常；具体为何是 15 需要复现实验验证（见子任务 ST1 的用例 2）。
3. GitHub 平台事件记录：本机没有 status/incident 订阅数据，不能引用官方 incident 编号。
4. 其余测试是否存在时间/随机/网络依赖：**本轮未逐文件审计全部 `tests/`**。可确认的是本次红点发生在 push 步骤，与测试执行无关；计划把“全量测试连续 3 次同结果”作为实施前基线（见 8），不在本轮下结论。

---

## 附录 B：仓库侧配置检查

| 项 | 现状 | 与本故障的关系 |
|---|---|---|
| `benchmark.yml` 触发 | `push(main/master)` / `pull_request` / `schedule: 0 18 * * *` / `workflow_dispatch` | **直接触发源**：红点是 schedule |
| `extras-health.yml` 触发 | `schedule: 17 19 * * *` + `9 9 * * 1` / `workflow_dispatch` | 也会写 gh-pages，且**内联了同样的残缺重试块** |
| `security.yml` 触发 | `pull_request` / `schedule: 30 18 * * *` / `workflow_dispatch` | 不写 gh-pages；11-05 绿 |
| `ci.yml` 触发 | `push(main/master)` / `pull_request` / `workflow_dispatch` | 无 schedule，不会“自己变红” |
| concurrency | 各工作流 `group: <wf>-${{ github.ref }}` + `cancel-in-progress` | **跨工作流不互斥**：benchmark 与 extras-health 可同时写 gh-pages（本次内容不冲突，但顺序不可控） |
| runner | `ubuntu-latest` / `windows-latest` / `macos-latest` | 浮动标签；注解已提示 `ubuntu-latest` 将在 2026-10-19 起迁移到 Ubuntu 26（既有风险，非本次故障） |
| action 版本 | `actions/checkout@v5`、`setup-python@v6`、`cache@v4`、`upload-artifact@v4`、`github-action-benchmark@v1`、`codecov@v5`、`github-script@v7` | 均为浮动 major 标签；`actions/cache@v4` 被强制在 Node 24 上运行（仅有 deprecation warning，不影响本次结论）。**本次不顺手升级**（最小改动原则） |
| Python 依赖 | `requirements-dev.txt` 已钉死测量引擎；`requirements.txt` 仅 `-e .`，核心区间见 `pyproject.toml` | 10-27 的依赖漂移已被钉死消除；本次无需变更 |
| 锁文件 | 无 pip lock（`requirements*.txt` 非完整锁） | 属既有架构，本次不动；引擎类已单版本钉死 |
| 测试入口 | `pyproject.toml [tool.pytest.ini_options]`：`testpaths=["tests"]`、`addopts='-m "not e2e"'`；`benchmarks/` 为独立顶层目录 | 与本次 push 故障无关 |
| 基准/趋势 | `pytest-benchmark==5.3.0`、PR 同机自对比 ±15%、nightly 全量 | 趋势阈值只告警不失败，跨机噪声不具失败权 |

### B.1 “非确定性来源”逐条处置（按用户硬约束：彻底消除，不掩盖）

| 来源 | 现状 | 处置 |
|---|---|---|
| 测量引擎版本漂移（pytest / pytest-benchmark / coverage / mypy / ruff / types-requests） | 已钉死单版本，10-27 事故即此因 | **已消除**，本次保持；不新增区间 |
| GitHub cron 调度延迟 | 18:00 UTC 的任务实际 23:24 才起跑 | **不可从仓库消除**（平台调度行为）；记录为触发事实，不把“起跑时间偏移”当失败原因 |
| GitHub ref 规则求值内部错误 `commit_refs_rules` | 单次平台故障，仓库无规则集 | **不可从仓库消除**；把影响收敛为“一次瞬时错误不再直接判红”（正确分类 + 完整 fetch + 有界退避），最终仍失败则如实报红并给出可诊断信息 |
| 残缺的 retry 实现（身份缺失、浅 fetch、错误不分类） | 本次把它放大成红灯 | **本次根治**：见 3.3 / 3.6，并用红灯测试锁死 |
| 跨工作流并发写 gh-pages | benchmark 与 extras-health 各自推送 | 内容互不重叠，完整 fetch + rebase 即可线性化；**不引入共享 concurrency group**（会取消正在跑的基准，属于用掩盖换绿灯） |
| 基准耗时抖动 | pytest-benchmark 统计 + PR 同机对比 | 趋势图跨机数据仅告警、不具失败权；PR 门禁用同机基线。**不加大阈值、不重试** |
| 测试中的时间/随机/网络依赖 | 未逐文件审计 | 实施前基线：`tests/` 全量连续 3 次结果一致（8.1）；若出现不稳定，按“消除来源”处理，禁止 skip/xfail/retry |

---

## 1. 依赖声明

**不新增、不变更任何依赖。** 本次实现只使用已有工具链：

| 用途 | 依赖 | 版本/来源 | 引入方式 |
|---|---|---|---|
| 推送脚本 | Python 标准库 `argparse` / `subprocess` / `time` / `os` / `sys` | Python ≥ 3.10（CI 3.12/3.13） | 无需安装 |
| 脚本测试 | `pytest` | `pytest==9.1.1`（`requirements-dev.txt:20`） | `pip install -r requirements-dev.txt` |
| 端到端 git 行为测试 | `git` | runner 自带（actions/checkout 已使用） | 无 |
| lint / 类型 | `ruff==0.16.10`、`mypy==1.20.2` | `requirements-dev.txt:45,55` | 同上 |

- 不修改 `requirements.txt` / `requirements-dev.txt` / `pyproject.toml` 的依赖表。
- 不升级 workflow 中任何 action 版本（`Node.js 20` deprecation 是既有告警，非失败原因，另案评估）。
- 不引入 `actionlint` 等新工具；YAML 只做最小合法性校验（见 8.2）。

---

## 2. 启动说明

### 2.1 环境准备（与 `ci.yml` 主矩阵同款）

```bash
# 仓库根：D:\Zcode项目\SaiTu skill
python -m pip install --upgrade pip
pip install -e ".[mcp,gui,exif,heic]"
pip install -r requirements-dev.txt
```

### 2.2 本次新增脚本的使用方式（实施后）

```bash
# 帮助与参数说明
python tools/ci/push_gh_pages.py --help

# CI 中的实际调用（与 workflow 保持一致）
python tools/ci/push_gh_pages.py \
  --repo . --remote origin --branch gh-pages \
  --attempts 5 --backoff-base 10
```

### 2.3 验证方式（只用仓库真实存在的入口）

1. 单测（新增）：`python -m pytest tests/test_ci_push_gh_pages.py -q`
2. 默认门禁：`python -m pytest tests/ -q`
3. 本地等价 CI 静态检查：`python -m ruff check .`、`python -m ruff format --check .`、`python -m mypy`、`python -m mypy --platform linux`
4. 基准快速集（与 push 分支同款）：`python -m pytest benchmarks/ -m "not bench_full" --benchmark-disable-gc`
5. 远端验证（实施并推送后）：
   - `benchmark.yml` 已有 `workflow_dispatch`，可在 Actions 页手动触发一次；
   - 也可等下一轮 `schedule`（UTC 18:00）；
   - 判定标准：`Push gh-pages with retry` step 为 success，且 gh-pages 出现对应 sha 的新提交。
   - 注意：本机 `gh` 未登录，`gh workflow run` 不可用；需要 CLI 触发时先完成 `gh auth login`（本轮不做）。

---

## 3. 错误处理

### 3.1 推送失败分类（替代“一招 rebase 到底”）

| 分类 | 判定依据（`git push` stderr） | 处置 | 退出码 |
|---|---|---|---|
| 成功 | exit 0 | 输出尝试次数与最终 sha | 0 |
| 非快进 | `non-fast-forward` / `fetch first` / `[rejected] ... (fetch first)` | **完整** `git fetch origin +refs/heads/<branch>:refs/remotes/origin/<branch>`（禁止 `--depth`）→ `git rebase origin/<branch>` → 下一轮 push | 继续重试 |
| 平台瞬时 | `commit_refs_rules` / `Internal Server Error` / `remote failure` / `HTTP 5xx` / 连接重置 | 原分支状态不动，退避后重试；每轮先做完整 fetch 再判断是否需要 rebase | 继续重试 |
| 认证/权限 | `Permission to ... denied` / `403` / `protected branch` / `GH006` | **立即失败，不重试**（重试只会延长红灯） | 1 |
| 本地分支缺失 | `git rev-parse --verify refs/heads/<branch>` 失败 | **立即失败**，明确提示“拒绝在非 gh-pages 分支上 rebase”，绝不回退去 rebase `main` | 1 |
| rebase 冲突 | `git rebase` 非零 | `git rebase --abort`；输出冲突文件列表；明确“本次数据未推送，非下一轮可补” | 1 |
| 重试耗尽 | 达到 `--attempts` | 输出最后一次分类与完整 stderr 摘要 | 1 |
| 参数非法 | 见第 4 节 | 打印 usage，不做任何 git 操作 | 2 |

### 3.2 兜底策略（确定性优先）

- 每次 rebase / push 前显式注入提交身份，不依赖 runner 的全局 gitconfig：
  `GIT_AUTHOR_NAME/EMAIL`、`GIT_COMMITTER_NAME/EMAIL` 与 `git -c user.name=... -c user.email=...` 双保险。默认 `github-actions[bot]` / `41898282+github-actions[bot]@users.noreply.github.com`（与 `benchmark.yml:162-163` 现有 bootstrap 一致）。
- **禁止浅 fetch**：任何 `--depth` 都会让“领先提交数”失真（本次日志 `Rebasing (1/15)` 即证据），脚本内直接禁止该参数，并由测试静态断言锁死。
- rebase 前必须断言 `git rev-parse --abbrev-ref HEAD == <branch>`，且 `refs/heads/<branch>` 存在；否则视为编程错误立即 exit 1。
- 每次尝试都打印可诊断上下文：`HEAD`、`origin/<branch>`、`git rev-list --count origin/<branch>..<branch>`、`git merge-base`、push 的完整 stderr 前 20 行。
- 不吞错：所有失败要么重试、要么非零退出；不会出现“步骤绿了但数据没推上去”。

### 3.3 日志输出规范与已知限制

- 普通信息写 stdout；告警/错误写 stderr，并在 `GITHUB_ACTIONS=true` 时输出 `::warning::` / `::error::` 注解，便于 Actions 摘要定位。
- 每轮格式：`attempt=<n>/<max> push=rejected class=<class> ahead=<n> backoff=<s>`。
- **已知限制（如实写明）**：若最终仍失败，本次基准数据点不会自动补推，“下一轮自愈”不成立。修复范围仅限“不再因一次瞬时错误判红 + 不再有历史改写风险”；若需要补数据，属独立需求，需另行评估（不在本次最小改动内）。

---

## 4. 参数校验

脚本 `tools/ci/push_gh_pages.py` 的入参（`argparse`，全部在动手前校验，失败即 exit 2，不执行 git）：

| 参数 | 类型 | 必填 | 默认 | 边界/非法值处理 |
|---|---|---|---|---|
| `--repo` | 路径 | 否 | `.` | 不存在 / 不是 git 仓库（`git rev-parse --git-dir` 失败）→ exit 2 |
| `--remote` | str | 否 | `origin` | 空串或含空白 → exit 2；`git remote get-url` 不存在 → exit 2 |
| `--branch` | str | 否 | `gh-pages` | 必须匹配 `^[A-Za-z0-9._/-]+$`、不得以 `-` 开头、不得含 `..`；非法 → exit 2 |
| `--attempts` | int | 否 | `5` | 合法区间 `1..10`；非整数 / 越界 → exit 2 |
| `--backoff-base` | float | 否 | `10` | 合法区间 `0..300`；负数 / 非数字 → exit 2 |
| `--author-name` | str | 否 | `github-actions[bot]` | 去空白后不得为空 → exit 2 |
| `--author-email` | str | 否 | `41898282+github-actions[bot]@users.noreply.github.com` | 必须含 `@` 且无空白 → exit 2 |
| `--git` | str | 否 | `git` | 供测试注入替代实现；解析不到可执行文件 → exit 2 |

外部输入视为不可信：`--branch` 不直接拼进 shell（全程 `subprocess` 列表参数，不 `shell=True`）；stderr 只做分类匹配，不原样执行。

---

## 5. 基础测试用例

新增 `tests/test_ci_push_gh_pages.py`，用临时目录构造**真实 git 仓库 + 裸远端**，不触网、不依赖时钟，全部确定性。

| # | 类型 | 场景 | 断言要点 |
|---|---|---|---|
| 1 | 正常 | 首次 push 成功 | 退出码 0；裸远端 `refs/heads/gh-pages` == 本地 HEAD；无 rebase |
| 2 | 正常 | 远端被另一克隆推进（真实非快进） | 完整 fetch + rebase 后成功；远端为线性历史；本地领先数 rebase 前 = 1（**红灯锁死 `--depth` 导致的 1/15**） |
| 3 | 异常 | 模拟 `commit_refs_rules` 两次后成功（注入 git 包装器） | 恰好重试 2 次后退出码 0；日志包含 `class=transient`；仍使用完整 fetch |
| 4 | 异常 | 无全局/局部 gitconfig（`HOME` 指向空目录） | rebase 仍成功（**红灯：修复前报 `Committer identity unknown`**）；提交作者为脚本注入身份 |
| 5 | 异常 | 认证/权限错误（`Permission ... denied`） | **只尝试 1 次**，退出码 1，日志 `class=fatal-auth`，不执行 rebase |
| 6 | 异常 | 本地不存在 `<branch>` 分支 | 退出码 1，日志明确“拒绝 rebase 非目标分支”，不改动仓库 |
| 7 | 边界 | `--attempts=1` 且远端持续报内部错误 | 退出码 1；尝试次数 = 1；最终错误含分类与尝试次数 |
| 8 | 边界 | `--attempts=0` / `--branch='bad name'` / `--repo=<非 git 目录>` | 均退出码 2，且未执行任何 git 命令（用 git 包装器记录调用次数） |
| 9 | 边界 | rebase 真内容冲突（两克隆改同一文件） | 退出码 1；输出冲突文件；`git rebase --abort` 后仓库状态干净；远端未被污染 |
| 10 | 契约（静态） | workflow 不含内联重试实现 | `benchmark.yml` / `extras-health.yml` 均调用 `python tools/ci/push_gh_pages.py`；两个文件内不存在 `--depth=` 与 `git push origin gh-pages:gh-pages` 的内联循环 |

测试实现要点：通过 `--git` 传入一个“包装 git”的 Python 脚本（记录参数、按预设脚本模拟 push 返回码/stderr），其余命令委托真实 git；避免网络与时间依赖。`--backoff-base 0` 让退避在测试中瞬时完成（这是测试参数，不是掩盖手段）。

---

## 6. 子任务拆分（每项按 红灯 → 改代码 → 转绿）

### ST0 基线确认（不改代码）

- 输入：当前 `main`（`68c086b`）干净工作区。
- 动作（真实命令）：
  ```bash
  python -m pytest tests/ -q
  python -m pytest tests/ -q -o addopts=
  python -m ruff check .
  python -m ruff format --check .
  python -m mypy
  python -m mypy --platform linux
  pre-commit run --all-files
  ```
- 验收：以上全部通过（若 Windows 本机有既有失败，先记录为基线，不顺手修）。
- 连续 3 次全量测试结果一致（消除“时间/随机/网络”不确定性来源的基线证据）。

### ST1 先写失败测试（RED）

- 文件：**新增** `D:\Zcode项目\SaiTu skill\tests\test_ci_push_gh_pages.py`
- 输入：第 5 节 10 个用例（其中 2、4、8 为重放本次事故的关键红灯）。
- 输出：测试代码 + 测试用 `git` 包装器夹具。
- 红灯命令与预期：
  ```bash
  python -m pytest tests/test_ci_push_gh_pages.py -q
  ```
  预期失败原因：`tools/ci/push_gh_pages.py` 不存在、workflow 仍是内联脚本（用例 1–9 失败 / 用例 10 失败）。
- 验收标准：**全部用例红**，且失败原因是“被测对象缺失/未改造”，不是夹具自身错误。

### ST2 实现推送脚本（GREEN）

- 文件：**新增** `D:\Zcode项目\SaiTu skill\tools\ci\push_gh_pages.py`
- 输入：第 4 节参数；git 仓库与远端。
- 输出：退出码 0/1/2 + 结构化日志（见 3.3）。
- 实现要点：
  1. 参数校验（4 节）；
  2. 断言本地目标分支存在且当前 HEAD 为目标分支；
  3. push → 失败分类（3.1）；
  4. 非快进/瞬时：完整 fetch（`+refs/heads/<b>:refs/remotes/origin/<b>`）→ 按需 rebase（注入身份）→ 重试；
  5. 有界退避（`attempt * backoff_base` 秒）；
  6. 每轮打印诊断上下文；
  7. 禁止任何 `--depth` 调用。
- 验收：
  ```bash
  python -m pytest tests/test_ci_push_gh_pages.py -q
  ```
  用例 1–9 全绿（用例 10 仍红，等 ST3/ST4）。

### ST3 替换 benchmark.yml 的内联脚本

- 文件：`D:\Zcode项目\SaiTu skill\.github\workflows\benchmark.yml`（替换 `193-212` 行整段 `Push gh-pages with retry` 的 `run:` 内容）
- 输入/输出：输入为 action 已生成的本地 `gh-pages` 提交；输出为远端 gh-pages 更新（或明确失败）。
- 新内容（示意，实际以 ST2 的 CLI 为准）：
  ```yaml
  - name: Push gh-pages with retry
    if: github.event_name == 'push' || github.event_name == 'schedule'
    run: |
      python tools/ci/push_gh_pages.py \
        --repo . --remote origin --branch gh-pages \
        --attempts 5 --backoff-base 10
  ```
- 同时修正上方 `168-189` 行过时注释（“action 不支持推送重试 / 两工作流写不同目录，rebase 无内容冲突”需与新实现一致）。
- 验收：
  - 用例 10 中对 `benchmark.yml` 的断言转绿；
  - `python -m pytest tests/test_ci_push_gh_pages.py -q` 全绿；
  - 人工检查 `if:` 条件仍为 `push || schedule`（PR 行为不变）。

### ST4 替换 extras-health.yml 的内联脚本

- 文件：`D:\Zcode项目\SaiTu skill\.github\workflows\extras-health.yml`（替换 `264-284` 行）
- 输入/输出：同 ST3；该 job 的 `charts` 只在 `collect` 成功后运行。
- 验收：用例 10 对 `extras-health.yml` 的断言转绿；全文件 grep 无 `--depth=` / 无内联 `git push origin gh-pages:gh-pages` 循环。

### ST5 记录事故与契约文档

- 文件：
  - `D:\Zcode项目\SaiTu skill\docs\agent-context\fixes.md`（追加本次事故条目：run id、根因、修复、判据；遵循该文件既有格式）
  - `D:\Zcode项目\SaiTu skill\docs\ci-fix-plan.md`（本文件，实施完成时补“实际执行结果”小节）
- 输入：ST6 回归结果。
- 输出：可被下一次会话检索的上下文。
- 验收：`python -m tools.check_agents_md` 仍通过；`python -m pytest tests/test_docs_consistency.py -q` 通过。

### ST6 全量回归 + 提交 + 推送 main

- 文件：无新增改动（仅提交上述变更）。
- 命令（全部真实存在，见第 8 节）。
- 验收：
  1. 所有回归命令通过；
  2. `git status` 仅包含预期文件；
  3. 提交信息说明“为什么”（平台瞬时错误 + 残缺重试被放大）；
  4. 直接 `git push origin main`（用户已定，不走 PR）；
  5. 推送后确认 `CI` / `Benchmark` push 运行绿，并在下一轮 nightly 观察 `Push gh-pages with retry`。

---

## 7. 根因结论

### 7.1 为什么“没有新推送却变红”

- `main` 最后一次 push 是 2026-10-28（sha `68c086b`），此后只有 `schedule` 运行；
- 红点是 `Benchmark` run `42129078042`，`event=schedule`，`head_sha` 同为 `68c086b`；
- 同一 sha 的 7 轮 nightly 在此前全绿，说明代码没有变化；
- 触发源是 `benchmark.yml:7-9` 的 `cron: '0 18 * * *'`。所以这不是“无故变红”，而是**定时任务触发 + 本轮推送步骤失败**。

### 7.2 失败链条（证据支撑）

1. GitHub 服务端在 ref 更新时返回 `remote: fatal error in commit_refs_rules`（平台内部错误；仓库无 rulesets、分支未保护，相邻日同命令成功）——**不可从仓库根除**。
2. 我们的重试块把这次瞬时错误当成普通拒绝，进入 `fetch --depth=50` + `rebase`：
   - checkout 没有提交身份 → `Committer identity unknown` → rebase 失败；
   - 脚本把该失败误报为“rebase 冲突”；
   - `--depth=50` 使本地/远端提交计数失真（`Rebasing (1/15)`），存在历史改写风险。
3. 结果：一次本应“重试即过”的瞬时错误，被确定性放大为整轮红，并丢失当天 `dev/bench` 数据点。

### 7.3 已闭环 / 未闭环

- 已闭环：10-27 的 pytest 9.2.0 兼容性红点（引擎已钉死，7 轮绿验证）。
- 本次待修：两处内联重试块（`benchmark.yml`、`extras-health.yml`）的三个缺陷。
- 不可根治、只能收敛：GitHub `commit_refs_rules` 内部错误本身。
- 证据不足（见 A.6）：具体触发机制、`1/15` 的精确恢复、官方 incident 记录。

---

## 8. 回归与全局校验

### 8.1 全量测试与静态检查（本仓库真实命令）

```bash
# 默认门禁（tests/，排除 e2e）
python -m pytest tests/ -q

# 全量（解除 addopts 过滤，含 e2e；缺 e2e 依赖时优雅跳过）
python -m pytest tests/ -q -o addopts=

# lint / 格式
python -m ruff check .
python -m ruff format --check .

# 类型检查（本机平台 + Linux 视角，对齐 CI typecheck job）
python -m mypy
python -m mypy --platform linux

# 本地钩子全量预检（等价 CI 的 lint/typecheck/AGENTS.md 完整性）
pre-commit run --all-files

# 基准快速集（与 push 分支同款）
python -m pytest benchmarks/ -m "not bench_full" --benchmark-disable-gc

# 文档契约
python -m pytest tests/test_docs_consistency.py -q
```

### 8.2 YAML 最小校验（不新增工具）

```bash
python -c "import yaml,sys; [yaml.safe_load(open(p,encoding='utf-8')) for p in ['.github/workflows/benchmark.yml','.github/workflows/extras-health.yml']]; print('YAML OK')"
```

（`pyyaml` 由既有 dev 工具链带入；若本机未安装，不为此新增依赖，改为靠 ST3/ST4 的契约测试 + 推送后 Actions 的实际解析结果验证。）

### 8.3 安全检查

```bash
pip install "pip-audit>=2.7,<3"
pip-audit                 # 与 security.yml 的 gate 步骤同款（当前 PIP_AUDIT_IGNORE 为空）
pip-audit --strict -r requirements-dev.txt   # 与 report-only 步骤同款
```

### 8.4 “修复前必须红灯”的验证方式

| 用例 | 红灯命令（ST2 之前执行） | 红灯证据 | 转绿判据 |
|---|---|---|---|
| 缺提交身份下 rebase | `python -m pytest tests/test_ci_push_gh_pages.py::test_rebase_works_without_global_git_identity -q` | 报 `Committer identity unknown` / 脚本不存在 | ST2 后通过 |
| 浅 fetch 导致领先数异常 | `python -m pytest tests/test_ci_push_gh_pages.py::test_non_fast_forward_uses_full_fetch_without_depth -q` | 断言“领先数=1”失败（实现若用 `--depth` 会变 15） | ST2 后通过 |
| 平台瞬时错误重试 | `python -m pytest tests/test_ci_push_gh_pages.py::test_transient_commit_refs_rules_retries_then_succeeds -q` | 脚本不存在 | ST2 后通过 |
| workflow 契约 | `python -m pytest tests/test_ci_push_gh_pages.py::test_workflows_use_shared_push_tool -q` | 仍存在内联 `--depth=50` / 内联 push 循环 | ST3+ST4 后通过 |

> 硬性要求：以上红灯必须在 ST2/ST3/ST4 之前**实际执行并确认失败**；若某条在修复前已通过，说明测试没有覆盖缺陷，必须重写该用例后再进入 GREEN。

### 8.5 交付前检查清单

- [ ] ST0 基线全绿（且全量测试连续 3 次一致）
- [ ] ST1 红灯已截图/日志留档
- [ ] ST2~ST5 转绿
- [ ] 8.1 全部命令通过
- [ ] 8.3 依赖审计无新增漏洞
- [ ] 变更仅涉及：`tests/test_ci_push_gh_pages.py`、`tools/ci/push_gh_pages.py`、`.github/workflows/benchmark.yml`、`.github/workflows/extras-health.yml`、`docs/agent-context/fixes.md`、`docs/ci-fix-plan.md`
- [ ] 直接推送 `main`，并在推送后确认 `CI` / `Benchmark`（push）为绿
- [ ] 下一轮 nightly 观察 `Push gh-pages with retry`（成功则闭环）

---

## 9. 范围与决策（用户已定，不再“待确认”）

1. 修复成果**直接推送 `main`**，不建分支、不走 PR。
2. 不确定性必须**彻底消除**：本次涉及的是平台瞬时错误与自身残缺重试，不得用 skip / xfail / 自动重试 / 加大超时掩盖；测试侧也不得引入重试。处置见 B.1。
3. 计划文件位置：`docs/ci-fix-plan.md`（本文件）。
4. 明确不做（避免顺手扩大改动面）：不升级 action 版本、不新增依赖、不改测试矩阵、不改基准阈值、不重构无关 workflow、不对 `tests/` 做未审计的“稳定性改造”。
5. 用户确认本计划后才进入实施；实施前先执行 ST0 与 ST1（红灯）。

---

## 10. 实际执行结果（2026-11-06）

### 10.1 落地变更（依赖零新增）

| 文件 | 变更 |
|---|---|
| `tools/ci/push_gh_pages.py` | 新增：参数校验、完整 fetch、显式提交身份、失败分类、有界退避、`ls-remote` 回验 |
| `tests/test_ci_push_gh_pages.py` | 新增 16 条行为/契约测试 |
| `.github/workflows/benchmark.yml` | step 13 改为调用共享脚本；删除内联重试与 `--depth=50` |
| `.github/workflows/extras-health.yml` | charts step 改为调用共享脚本；charts job 补 `setup-python@v6 (3.12)`；sentinel 的 `--depth=50` 改为完整 fetch + ancestor 判定 |
| `docs/agent-context/fixes.md` | 新增 §4.13 事故记录 |
| `AGENTS.md` | 新增 §4.13 导航行 |
| `docs/ci-fix-plan.md` | 本文件 + 本节 |

### 10.2 红灯 → 绿灯（逐条实测）

| 用例 | 红灯证据（ST2 前实跑） | 绿灯 |
|---|---|---|
| `test_first_push_succeeds` | 脚本不存在，失败 | 通过 |
| `test_non_fast_forward_uses_full_fetch_without_depth` | 脚本不存在，失败 | 通过（远端 62 提交线性、无 merge） |
| `test_transient_commit_refs_rules_retries_then_succeeds` | 失败 | 通过（钩子计数=3，`class=transient`） |
| `test_rebase_works_without_global_git_identity` | 失败 | 通过（committer=`github-actions[bot]`） |
| `test_fatal_auth_fails_fast_without_retry` | 失败 | 通过（仅 1 次尝试，`class=fatal-auth`） |
| `test_missing_local_branch_fails_without_rebase` | 失败 | 通过（远端未变） |
| `test_attempts_exhausted_reports_classified_failure` | 失败 | 通过（`attempts=2`、`class=transient`） |
| `test_invalid_arguments_exit_2_without_side_effects` | 初版因“脚本缺失即 exit 2”假绿 → 已加“参数非法”文案断言重写后判红 | 通过 |
| `test_rebase_conflict_aborts_and_leaves_remote_untouched` | 失败 | 通过（abort 后工作区干净、远端未污染） |
| `test_benchmark_workflow_uses_shared_push_tool` | 失败（内联脚本） | 通过 |
| `test_extras_health_workflow_uses_shared_push_tool` | 失败（内联脚本 + `--depth=50`） | 通过 |
| `test_tool_source_has_no_shallow_fetch` | 失败（脚本不存在） | 通过 |
| `test_head_on_other_branch_still_pushes_target_branch` | 失败（`当前分支 'main' 不是目标分支 'gh-pages'`，复现 CI run 42182164644） | 通过（远端 gh-pages 更新，结束后 HEAD 切回 main） |
| `test_tool_source_has_no_shebang` | 失败（文件以 `#!` 开头，复现 CI run 42182164636 的 `EXE001`） | 通过 |
| `test_diagnostics_survive_non_utf8_console` | 失败（`\u53c2\u6570\u975e\u6cd5` 转义串，复现 windows 三腿判红） | 通过（`PYTHONIOENCODING=cp1252` 下仍是可读中文） |
| `test_tool_output_decoded_as_utf8_on_non_utf8_runner` | 失败（`stderr` 为 `None`：替换 `subprocess._text_encoding` 为 cp1252，复现二次推送后 windows 三腿判红） | 通过（测试侧统一按 UTF-8 解码） |

首轮红灯阶段实跑结果：**11 failed / 0 passed**；转绿后：**12 passed**。
推送后 CI 反证暴露 4 条本地测不到的缺陷，逐条补红灯（1 / 1 / 1 / 1 failed）后修复，现 **16 passed**。

### 10.3 回归与全局校验（本机实测）

- `python -m pytest tests/ -q`：变更前连续两次 **1059 passed / 29 skipped / 38 deselected**；首轮变更后 **1071 passed**（453s，+12 条新增）；二次修复后 **1074 passed**（447.80s，+15 条新增）；三次修复后 **1075 passed / 29 skipped / 38 deselected**，无新增失败。
- `python -m pytest tests/ -q -o addopts=`（首轮变更后）：**1109 passed / 29 skipped**。
- `python -m pytest benchmarks/ -m "not bench_full" --benchmark-disable-gc`：**8 passed / 1 deselected**（5.59s）。
- `python -m ruff check .`、`python -m ruff format --check .`：通过（103 files）。
- `python -m mypy`、`python -m mypy --platform linux`：通过（82 source files）。
- `pre-commit run --all-files`：AGENTS.md 完整性、ruff、format、mypy 全部 Passed。
- `python -m tools.check_agents_md`、`tests/test_docs_consistency.py`：通过。
- 两条 workflow YAML 解析：`YAML OK`。
- 安全：在全新 venv 复刻 `security.yml` 门禁（`pip install -e .` + `pip-audit>=2.7,<3`）→ **No known vulnerabilities found**（本机主环境的告警来自既有 dev 工具链，与本次零依赖变更无关）。

### 10.4 推送与 CI 终验

- 推送方式：直接 `git push origin main`（用户已定），凭据用本机 git credential 里已有的。
- 首推 `052d77b`（2026-11-06T07:38:05Z）后新触发的两条运行，都成为新的反证：
  - **Benchmark** run **42182164644**（event=`push`）：step 13 在 40ms 内退出 1，
    日志 `push-gh-pages: 当前分支 'main' 不是目标分支 'gh-pages'`。根因是我们的脚本
    要求 HEAD 在目标分支，而 `github-action-benchmark` 提交完 gh-pages 会 `git checkout -`
    切回 main（旧内联脚本用 `git push origin gh-pages:gh-pages`，从不看 HEAD）。
  - **CI** run **42182164636**（event=`push`）：lint job 报 `EXE001`（新脚本带 shebang，
    NTFS 无 exec 位语义，本地 ruff 恒不报，pitfalls §3.8 早有口径），windows 三腿
    在 `test_invalid_arguments_exit_2_without_side_effects` 判红（cp1252 控制台把中文诊断
    写成 `\uXXXX` 转义串）；ubuntu / macos 腿全绿，说明是平台语义差异而非逻辑错误。
- 二推 `b192548`（08:05:59Z）：**Benchmark 42185258348 转绿**（gh-pages push 成功；
  说明「按需切分支」修复生效），**CI 42185258304 仍红**——`ruff` 已绿，但 windows 三腿
  换成了更隐蔽的形态：runner 的 ACP 是 cp1252，测试辅助函数按 locale 解码子进程输出，
  reader 线程里的 `UnicodeDecodeError` 被吞掉后 `stderr` 静默变成 `None`；本机 ACP 恰好
  是 UTF-8，所以本地永远绿。
- 三次修复（逐条先红灯再转绿，见 10.2 最后 4 行）：脚本按需 `git switch` 目标分支并在
  结束时切回、去掉 shebang、启动时把 stdout/stderr 固定为 UTF-8；测试侧 `_run` 统一按
  UTF-8 解码。红灯复现改用替换 `subprocess._text_encoding`，不再依赖机器语言设置。
- 三推 `687756c`（08:33:19Z）：**Benchmark 42188510298 success**（gh-pages 真实推进 `d3b9c791`，
  11-05 事故的 gh-pages 链路至此闭环）；**CI 42188510332 仍红**，但失败面整体换到了另一头——
  windows 四腿转绿，**三条 py3.10 腿**（ubuntu / macos / windows）改为红在
  `test_tool_output_decoded_as_utf8_on_non_utf8_runner`：
  `AttributeError: <module 'subprocess' …>/python3.10/subprocess.py'> has no attribute '_text_encoding'`。
  即 10.2 表最后一行「红灯复现改用替换 `subprocess._text_encoding`」这个手法本身是新的缺陷，
  它把一条红灯换成了一条恒真的绿 + 三条矩阵下限腿的红灯。**本轮结论见 §11。**



---

## 11. 第四轮：收掉 §10.4 遗留的 py3.10 三腿红灯（2026-11-06）

### 11.0 本轮的五项口径（§1–§5 是为 gh-pages 那轮写的，本轮逐条说明是否沿用）

- **依赖声明**：新增/变更依赖 **0 项**——`pyproject.toml` 与 `requirements-dev.txt` 一行未动
  （`git diff --name-only 687756c..HEAD` 只有 `tests/` 与 `docs/`）。仅本机一次性工具链
  `uv python install 3.10` + `uv venv` + `pytest==9.1.1`（不进仓库、不进 CI 路径、用完删除）。
- **启动说明**：环境准备与验证命令见 11.4 末的复现块；全量口径仍是仓库真实存在的
  `make check` / `make test` / `python -m pytest tests/ -q --cov=flashgaze`
  （覆盖率门禁不在 `make test` 里，见 AGENTS.md §5）。
- **错误处理**：不改任何生产分支。被测对象 `tools/ci/push_gh_pages.py` 的既有语义保持不变——
  `_validate()` 非法入参走 rc=2、`_classify()` 四类（`fatal-auth` 不重试 / `transient`
  与 `non-fast-forward` 有界退避 / `unknown` 重试）、失败落 `::error::` 并用 `ls-remote` 回验。
  本轮新增的是**测试侧**的异常口径：解码失败在 POSIX 抛异常、在 Windows 返回 `None`，
  所以断言降到字节层，两种形态都不再被依赖。
- **参数校验**：不新增入参。用例复用 `_run` 已有的 `encoding: str | None = "utf-8"`；
  新守卫无参数，扫描根来自 `REPO_ROOT / "tests"`，边界为非 `*.py` 不扫、
  `sys.stdlib_module_names` 交集为空时返回空清单；判定为「一旦发现 stdlib 私有补丁目标即整体
  判红」，不设白名单（白名单等于给下一次事故留门）。
- **基础测试用例**：正常 / 异常 / 边界三类见 11.4 的逐条红绿表（含两条合成反例必须被守卫抓到、
  一条项目模块对照不得误报、一条变异复核必须判红）。

### 11.1 失败面（逐腿用 job 日志确认，不靠推断）

| run | event | sha | 结论 | 细节 |
|---|---|---|---|---|
| 42188510332 | push | `687756c` | CI failure | 19 job 中 3 条 py3.10 腿红在 step 5，其余 16 绿；`extras` / `e2e` 三个 job **skipped（非绿）** |
| 42188510298 | push | `687756c` | Benchmark success | gh-pages 推进 `d3b9c791` |

ubuntu py3.10 job 127794496252 日志逐字：`= 1 failed, 1069 passed, 29 skipped, 28 deselected, 3 warnings in 138.24s`
→ 每条腿**只红 1 个用例**，失败面精确，不存在被首个报错掩住的其他 3.10 缺陷。

### 11.2 根因（两层）

1. `subprocess._text_encoding` 是 **3.11 才引入的私有函数**（本机 3.11.16 / 3.12.10 实测存在、
   实现走 `locale.getencoding()`；3.10 的 `subprocess.py` 无此名）。`monkeypatch.setattr` 默认
   `raising=True`，属性不存在即在用例 setup 阶段抛 `AttributeError`。本仓 `requires-python >=3.10`，
   矩阵含 3 条 3.10 腿 → 只有它们红。开发机是 3.12，9 条腿在 3.11+，故本地与多数腿恒绿。
2. **更贵的一层**：这条用例在 3.11+ **本来就是恒真的**——同文件 `_run` 已写死 `encoding="utf-8"`，
   `subprocess` 的「默认文本编码」路径根本不被走，补丁打在一个不参与任何行为的私有符号上。
   上一轮想复现的机制（父进程按 runner ACP 解码 → reader 线程吞异常 → stderr 变 None）
   并没有因为补丁成功而被测到。
3. 静态门禁为何放行：`mypy strict`（`python_version=3.10`）只拦**属性访问**形态
   （`subprocess._text_encoding` 会报 no attribute），而这里符号名是 `setattr` 的**字符串实参**；
   ruff `target-version="py310"` 只管语法层，默认规则集不含 SLF001。

### 11.3 修法（生产代码 / workflow / 阈值 / 矩阵 / 超时预算一条未动）

- `tests/test_ci_push_gh_pages.py`：删掉私有符号补丁，改走 `_run` **已有的公开 `encoding` 参数**
  做双向断言——① `encoding="cp1252"` 时中文诊断整段丢失、② 默认（显式 UTF-8）时诊断完整。
  **当时以为**这是「纯 Python 层机制、与机器语言设置无关，12 腿一致」——那句已被 run 42198208112
  证伪（POSIX 在主线程抛 `UnicodeDecodeError`、Windows 才吞成 `None`），二次翻车与终态见 11.7
  反向那半会真的产生 reader 线程异常，故加
  `@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")`
  显式声明「这是被证明的机制本身」，避免将来 `filterwarnings` 收紧成 error 时把它打红。
- `tests/test_coverage_gate_contract.py` 19 → **20 条**：新增 `test_no_test_patches_private_stdlib_api`
  （AST 扫 `tests/**/*.py`，import 根名 ∩ `sys.stdlib_module_names` 判归属；对象形式与字符串形式
  都拦——后者正是 mypy 看不见的那一半）。
- **否决的改法**：`raising=False`（把红换成静默恒真，正是本条要拦的形态）；
  `skipif(sys.version_info < (3,11))` 或把该文件从 3.10 腿摘掉（用「不测」冒充「修好」）；
  把守卫范围扩到「一切私有符号」（会误报 `argparse._StoreTrueAction` 这类读取，把既有绿测试全打红）。

### 11.4 红灯 → 绿灯（逐条实测，含真 3.10 解释器）

| 项 | 修复前 | 修复后 |
|---|---|---|
| `test_no_test_patches_private_stdlib_api`（真实扫描） | 失败：`tests/test_ci_push_gh_pages.py → 376: subprocess._text_encoding` | 通过（清单为空） |
| 同用例合成反例（对象形式 + 字符串形式） | 随守卫一起红 | 通过（两种形态都被抓） |
| 同用例项目模块对照（`hs._evaluate_cv_and_portrait`） | — | 通过（不误报） |
| `…decoded_as_utf8_on_non_utf8_runner` **@CPython 3.10.20 真机** | **失败**（AttributeError，与 CI annotation 逐字同源；该文件 1 failed / 15 passed） | 通过（该文件 16 passed） |
| 同文件 @3.11.16 / @3.12.10 | 通过但恒真 | 通过且真在测契约（各 16 passed） |
| 变异复核：`_run` 默认 `encoding` 改 `"cp1252"` | — | **判红**：`TypeError: can only concatenate str (not "NoneType")`（与 CI run 42185258304 的原始签名逐字相同）；还原后转绿，`git diff` 无残留 |

本地 py3.10 复现通道（写下来，别只留在这轮会话里）：

```bash
uv python install 3.10 && uv venv --python 3.10 "$TEMP/fgpy310"
uv pip install -p "$TEMP/fgpy310/Scripts/python.exe" "pytest==9.1.1"
# tests/conftest.py 需要 cv2 / numpy / PIL，单文件复现用 --noconftest 绕开
"$TEMP/fgpy310/Scripts/python.exe" -m pytest tests/test_ci_push_gh_pages.py --noconftest -q
```

### 11.5 远端终验

- 判据：新 CI run 的 **12 条腿全绿**，且 `extras` 与 `e2e` 由 skipped 变**真实执行并 success**
  （它们只因 test 腿红而被连带跳过，本轮是它们在新配置下的首次真实执行机会）。
- 结果（**已终验通过**）：`5cc0781` 推送后 CI run **42200923304**（event=`push`、
  2026-11-06T10:12:51Z 起跑、10:43 前后收口）结论 **success**，21 个 job =
  **20 success + 1 skipped**（skipped 是设计成非门禁的 `e2e (playwright, webkit, optional)`），
  **0 失败**。逐项核对：
  - 12 条腿全绿，含三条 py3.10：ubuntu 测试步 145s / 全程 189s、macOS 307s / 418s、
    windows 605s / 741s——三条腿都真实执行了 step 5，不是被跳过；
  - `ruff` / `mypy` / `AGENTS.md integrity` 全绿；
  - `extras` 双腿首次真实执行并 success（ubuntu 626s、macOS 879s），且
    **step 6 `Coverage gate (hard floors)` 为 success**（82/80/95 三条逐模块下限真的比过了，
    不是 §4.9 那种「无数据」假绿）；
  - 产物 **28 个**：`coverage-*` 14 + `junit-*` 14（12 腿 + extras 双腿各一份），
    `junit-extras-macos-*` / `coverage-extras-macos-*` 均在；
  - `e2e` chromium 67s、firefox 122s 全绿；
  - 同 push 的 Benchmark run **42200923177** success，gh-pages 连续推进
    `bf2acf93`(37d7b7f) → `0b859dd8`(5cc0781)——新推送工具连续三轮真实生效。
- 中间态如实保留：`37d7b7f` 的 CI run **42198208112** 是 failure（windows 四腿绿、
  ubuntu + macOS 八腿红，见 11.6）。它同时证明两件事：py3.10 的原始缺陷确已被第一版修好，
  而第一版的反向对照在 POSIX 上是另一种死法。
- 文档跟进提交的运行结论（说明「纯文档提交没有把任何门禁搞红」，也解释 Actions 历史里那几条
  cancelled）：`8b1345d` / `5232bbe` / `50c4713` 三次 CI 因 `concurrency.cancel-in-progress`
  被后续推送取消（**cancelled 不是 failure**，是我连推文档的副作用）；
  tip `475633d` 的 CI run **42206547889 = success**（21 job，0 非绿）、
  Benchmark **42206548111 = success**，gh-pages 推进到 `f8bef9a8`。
- 遗留：① `schedule` 分支的 gh-pages 推送在新工具下尚无样本，下一轮 nightly 才是首验；
  ② `tools/ci/push_gh_pages.py::_git` 用 `text=True` 未显式给 `encoding`（`errors="replace"`
  故不崩，只在非 ASCII git 诊断上 mojibake，且该脚本只在 ubuntu/py3.12 跑）→ 记录不动；
  ③ `tools/ci/` 不在 mypy 的 `files = [flashgaze, tests, tools/bench]` 内 → 无类型门禁；
  ④ 11-05 的 Benchmark 趋势点已永久缺失，gh-pages 图表留洞；⑤ Codecov token 仍缺（仓库设置项）。

### 11.6 安全检查口径（本机 pip-audit 会红，但仓库不红——别把它读成漏洞暴露）

本轮零依赖变更（`git diff --name-only 687756c..HEAD` 只有 `tests/` 与 `docs/`），但本机
`python -m pip_audit` 仍报 14 个包命中通告。逐条比对后的结论：

- 命中集里唯一落在**运行时依赖**上的是 `pillow 12.2.0`（修复线 12.3.0）。本机是过期缓存：
  PyPI 当前解析到 **13.0.0**（2026-10-16），而约束是 `Pillow>=10.0.0,<14` →
  CI 的 `pip install -e .` 装的是已修复版本，`Security` workflow 的 success 是真的。
- `mcp 1.29.0` 属 **extras**（`[mcp]`），security.yml 的主扫描环境不装它；
  其余（`virtualenv` / `werkzeug` / `setuptools` / `pip` / `aiohttp` / `msgpack` 等）
  来自本机额外装的工具链，均不在 CI 的门禁环境里。
- **给下一轮的提醒**：`make install` 不装 `-e .`（见 AGENTS.md §5），所以开发机的依赖树
  与 CI 门禁环境本来就不是同一份。要复现门禁口径得新建干净 venv 只跑 `pip install -e .`，
  否则会把本机缓存读成仓库暴露。豁免单 `PIP_AUDIT_IGNORE` 目前为空，无需登记。

### 11.7 二次翻车：`_run(encoding="cp1252")` 的失败形态本身是平台专属的

`37d7b7f` 推送后 CI run **42198208112** 的结果与本节 11.4 的预判完全不同：

| 腿 | 结果 | 原因 |
|---|---|---|
| windows ×4 | **绿** | reader 线程吞掉 `UnicodeDecodeError` → `stderr=None` → 「拿不到诊断」成立 |
| ubuntu ×4 + macOS ×4 | **红** | 同一条断言在主线程直接抛 `UnicodeDecodeError: 'charmap' codec can't decode byte 0x8f in position 16` |
| 每条腿合计 | `1 failed, 1070 passed, 29 skipped, 28 deselected` | py3.10 的原始缺陷确已被修好，只剩我这一个新用例 |

机理（已读 3.12 `Lib/subprocess.py` 核对）：POSIX 的 `_communicate` 用 `_PopenSelector` 读**原始字节**，
回到主线程才 `self._translate_newlines(...)` 解码 → 异常抛给调用方；Windows 的 `_communicate` 起
`_readerthread` 在子线程 `fh.read()` → 异常逃出线程、收集值静默留 `None`。
**我在 Windows 上验证了「吞成 None」这一种死法，就替 12 条腿担保了全部死法**——与 pitfalls §3.9
同族，且这一笔是本轮新欠的，不是继承的。

终态（仍零生产代码改动）：反向对照降到**字节层**，正向仍走 `_run` 的公开默认值。

```python
raw = subprocess.run(cmd, cwd=REPO_ROOT, env=clean_env, capture_output=True, check=False)
combined = raw.stdout + raw.stderr
assert "参数非法" in combined.decode("utf-8")  # 子进程发的确实是 UTF-8
with pytest.raises(UnicodeDecodeError):
    combined.decode("cp1252")  # runner 的 ACP 解不开这份字节
ok = _run(cmd, REPO_ROOT, env=clean_env, check=False)
assert "参数非法" in ok.stdout + ok.stderr  # 显式 UTF-8 才拿得到诊断
```

两段断言都不再进入 subprocess 的任何平台分支，12 腿同码同判；
`filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")` 标记随之删除
（bytes 模式下不再产生 reader 线程异常）。

**终态证据**：py3.12 / py3.11.16 / **CPython 3.10.20 真机** 各 **16 passed**；
变异复核（把 `_run` 默认 `encoding` 改成 `"cp1252"`）本机以 `TypeError: can only concatenate str
(not "NoneType")` 判红、还原后转绿、`git diff` 无残留；全量
**1076 passed / 29 skipped / 38 deselected**、覆盖率 90.49% ≥ 80；
`ruff check` / `format --check`（103 files）/ `mypy` 两面（82 files）/ `check_agents_md` 全绿。
