# FlashGaze PEP 695 类型语法兼容性跟踪与解锁治理

> 配套文件：`pyproject.toml`（`[tool.mypy]`、`numpy` 约束）、`requirements-dev.txt`（`mypy` 约束）、`.github/workflows/ci.yml`（`typecheck` job）。
> 适用范围：`flashgaze/`、`tests/`、`tools/bench` 的静态类型检查（`[tool.mypy] files`）。
> 解锁口径：**OR** —— 满足「mypy 上游支持低版本目标下的 PEP 695 向下兼容解析」或「项目最低支持 Python 升到 3.12+」任一条件即解锁。

## 1. 背景与现状摘要

PEP 695（Python 3.12 引入）提供了更简洁的类型参数语法：

- `type` 语句定义类型别名：`type Vector = list[float]`（替代 `Vector = list[float]` 裸赋值 + `typing.TypeAlias`）。
- 泛型类/函数内联类型参数：`class Box[T]: ...` / `def f[T](x: T) -> T: ...`（替代 `TypeVar` + `Generic[T]`）。

当前项目约束：

- `[project] requires-python = ">=3.10"`，因此 `[tool.mypy] python_version = "3.10"`、`[tool.ruff] target-version = "py310"`，类型检查只覆盖最低支持版本的语义。
- mypy 复用 Python `ast` 解析 stub 与源码，**在 `python_version=3.10` 目标下无法解析 PEP 695 语法**，会报语法级错误（而非类型错误），因此代码库现阶段**禁止**使用 PEP 695 语法，继续沿用 `TypeVar` / `typing.TypeAlias` / `Generic` 传统写法。
- 依赖侧连带约束：`numpy>=1.24.0,<2.3` 的上限有**两个独立成因**，任一未解除都不能放宽——① numpy **2.3** 起 `requires-python` 升至 `>=3.11`（官方发布说明：2.3.0 支持 Python 3.11–3.13），与本项目 `requires-python = ">=3.10"` 直接冲突，这是当前 `<2.3` 的**生效约束**；② numpy **2.5+** 内置 stubs 使用 PEP 695 `type` 语法，与 mypy 的 py3.10 目标冲突。
- mypy 的 PEP 695 解析门槛实测为 **3.12**（mypy 1.20.2：`--python-version 3.10` 与 `3.11` 均报 `Type statement is only supported in Python 3.12 and greater`，仅 `3.12` 通过）。因此「把 mypy 目标升到 3.11」**不能**解除成因 ②，解锁下限必须是 3.12+。

> 上游跟踪现状（截至 2026-08）：mypy issue [#15238 "Support for PEP 695"](https://github.com/python/mypy/issues/15238) 仍指出低 `python_version` 目标下解析受限，未完整支持向下兼容。本治理文档即用于持续跟踪该进展。

## 2. 约束链

```
requires-python = ">=3.10"            # pyproject [project]
        │
        ├─→ python_version = "3.10"   # pyproject [tool.mypy]
        │        └─→ 禁止 PEP 695 语法（mypy 用 ast 解析，低版本目标语法级报错）
        │
        ├─→ target-version = "py310"  # pyproject [tool.ruff]（ruff 仅 lint/format，不解析 PEP 695 语义）
        │
        └─→ numpy>=1.24.0,<2.3        # 上限双因：① numpy 2.3 起 requires-python >=3.11（生效项，撞本项目 3.10 下限）
        #                             #    ② numpy 2.5+ stubs 含 PEP 695 `type`，mypy 目标 <3.12 无法解析
```

**单一事实来源（SSoT）**：本文件。配置处（`pyproject.toml`、`requirements-dev.txt`）仅保留一行指向本文件的引用注释，避免约束链信息碎片化导致维护漂移。

## 3. 上游跟踪清单

定期（建议随 dependabot 月度 PR 评审时）复核以下信号：

| 跟踪项 | 位置 / 链接 | 关注信号 |
|---|---|---|
| mypy PEP 695 支持总议题 | [python/mypy#15238](https://github.com/python/mypy/issues/15238) | 是否声明支持 `python_version < 3.12` 目标下的 PEP 695 解析；是否合入相关 PR |
| mypy 发布说明 | [mypy changelog](https://mypy.readthedocs.io/en/stable/changelog.html) | 出现 "PEP 695" + "older Python versions" / "backport parsing" 类条目 |
| mypy 版本区间 | `requirements-dev.txt` `mypy>=1.11,<2` | 解锁后是否需放宽上界以接纳新特性版本 |
| numpy stubs PEP 695 使用 | `numpy` 2.3（`requires-python` 跃迁）与 2.5+（stubs 语法）发布说明 | 2.3 起是否恢复 py3.10 支持；stubs 是否回退/隔离 PEP 695 语法，或 mypy 已能兼容 |
| 项目 Python 下限决策 | `pyproject.toml` `requires-python` | 是否将下限提升至 `>=3.12` |

**本地快速验证命令**（跟踪复核时用）：

```bash
# 切到拟解锁的目标版本，跑一次 typecheck，观察 PEP 695 是否仍报语法错误
python -m mypy --python-version 3.12 flashgaze   # 仅验证解析能力，不改 pyproject
```

> 注意：上面命令以 `--python-version` 覆盖仅用于本地探测，**不修改** `pyproject.toml` 的正式配置；正式解锁见第 5 节。

## 4. 解锁检查单（OR 两路）

满足以下**任一**条件即可进入解锁流程：

### 路线 A —— mypy 上游支持低版本目标的向下兼容解析

- [ ] mypy 官方发布说明/changelog 明确支持在 `python_version < 3.12` 目标下解析 PEP 695 语法。
- [ ] 本地用 `python -m mypy --python-version 3.10 flashgaze` 对一份含 PEP 695 语法的样例文件验证通过（无语法级错误）。
- [ ] 确认 `numpy>=2.3`（或更高）stubs 在该 mypy 版本下不再触发语法级冲突（或 numpy 问题已独立消除）。

### 路线 B —— 项目最低支持 Python 升到 3.12+

- [ ] 产品/维护侧决策将 `requires-python` 下限提升至 `>=3.12`（并同步 classifiers）。
- [ ] CI `test` 矩阵、运行环境（含 headless 服务器）确认支持 3.12+。
- [ ] 确认升级下限不会切断仍在用 3.10/3.11 的用户（属产品决策，需评审）。

> 路线 B 触发时，PEP 695 语法在 `python_version=3.12` 目标下天然合法，无需等 mypy 上游补丁；但**仍需**走第 5 节迁移步骤并验证。

## 5. 解锁后的迁移步骤

一旦第 4 节任一路线满足，按以下顺序执行（建议单 PR 或短序列 PR，配 tracking Issue）：

1. **提升目标版本**：
   - `pyproject.toml`：`[tool.mypy] python_version` 由 `"3.10"` 改为 `"3.12"`（路线 B）；或维持 3.10 仅当路线 A 成立。
   - `pyproject.toml`：`[tool.ruff] target-version` 同步调整（`"py312"`）以保持 lint 与类型检查一致。
   - `requires-python` 与 `classifiers` 随路线 B 一并更新。
2. **放宽 numpy 上限**：`numpy>=1.24.0,<2.3` → 放宽至 `<2.5` 或更高（遵循 numpy 自身支持的 Python 区间），并**重跑 CI `extras-health` / `extras` job** 验证依赖解析（既有维护约定）。
3. **全量语法迁移**（核心工作）：
   - 扫描 `flashgaze/`、`tests/`、`tools/bench` 中所有 `TypeVar` / `Generic[...]` / `typing.TypeAlias` / 裸类型别名赋值。
   - 改写为 PEP 695 语法：`type X = ...`、内联 `[T]` 类型参数。
   - 建议增量分批（按子包 `models` / `utils` / `core` / `plugins` / `cli` / `webui` 顺序，与既有 mypy 收紧路线图一致），每批跑 `python -m mypy` 确认无回归。
4. **验证门禁**：
   - 本地：`python -m mypy && python -m ruff check . && python -m ruff format --check . && pytest`。
   - CI：`typecheck` job（mypy）、`lint` job（ruff）、`test` 矩阵全绿。
   - extras job：确认放宽 numpy 后可选依赖解析正常（路线 A 不放松 numpy 时跳过）。

## 6. 回滚与风险说明

| 风险 | 说明 | 缓解 |
|---|---|---|
| 过早解锁 | 在 mypy 未真正支持的情况下误用 PEP 695，导致 `typecheck` 全红 | 严格按第 4 节检查单逐项验证（尤其路线 A 的本地 `--python-version` 探测）后再改 `pyproject` |
| numpy 上限松动引入不兼容 | 放宽 `<2.3` 后 numpy 2.3+ 的运行时/API 变动影响 `cv_engine` | 解锁前先小范围验证 numpy 2.3+ 在 headless 环境 import 与核心评分路径；并跑 extras job |
| 迁移引入类型回归 | PEP 695 改写改变了泛型推断，可能暴露原被传统写法掩盖的类型问题 | 分批迁移 + 每批 mypy 全量；保留 `strict = true` 不降档 |
| 用户被切断 | 路线 B 升最低 Python 至 3.12 后，3.10/3.11 用户无法安装 | 属产品决策，需评审与发布公告；非单纯技术动作 |

**回滚**：若解锁后 CI 或运行出现 PEP 695 相关回归，可逆序执行第 5 节（先回退迁移提交，再恢复 `python_version` / `numpy` 上限 / `requires-python`），并回到本文件的「未解锁」基线状态，继续跟踪上游。

## 7. 维护约定

- 本文件为 PEP 695 兼容性的**唯一权威说明**（SSoT）；配置注释只做指针，不展开细节。
- 任何对 `[tool.mypy] python_version`、`numpy` 上限、`requires-python` 的修改，都须同步更新本文件第 4/5 节状态。
- 上游跟踪信号（第 3 节）建议随 dependabot 月度评审时顺带复核，无需独立节奏。
