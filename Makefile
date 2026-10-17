# FlashGaze 本地代码质量守护（Makefile）
#
# 提供与 CI lint / typecheck job 等价的本地一键命令，全部复用 pyproject.toml
# 中的 [tool.ruff] / [tool.mypy] 规则与 requirements-dev.txt 的版本区间。
#
# 常用目标：
#   make install       安装 dev 依赖并启用 pre-commit 钩子
#   make lint          运行 ruff 检查（python -m ruff check .）
#   make format        自动格式化（python -m ruff format .）
#   make format-check  检查格式化是否合规（python -m ruff format --check .）
#   make typecheck     运行 mypy（python -m mypy）
#   make check         完整本地守护：lint + format-check + typecheck
#   make verify        一键完整验证：check + test（lint + format-check + typecheck + test）
#   make test          运行测试（python -m pytest tests/ -q；默认口径自动排除 e2e，见 pyproject addopts）
#   make test-all      全量测试（-o addopts= 解除默认过滤，含 e2e；无 e2e 依赖时自动跳过）
#   make hooks         对所有文件运行 pre-commit（等价于 CI 全量预检）
#   make dist          本地构建并校验发布产物（python -m build + twine check --strict）
#
# 注意：Makefile 需放在仓库根（pyproject.toml 所在目录）执行。
# Windows 下若未安装 GNU make，可直接使用等价的 `python -m ...` 命令。
# dist 目标会自行安装 build/twine：发布工具与开发工具链分离，
# 故不写入 requirements-dev.txt。

.PHONY: install lint format format-check typecheck test test-all check verify hooks dist

install:
	pip install -r requirements-dev.txt
	pre-commit install

lint:
	python -m ruff check .

format:
	python -m ruff format .

format-check:
	python -m ruff format --check .

typecheck:
	python -m mypy

check: lint format-check typecheck

verify: check test

# -o addopts= 清空 pyproject [tool.pytest.ini_options] addopts 的默认过滤
# （-m "not e2e"，M-17），使 e2e 也被收集；无 e2e 依赖时 conftest importorskip
# 会让该目录优雅跳过而非报错。
test:
	python -m pytest tests/ -q

test-all:
	python -m pytest tests/ -q -o addopts=

hooks:
	pre-commit run --all-files

dist:
	pip install build twine
	python -m build
	twine check --strict dist/*
