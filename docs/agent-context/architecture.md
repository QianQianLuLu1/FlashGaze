# FlashGaze 关键架构决策

> 本文件从 `AGENTS.md` §2 拆分而来，承载完整的架构决策细节。
> AGENTS.md 保留摘要与导航链接。

---

## 2.1 混合评分引擎（CV + VLM）

- **CV 层**（`flashgaze/core/cv_engine.py`）：客观评分——清晰度（Laplacian 方差）+ 曝光度（直方图分析）
- **VLM 层**（`flashgaze/core/vlm_client.py`）：场景补偿——多提供商（qwen / openai / anthropic / ollama）
  - **默认接入方式**：内置 pin-IP 直连层（无厂商专属适配代码）
  - **litellm**：仅为**可选 opt-in 后端**，不是默认路径
- **混合评分器**（`flashgaze/core/hybrid_scorer.py`）：CV 基础分 + VLM 场景补偿 = 最终分
- **可解释性**：输出含 `vlm_reason` / `vlm_provider` 字段

## 2.2 可选 CV 增强维度（全部默认关闭）

| 维度 | 启用开关 | 依赖 | 实现 |
|---|---|---|---|
| 构图（实验性） | `--enable-composition` | 无（纯 CV） | `flashgaze/core/cv_engine.py::compute_composition` |
| 噪点（BRISQUE） | `--enable-noise` | `opencv-contrib-python-headless`（extras: `cv-enhanced`） | `flashgaze/core/cv_engine.py`（评分逻辑）+ `flashgaze/models/brisque/*.yml`（模型参数，见该目录 README） |
| 色彩丰富度 | `--enable-color` | 无（纯 CV） | `flashgaze/core/cv_engine.py` |
| 人像专项 | `--enable-portrait` | `face_recognition`（dlib） | `flashgaze/core/portrait_engine.py` |
| PHash 去重 | `--enable-dedup` | `imagededup` | `flashgaze/core/deduplicator.py` |

> 注意 `core/` 与 `models/brisque/` 的分工：BRISQUE **算法调用**在 `core/cv_engine.py` 内，
> `models/brisque/` 只放随包分发的模型参数文件；不存在 `flashgaze/core/brisque.py`。

## 2.3 三入口一致性

- **CLI**（`flashgaze/cli/entry.py`）：三个子命令 `flashgaze score <目录>` / `flashgaze cleanup <目录>` / `flashgaze restore <审计清单>`（`cli/parser.py::_SUBCOMMANDS`；裸 `flashgaze <目录>` 兼容为 `score`）
- **MCP Server**（`flashgaze/mcp_server.py`）：5 个工具（`score_images` / `score_single_image` / `export_selected_images` / `score_uploaded_images` / `cleanup_workspace_images`）
- **Web GUI**（`flashgaze/webui/app.py`）：Gradio 界面（约束 `gradio>=4.21,<7`，完整实测仅 6.24.0 一线）
- **配置优先级链**（三入口一致）：CLI 参数（MCP 工具参数）> 环境变量 `FLASHGAZE_CONFIG_FILE` > 配置文件 > 默认值
- **单一载体**：`flashgaze/models/options.py::ScoringOptions` 承载 26 个评分旋钮（全字段默认 `None` = 不覆盖下层配置；计数以 `dataclasses.fields(ScoringOptions)` 为准，新增旋钮须同步本数）

## 2.4 工作空间清理安全护栏

- **唯一实现**：`flashgaze/core/cleanup.py`（MCP 与 CLI 共用）
- **默认 dry-run**：绝不默认删除，显式 `--apply`（MCP `dry_run=False`）才进入删除流程
- **回收站优先，绝不裸 unlink**：实际删除先把文件**同卷 rename** 进工作空间内 `.flashgaze_deleted/` 回收站，再落盘 JSONL 审计清单 `.flashgaze_deleted_<UTC>_<pid>.jsonl`；回收站移动失败**绝不降级为直接 unlink**（`--no-recycle` 是唯一直接删除出口，且须配合 `--force`）
- **两步确认（force ↔ 指纹强绑定）**：`force=True` / `--force` 必须携带与当前待删清单**匹配的** `confirm_fingerprint`（取自 dry_run 报告 `summary.fingerprint`），缺失或不符时整批拦截、一张不删，返回 `status="blocked"` / code 1（CLI 侧 `--force` 缺 `--confirm-fingerprint` 更在**评分之前**即拒绝，不白烧 VLM 算力）
- **批量删除比例护栏**：待删数占**可评分图**（分母扣除损坏图，避免其稀释比例绕过拦截）比例 > `CLEANUP_MAX_DELETE_RATIO`（0.95）且样本 ≥ `CLEANUP_GUARD_MIN_SAMPLE`（6）时整批拦截
- **路径边界**：`relative_to` 校验 + 删除前 `stat.S_ISREG` 校验（TOCTOU 防护）+ 双重解析不缓存
- **绝不影响目录外文件**
- **可回滚**：`flashgaze restore <manifest> [--dry-run]` 按审计清单逐项移回原位（`restore_from_manifest`）
