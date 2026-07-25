# FlashGaze 工程基础设施改进计划

> 制定日期：2026-07-24
> 适用范围：`flashgaze/` 目录下的全部源码、测试与打包配置
> 目标读者：维护者 / 贡献者 / CI 系统

---

## 1. 现状分析

### 1.1 当前工程基础设施盘点

| 维度 | 现状 | 评估 |
| --- | --- | --- |
| 打包配置 | `setup.py` 承担全部元数据 + 依赖 + entry_points | 可用，但已属旧式（PEP 517/518 未启用） |
| 依赖管理 | `requirements.txt` 仅 `-e .`；`requirements-dev.txt` 只有 pytest/pytest-cov | 缺少 lint / type check 工具 |
| CI/CD | 无 `.github/workflows/` 目录，无任何流水线 | 完全缺失，push 后无自动化校验 |
| 代码质量工具 | 无 ruff / flake8 / black / isort 配置 | 完全缺失 |
| 静态类型检查 | 无 mypy 配置，源码中类型注解稀疏 | 完全缺失 |
| 测试 | 存在 `tests/` 目录与 pytest，共 134 项用例 | 基础齐全，但未在 CI 中运行 |
| 版本控制忽略规则 | `.gitignore` 仅位于仓库根目录（`h:\45001\Documents\SaiTu skill\.gitignore`），`flashgaze/` 子目录无独立 `.gitignore` | 可接受，但本地构建产物（`build/`、`dist/`、`*.egg-info`）已覆盖 |
| Python 版本约束 | `python_requires=">=3.10"`，classifiers 声明 3.10/3.11/3.12 | 矩阵清晰，但未在 CI 中验证跨版本兼容 |

### 1.2 关键缺口

1. **CI/CD 完全缺失**：push 到 `main` 或提交 PR 时，没有任何自动化测试 / lint / 类型检查。回归风险完全依赖本地自觉。
2. **代码质量工具空白**：没有统一的 lint 与 format 工具，代码风格仅靠人工维护，难以在多人 / 多 Agent 协作下保持一致。
3. **静态类型检查空白**：`flashgaze/core/cv_engine.py`、`vlm_client.py` 等模块涉及外部输入与数值计算，缺类型校验容易在运行时暴露 `None` / 类型错配问题。这与项目记忆中的硬约束（"所有外部输入默认不可信"）形成隐患。
4. **打包配置陈旧**：`setup.py` 是 PEP 517 之前的写法，现代 Python 工具链（pip、build、hatch、uv）均优先识别 `pyproject.toml`。当前写法虽可用，但无法被新工具直接消费元数据。
5. **开发依赖不完整**：`requirements-dev.txt` 没有 ruff、mypy，新贡献者必须自行安装才能复现质量检查。

### 1.3 现有约束（来自项目记忆，需严格遵循）

- `requirements.txt` 不得将 `mcp` 列为必装依赖；必须通过 `extras_require`（迁移后为 `[project.optional-dependencies]`）提供。
- MCP Server 工具必须包含 try-except，错误时返回 `code=4` 结构化响应。
- 工作空间清理默认 `dry_run=True`，路径校验防越界删除。
- 配置必须通过 `merge_env()` 合并环境变量。

本计划所有文件内容模板均遵循上述约束。

---

## 2. 改进目标

### 2.1 添加 GitHub Actions CI 流水线（测试 + lint + 类型检查）
- 触发：push 到 `main` + 所有 PR
- 矩阵：Python 3.10 / 3.11 / 3.12
- 步骤：checkout → setup-python → 安装 `-e ".[mcp]"` + `requirements-dev.txt` → `ruff check .` → `mypy flashgaze` → `pytest -v`

### 2.2 添加 ruff 代码质量工具（lint + format）
- 行长度 100
- 启用规则集：`E`（pycodestyle errors）、`F`（pyflakes）、`W`（pycodestyle warnings）、`I`（isort）、`UP`（pyupgrade）
- 同时承担 import 排序与废弃语法升级检测

### 2.3 添加 mypy 静态类型检查配置
- `python_version = "3.10"`
- `strict = false`（初次引入，逐步收敛，避免一次性炸出大量告警阻塞 CI）
- `warn_return_any = true`
- `warn_unused_configs = true`

### 2.4 将 setup.py 迁移到 pyproject.toml（PEP 621 标准）
- 全部元数据迁入 `[project]`
- `extras_require` → `[project.optional-dependencies]`
- `entry_points` → `[project.scripts]`
- 保留 `setup.py` 为空壳（`from setuptools import setup; setup()`），因为 `pip install -e .` 在某些旧版 pip 下仍需它

---

## 3. 详细实施步骤

> 执行顺序：3.1 → 3.3 → 3.4 → 3.2（先完成本地配置，再让 CI 消费这些配置）。

### 3.1 创建 `pyproject.toml`

**文件路径**：`flashgaze/pyproject.toml`（新建）

**完整文件内容**：

```toml
[build-system]
requires = ["setuptools>=68.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "flashgaze"
version = "0.1.0"
description = "瞬选灵眸 - AI 辅助图片评分与筛选 CLI + MCP Server"
readme = "README.md"
requires-python = ">=3.10"
license = { text = "MIT" }
authors = [
    { name = "FlashGaze Contributors" },
]
keywords = ["image", "scoring", "photography", "mcp", "cli", "cv", "vlm"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: End Users/Desktop",
    "License :: OSI Approved :: MIT License",
    "Operating System :: OS Independent",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Topic :: Multimedia :: Graphics",
    "Topic :: Scientific/Engineering :: Image Recognition",
]
dependencies = [
    "opencv-python>=4.8.0",
    "Pillow>=10.0.0",
    "numpy>=1.24.0",
    "requests>=2.31.0",
    "pillow-heif>=0.15.0",
]

[project.urls]
Homepage = "https://github.com/QianQianLuLu1/FlashGaze"
Repository = "https://github.com/QianQianLuLu1/FlashGaze"

[project.optional-dependencies]
mcp = ["mcp>=1.0.0"]

[project.scripts]
flashgaze = "flashgaze.cli.entry:main"

[tool.setuptools.packages.find]
include = ["flashgaze*"]
exclude = ["tests*"]

[tool.ruff]
line-length = 100
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP"]
ignore = [
    "E501",
]

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["E402"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

[tool.mypy]
python_version = "3.10"
strict = false
warn_return_any = true
warn_unused_configs = true
ignore_missing_imports = true
exclude = [
    "tests/",
    "build/",
    "dist/",
]

[[tool.mypy.overrides]]
module = ["cv2.*", "PIL.*", "mcp.*"]
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v"
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
```

**关键说明**：
- `[build-system]` 声明 PEP 517 构建后端，让 `pip install -e .` 与 `python -m build` 走现代路径。
- `dependencies` 完全对齐原 `setup.py` 的 `install_requires`，**未包含 `mcp`**（遵循项目记忆硬约束）。
- `[project.optional-dependencies].mcp` 对齐原 `extras_require["mcp"]`，通过 `pip install -e ".[mcp]"` 启用 MCP Server。
- `[project.scripts]` 对齐原 `entry_points["console_scripts"]`，`flashgaze` 命令入口不变。
- `[tool.setuptools.packages.find]` 显式 include `flashgaze*`，避免误打包 `tests/`。
- `[tool.ruff.lint]` 中 `ignore = ["E501"]` 防止行长度规则与 `line-length = 100` 冲突时反复报错；实际行长度由 formatter 保证。
- `[tool.mypy]` 中 `ignore_missing_imports = true` + `overrides` 双保险处理 `cv2` / `PIL` / `mcp` 的类型存根缺失。

**验证方法**：
```powershell
cd "h:\45001\Documents\SaiTu skill\flashgaze"
python -m pip install -e ".[mcp]"
python -c "import flashgaze; print(flashgaze.__version__)"
flashgaze --version
```
预期：输出版本号 `0.1.0`，无安装错误。

---

### 3.2 创建 `.github/workflows/ci.yml`

**文件路径**：`flashgaze/.github/workflows/ci.yml`（新建）

> 注意：若 FlashGaze 仓库根目录即 `flashgaze/`，则 `.github/` 放在此处；若仓库根目录是上一层，需要相应调整路径。本模板按 `flashgaze/` 即仓库根目录编写。

**完整文件内容**：

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read

jobs:
  lint-type-test:
    name: Lint + Type + Test (Python ${{ matrix.python-version }})
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.10", "3.11", "3.12"]

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip
          cache-dependency-path: |
            pyproject.toml
            requirements-dev.txt

      - name: Install package with MCP extra
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[mcp]"
          pip install -r requirements-dev.txt

      - name: Ruff check
        run: ruff check .

      - name: Ruff format check
        run: ruff format --check .

      - name: Mypy type check
        run: mypy flashgaze

      - name: Run pytest
        run: pytest -v
```

**关键说明**：
- `fail-fast: false`：单个 Python 版本失败不取消其他矩阵任务，便于一次性看到全部问题。
- `cache: pip` + `cache-dependency-path`：缓存 pip 下载，加速后续运行。
- 安装命令严格遵循项目约束：`-e ".[mcp]"` 安装可编辑包 + MCP 可选依赖，`requirements-dev.txt` 提供 ruff/mypy/pytest。
- 参考 [astral-sh/ruff](https://github.com/astral-sh/ruff) 官方推荐：直接 `pip install ruff` 后用命令行调用，无需第三方 Action。
- `ruff format --check .` 仅检查不修改，CI 中不自动格式化（避免 PR 中产生意外 diff）。
- `mypy flashgaze` 只检查源码包，不检查 tests（见 `pyproject.toml` 中 `exclude`）。

**验证方法**：
- 本地用 [act](https://github.com/nektos/act) 模拟：`act -j lint-type-test -W .github/workflows/ci.yml`
- 或推送分支后观察 GitHub Actions 页面。
- 若无 push 权限，可在 PR 中观察 Check 状态。

---

### 3.3 更新 `requirements-dev.txt`

**文件路径**：`flashgaze/requirements-dev.txt`（修改）

**完整文件内容**：

```text
# Testing
pytest>=7.4.0
pytest-cov>=4.1.0

# Lint & format
ruff>=0.5.0

# Static type check
mypy>=1.10.0
```

**关键说明**：
- 保留原有 pytest / pytest-cov，避免破坏现有 `pytest -v` 流程。
- ruff 与 mypy 版本下限选择 2024 年稳定版本，避免引入过新规则。
- 不在此文件中重复列出 `opencv-python` 等运行时依赖，它们由 `pyproject.toml` 的 `[project.dependencies]` 管理。

**验证方法**：
```powershell
cd "h:\45001\Documents\SaiTu skill\flashgaze"
python -m pip install -r requirements-dev.txt
ruff --version
mypy --version
pytest --version
```
预期：三条 version 命令均正常输出。

---

### 3.4 将 `setup.py` 改为空壳

**文件路径**：`flashgaze/setup.py`（修改）

**完整文件内容**：

```python
from setuptools import setup

setup()
```

**关键说明**：
- 保留 `setup.py` 而非删除，因为：
  1. 部分旧版 pip（<21.3）在 `pip install -e .` 时仍会查找 `setup.py`。
  2. 某些 CI / 打包脚本显式调用 `python setup.py xxx`。
- 所有元数据已由 `pyproject.toml` 接管，`setup()` 调用不传任何参数，setuptools 会自动从 `pyproject.toml` 读取配置。
- 项目记忆中明确要求 `requirements.txt` 不列 `mcp`，同理 `setup.py` 空壳也不会重新声明 `mcp`，避免双源冲突。

**验证方法**：
```powershell
cd "h:\45001\Documents\SaiTu skill\flashgaze"
python -m pip uninstall -y flashgaze
python -m pip install -e .
flashgaze --version
python -m pip install -e ".[mcp]"
python -m flashgaze.mcp_server
```
预期：前两步安装成功，`flashgaze --version` 输出 `0.1.0`，最后一行能启动 MCP Server（按下 Ctrl+C 退出）。

---

## 4. 验证清单

执行全部实施步骤后，按顺序逐项验证：

- [ ] `python -m pip install -e ".[mcp]"` 正常安装，无错误
- [ ] `python -m pip install -r requirements-dev.txt` 正常安装，无错误
- [ ] `ruff check flashgaze/` 无错误（warning 可接受）
- [ ] `ruff format --check flashgaze/` 无需修改的文件
- [ ] `mypy flashgaze/` 退出码 0（允许 warnings，不允许 errors）
- [ ] `pytest -v` 全部 134 项通过
- [ ] `flashgaze --version` 正常输出 `0.1.0`
- [ ] `python -m flashgaze.mcp_server` 能启动并监听（手动 Ctrl+C 退出）
- [ ] `python -c "from flashgaze.core import cv_engine; print('ok')"` 导入正常
- [ ] GitHub Actions CI 在 PR 上显示绿色对勾（推送后验证）

---

## 5. 风险与回退方案

### 5.1 pyproject.toml 迁移失败

**风险**：`pip install -e .` 报元数据解析错误，或 `flashgaze` 命令找不到。

**回退**：
1. 保留原始 `setup.py` 备份（迁移前先 `Copy-Item setup.py setup.py.bak`）。
2. 删除 `pyproject.toml`，恢复 `setup.py.bak` 为 `setup.py`。
3. 重新 `pip install -e ".[mcp]"` 验证。

**预防**：迁移前在干净虚拟环境测试：
```powershell
python -m venv .venv-test
.\.venv-test\Scripts\Activate.ps1
pip install -e ".[mcp]"
flashgaze --version
```

### 5.2 ruff auto-fix 修改代码风格

**风险**：直接 `ruff check --fix .` 可能批量修改源码，引入与本次基础设施改动无关的 diff，污染 PR 评审。

**缓解**：
1. 初次运行只用 `ruff check .`（不带 `--fix`）查看问题清单。
2. 评估问题数量：若 <20 处，手动或单独 PR 修复；若 >20 处，分模块逐步 `--fix`。
3. CI 中只用 `ruff check .` 与 `ruff format --check .`，不执行自动修复。

### 5.3 mypy 报出大量类型告警

**风险**：现有源码类型注解不全，`mypy flashgaze` 可能输出几十条告警，阻塞 CI。

**缓解**：
1. 初次配置 `strict = false`（本计划已采用），只拦截真正错误。
2. 对无法立即修复的模块，可在 `pyproject.toml` 临时追加：
   ```toml
   [[tool.mypy.overrides]]
   module = ["flashgaze.core.vlm_client"]
   ignore_errors = true
   ```
3. 后续按模块逐步收紧：先去掉 `ignore_errors`，再补类型注解，最后逐步开启 `disallow_untyped_defs` 等严格选项。

### 5.4 CI 矩阵在 3.10 上失败

**风险**：某些依赖（如新版 `numpy`）在 3.10 下行为与 3.12 不同，可能导致测试失败。

**缓解**：
1. 本地用 `py -3.10 -m pytest -v` 复现。
2. 若确属依赖版本问题，在 `pyproject.toml` 中追加下限：
   ```toml
   "numpy>=1.24.0,<2.3.0; python_version<'3.11'",
   ```
3. 必要时在 CI 矩阵中临时移除 3.10，但需在 Issue 中记录技术债。

### 5.5 可编辑安装模式冲突

**风险**：`pip install -e .` 与 `pyproject.toml` 的 `[tool.setuptools.packages.find]` 配置不匹配，导致 `import flashgaze` 失败。

**缓解**：
1. 显式 `include = ["flashgaze*"]`，避免误包含 `tests/`。
2. 安装后用 `python -c "import flashgaze; print(flashgaze.__file__)"` 确认指向源码目录。
3. 若失败，回退到 `setup.py` 旧配置。

---

## 附录：实施顺序总览

| 步骤 | 操作 | 影响范围 | 可回退性 |
| --- | --- | --- | --- |
| 3.1 | 新建 `pyproject.toml` | 打包元数据源切换 | 高（保留 setup.py.bak） |
| 3.3 | 修改 `requirements-dev.txt` | 新增 ruff / mypy | 高（git revert） |
| 3.4 | 简化 `setup.py` 为空壳 | 移除旧元数据声明 | 高（git revert） |
| 3.2 | 新建 `.github/workflows/ci.yml` | 启用 CI | 高（删除文件即可） |

推荐在单独分支 `infra/pyproject-migration` 上完成全部步骤，验证通过后合并到 `main`。
