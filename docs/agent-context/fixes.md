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
     windows-py3.10 未覆盖，其余 10 腿覆盖；
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
    问题 2 至今无法定性（失败/报错/未跑三种可能在产物里不可区分），只能交给新落地的
    junit 下一轮给答案。**证据不足时如实标注，不猜改生产代码。**
  - 依赖未钉版时，上游一次发布就能让同一次 CI 运行内出现两个测量引擎；`coverage`
    这类「只经间接依赖引入」的工具同样要显式钉。
