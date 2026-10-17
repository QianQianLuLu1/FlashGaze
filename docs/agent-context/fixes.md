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
  - 构造期失败 → `CONFIG_ERROR(6)`，评分期失败 → `IMAGE_ERROR(4)`
  - 新增 `except BrisqueIntegrityError` 分支（**必须排在 `except Exception` 之前**，它是 RuntimeError 子类）
  - `main()` 分发层新增 `except Exception` 最后防线 → `INTERNAL_ERROR(8)`
- **教训**：供应链安全信号（模型完整性校验失败）必须用专属退出码，不能被通用异常吞掉

## 4.4 M-17：裸跑 pytest 默认口径校验

- **问题**：`pyproject.toml` 的 `addopts` / `testpaths` 默认过滤可能被悄悄回退
- **修复**：CI 新增 `Bare pytest default gate (collect-only)` 步骤，验证裸跑 collect-only 输出不含 e2e/benchmarks 节点 ID
- **教训**：默认口径必须用 CI 守卫，不能依赖开发者自觉

## 4.5 H-10/H-11/H-12：MCP 删除/导出/读取面高危审查

- **H-10**：MCP cleanup 删除失败时返回成功（已修复：返回部分失败清单）
- **H-11**：MCP export 路径未做 containment 校验（已修复：relative_to 边界）
- **H-12**：MCP allowed_roots 未生效（已修复：配置层强制）
- **教训**：MCP 工具是 AI Agent 主用入口，安全护栏必须比 CLI 更严格
