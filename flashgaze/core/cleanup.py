"""工作空间清理核心：评分后安全地原地删除低分图。

抽取自 `flashgaze/mcp_server.py::cleanup_workspace_images` 的「分类 + 删除 +
安全校验」逻辑，供 CLI（run_cleanup）与 MCP（classify_and_delete）复用。
评分（make_scorer）由调用方负责：MCP 因契约测试会在 `flashgaze.mcp_server`
层 mock make_scorer，故本模块不替调用方做评分，只接收已评分的 `ImageScore` 列表。

安全护栏（不可"简化"）：
1. dry_run 默认开启：未显式 apply 绝不 unlink。
2. relative_to 边界校验：删除前 resolve 后 relative_to(ws) 必须成功，否则拦截
   （符号链接逃逸解析后指向 workspace 外，因此被拒）。
3. 删除前 stat 校验（TOCTOU）：对同一已解析路径重新 stat，非 S_ISREG
   （设备/FIFO/socket/目录）或 OSError 时拦截，绝不删除。
4. 双重解析不缓存：删除阶段重新 resolve + stat，规避检查→删除时间窗内的替换。
5. 批量删除比例护栏（FIX #sec-threshold）：实际删除模式下待删比例超过
   CLEANUP_MAX_DELETE_RATIO（0.95）且样本量达到 CLEANUP_GUARD_MIN_SAMPLE 时，
   整批拦截（一张不删）并全部计入 blocked，须调用方显式传 force=True 才放行。
   防御 threshold 越界/配置错误（如 150 → 全部不达标）一次调用删空工作空间。
6. 回收站 + 审计清单（不可逆删除防护）：实际删除绝不直接 unlink，而是同卷 rename
   到 <ws>/.flashgaze_deleted/<批>/<原相对路径>（字节完整、可按原路径恢复），
   并逐张落盘审计清单 <ws>/.flashgaze_deleted_<UTC>_<pid>.jsonl（原路径、回收站
   路径、SHA256、大小、评分）。回收站目录与清单均以 "." 开头，iter_images 不扫描，
   不会污染后续评分/清理。recycle=False（CLI --no-recycle）仍强制写审计清单。
   SHA256 与清单落盘是 best-effort：失败只告警（每批次一次）、绝不阻断删除——
   安全增强不得把原本可成功的删除变成可用性回退。
7. force 与 dry_run 清单指纹强绑定：force=True 不再是「无条件放行」。调用方必须先
   dry_run 拿到 summary.fingerprint、人工核对待删清单，再回填 confirm_fingerprint；
   缺失或与当前清单不符 → 整批拦截（一张不删，kind="confirm_required"）。
   指纹只取决于待删**路径集合**（不含分数）：VLM 抖动会改分数但不改待删路径，
   而路径增减才真正意味着「用户核对过的那份清单已经变了」。
8. 符号链接路径拦截（检查点 A0，H-4）：对 s.path 本体做 lstat 判定（is_symlink，
   不解析）。扫描层 `iter_images` 已过滤链接文件（H-4/M-16 主修复），此处专防
   scored 来自内部扫描之外的来源（预评分/测试注入）：若解析后作用于链接目标本体，
   会出现「报告/审计记的是链接、实际删的是目标」的不一致。命中计入 blocked
   （kind="symlink_path"）并跳过，绝不触碰目标本体。
9. 预评分来源可信度分级（C-09）：scored 入参的分数默认不被信任——仅复用损坏
   标记（error 占位），分数一律由评分引擎重算，删除集合不能被调用方逐图指定
   （伪造分数 + top=N 即可让「除伪造高分外全部被删」，且 _reselect 只重算
   selected 不重算 score，伪造在 summary 中不可见）。分数复用须显式传
   trust_scored=True，且传入分数须为有限值并落在 [0, 100]（任一违反整体拒绝
   执行，不静默钳制），实际口径以 summary.scored_source 三态（engine /
   caller / engine_with_caller_errors）透明标注。伪造 error 最多把图推入
   unevaluated（不删不入选、报告可见），危害收敛为「少删」。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import time
from collections.abc import Iterable
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flashgaze.core.cv_engine import BrisqueIntegrityError
from flashgaze.core.factory import make_scorer
from flashgaze.defaults import (
    CLEANUP_GUARD_MIN_SAMPLE,
    CLEANUP_MAX_DELETE_RATIO,
    CLEANUP_RECYCLE_BATCH_PREFIX,
    CLEANUP_RECYCLE_DIR_NAME,
    DEFAULT_TOP,
    DELETE_MANIFEST_PREFIX,
)
from flashgaze.models.schemas import Config, ImageScore
from flashgaze.utils.image_io import iter_images
from flashgaze.utils.logging import get_logger


class CleanupError(ValueError):
    """清理前置校验失败（调用方映射为 NO_IMAGES / code 3）。"""

    code = 3


def is_within_directory(file_path: Path, root: Path) -> bool:
    """安全检查：file_path 是否严格在 root 目录内（防止路径穿越）。"""
    try:
        file_path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def exclusion_dirs(config: Config, ws: Path) -> set[Path]:
    """返回目录扫描时应排除的目录集合（导出副本目录 + EXIF 备份目录）。

    与 `run_cleanup` / `cleanup_workspace_images` 的排除约定保持单一真源，供
    score / export / cleanup 三入口统一调用，避免把 `./精选` 副本或 `.flashgaze_backup`
    备份图重新扫描、评分并污染统计或生成重复导出文件（C-01）。

    ws 须为已 resolve 的 workspace 路径。相对 `export_dir` 解析到 ws 自身
    （导出目录本就位于 workspace 内，不受调用时的 CWD 影响）；绝对路径则按
    原值 resolve。backup 为 ws/".flashgaze_backup"（os.walk 内隐藏目录跳过已
    覆盖，但显式传入解析后的绝对路径可让 `iter_images` 的 relative_to 比对更健壮）。
    排除基于解析后的绝对路径比较，由 `iter_images` 内部 `relative_to` 完成。
    """
    export_dir = Path(config.export_dir)
    export_dir = (
        (ws / export_dir).resolve() if not export_dir.is_absolute() else export_dir.resolve()
    )
    backup_dir = (ws / ".flashgaze_backup").resolve()
    return {export_dir, backup_dir}


def pending_fingerprint(paths: Iterable[str | Path]) -> str:
    """待删清单指纹：已解析绝对路径去重排序后换行拼接，取 SHA256 前 12 位。

    只取路径集合、不含分数：VLM 抖动会改分数但不改待删路径集合，而只有路径增减
    才真正意味着「用户此前核对过的那份清单已经变了」。dry_run 与实际删除共用同一
    算法——用户从 dry_run 报告的 `summary.fingerprint` 取值，经
    `--confirm-fingerprint` 回填，形成「先核对、后放行」的强绑定。
    """
    normalized = sorted({str(Path(p).resolve()) for p in paths})
    return hashlib.sha256("\n".join(normalized).encode("utf-8")).hexdigest()[:12]


def _utc_stamp() -> str:
    """UTC 时间戳（文件名安全：Windows 路径不允许 ':'，故不用 isoformat）。"""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256_file(path: Path, chunk: int = 1 << 20) -> str | None:
    """计算文件 SHA256；读取失败返回 None（best-effort，告警由调用方负责）。"""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for block in iter(lambda: f.read(chunk), b""):
                digest.update(block)
    except OSError:
        return None
    return digest.hexdigest()


def _recycle_target(batch_dir: Path, rel: Path) -> Path:
    """回收站落点：保留原相对目录结构；同名冲突追加 .1/.2…，绝不覆盖既有副本。"""
    target = batch_dir / rel
    if not target.exists():
        return target
    i = 1
    while True:
        candidate = target.with_name(f"{target.name}.{i}")
        if not candidate.exists():
            return candidate
        i += 1


class _DeleteAudit:
    """删除审计清单（JSONL）落盘器，风格对齐 `exif_writer` 的差异撤销日志。

    每张成功删除的图一条记录：原路径、回收站路径、内容 SHA256、字节大小、评分。
    清单是事后追溯与 `restore_from_manifest` 回滚的唯一依据，但落盘本身是
    best-effort：失败只记 WARNING（每批次一次）并置 `failed`，绝不阻断删除。
    """

    def __init__(self, manifest: Path, workspace: Path) -> None:
        self.manifest = manifest
        self.workspace = workspace
        self.records: list[dict[str, Any]] = []
        self.failed = False
        self._announced = False
        self._hash_warned = False
        self._write_warned = False

    def hash_of(self, path: Path) -> str | None:
        """计算 SHA256；失败返回 None 并每批次告警一次（不阻断删除）。"""
        digest = _sha256_file(path)
        if digest is None and not self._hash_warned:
            self._hash_warned = True
            get_logger().warning("删除审计：读取 %s 计算 SHA256 失败，该条记为 null", path)
        return digest

    def add(
        self,
        *,
        original: Path,
        trash: Path | None,
        sha256: str | None,
        size: int,
        score: float,
    ) -> dict[str, Any]:
        """登记一条审计记录并追加落盘，返回该记录（供返回值复用）。"""
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "pid": os.getpid(),
            "workspace": str(self.workspace),
            "original_path": str(original),
            "trash_path": None if trash is None else str(trash),
            "sha256": sha256,
            "size": size,
            "score": score,
            "mode": "recycle" if trash is not None else "unlink",
        }
        self.records.append(record)
        self._append(record)
        return record

    def _append(self, record: dict[str, Any]) -> None:
        try:
            self.manifest.parent.mkdir(parents=True, exist_ok=True)
            with self.manifest.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as e:
            self.failed = True
            if not self._write_warned:
                self._write_warned = True
                get_logger().warning(
                    "删除审计清单写入失败（继续删除，本次无追溯记录）: %s: %s", self.manifest, e
                )
            return
        if not self._announced:
            self._announced = True
            get_logger().info("删除审计清单（原路径/回收站路径/SHA256）: %s", self.manifest)


def classify_and_delete(
    workspace: str | Path,
    scored: list[ImageScore],
    dry_run: bool = True,
    force: bool = False,
    *,
    recycle: bool = True,
    audit_manifest: Path | None = None,
    confirm_fingerprint: str | None = None,
    guard_min_sample: int = CLEANUP_GUARD_MIN_SAMPLE,
) -> dict[str, Any]:
    """对已评分结果执行分类 + 安全校验 + （可选）删除。

    不含评分与目录扫描——调用方先 iter_images + make_scorer 得到 `scored` 再传入。
    返回结构化 dict（CLI 与未来 WebUI 均可消费），不含任何 MCP/JSON 包装。

    报告路径口径（M-09）：pending_delete / deleted 每条记录同时含 `path`（调用方
    传入的原始串）与 `resolved_path`（检查点 A 解析后的真实路径，即实际删除/回收
    的对象）；blocked 每条同样含 `resolved_path`——per-file 拦截（outside_workspace /
    not_regular_file / stat_failed / delete_failure）为解析后真实路径，guard /
    confirm_required / symlink_path（检查点 A0 不解析，不作用于链接目标本体）为 None。

    分类规则（F-03）：低分且未损坏 → to_delete；高分 → selected（保留）；
    损坏图（error 非 None）→ unevaluated，既不删除也不入选，需用户手动处理；
    待删路径本身是符号链接 → blocked（kind="symlink_path"，检查点 A0，H-4），
    不解析、绝不作用于链接目标本体。

    Args:
        workspace: 工作空间根目录（删除严格限制在其内）。
        scored: 已评分结果。
        dry_run: True 时只登记不删除（默认）。
        force: 显式确认开关。为 False 且待删比例超过 CLEANUP_MAX_DELETE_RATIO
            且样本量达到 CLEANUP_GUARD_MIN_SAMPLE 时，整批拦截（一张不删）并全部
            计入 blocked；为 True 时跳过该护栏直接执行删除。dry_run 不受影响。
            比例按可评分图口径计算（分母不含 error 非 None 的损坏图，损坏图既
            不进分子也不进分母），防止损坏图稀释比例令护栏失效。
        recycle: True（默认）时把待删图同卷 rename 进 <ws>/.flashgaze_deleted/<批>/
            <原相对路径> 而非直接 unlink，字节完整可按原路径恢复；False 时直接
            unlink（无回滚点），但**仍强制写审计清单**保证至少可追溯。
        audit_manifest: 审计清单落点，None（默认）时用
            <ws>/.flashgaze_deleted_<UTC>_<pid>.jsonl。仅供测试注入与特殊部署。
        confirm_fingerprint: force=True 时必填的清单指纹，须等于本次
            `summary["fingerprint"]`（取自上一次 dry_run）。缺失或不匹配 → 整批
            拦截、一张不删。非 force 路径不校验。
        guard_min_sample: 比例护栏的最小样本量（默认 CLEANUP_GUARD_MIN_SAMPLE，口径为
            已评分图总数，含损坏图）。<1 时钳到 1——护栏不可经参数关闭，放行须走
            force + 指纹。
    """
    ws = Path(workspace).resolve()
    guard_min_sample = max(1, int(guard_min_sample))

    to_delete = [s for s in scored if not s.selected and s.error is None]
    selected = [s for s in scored if s.selected]
    # F-03：损坏图（有 error）既不删除也不入选，单独归类保证去向可追溯
    unevaluated = [s for s in scored if s.error is not None]

    deleted_list: list[dict[str, Any]] = []
    pending_list: list[dict[str, Any]] = []
    blocked_list: list[dict[str, Any]] = []
    deleted_count = 0

    # 护栏 5：批量删除比例护栏（O(1) 判定，删除循环之前执行）。触发时整批拦截，
    # 不进入 A/B/C 检查点也不 unlink，全部待删项进 blocked 并携带统一原因；
    # 调用方显式 force=True 才放行。dry_run 与小样本目录不受影响。
    # 分母用可评分图口径：损坏图（error 非 None）本就不进 to_delete，若计入分母
    # 会稀释比例（100 图含 20 损坏 + 80 低分 → 80/100=80%<95%，护栏失效，一次
    # 删空全部可评分图只剩损坏图）。全损坏时无待删项，ratio 记 0.0 不触发。
    scoreable_count = len(scored) - len(unevaluated)
    delete_ratio = (len(to_delete) / scoreable_count) if scoreable_count else 0.0
    guard_triggered = (
        not dry_run
        and not force
        and len(scored) >= guard_min_sample
        and delete_ratio > CLEANUP_MAX_DELETE_RATIO
    )
    guard_reason = ""
    if guard_triggered:
        guard_reason = (
            f"待删比例 {delete_ratio:.0%} 超过 {CLEANUP_MAX_DELETE_RATIO:.0%} 安全阈值"
            f"（{len(to_delete)}/{scoreable_count} 张可评分图，损坏图 {len(unevaluated)} 张不计入），"
            "已整批拦截未删除任何文件；确认无误后请显式传入 force=True"
        )
        get_logger().warning("清理护栏触发：%s", guard_reason)

    # 护栏 7：force 指纹强绑定（O(1) 判定，删除循环之前执行）。force=True 而指纹
    # 缺失/不匹配时整批拦截，一张不删，全部待删项进 blocked。非 force 路径不校验——
    # 未过比例护栏的常规删除无需人工指纹确认。
    fingerprint = pending_fingerprint(s.path for s in to_delete)
    confirm_required = (
        not dry_run and force and (confirm_fingerprint or "").strip().lower() != fingerprint
    )
    confirm_reason = ""
    if confirm_required:
        if confirm_fingerprint:
            confirm_reason = (
                f"清单指纹不符（传入 {confirm_fingerprint}，当前 {fingerprint}），"
                "已整批拦截未删除任何文件；请重新 dry_run 核对待删列表后回填新指纹"
            )
        else:
            confirm_reason = (
                "force=True 缺少已核对的 dry_run 清单指纹，已整批拦截未删除任何文件；"
                f"请先执行 dry_run 核对列表，再回填 --confirm-fingerprint {fingerprint}"
            )
        get_logger().warning("删除确认拦截：%s", confirm_reason)

    # 护栏 6：回收站批目录 + 审计清单。两者都在真正删除时才落盘——batch_dir 只是
    # 路径对象，目录由删除分支按需 mkdir；清单由 _DeleteAudit 首条记录时创建。
    # 因此 dry_run / 护栏拦截 / 无待删项三种情况下零副作用（不产生空目录与空清单）。
    stamp = _utc_stamp()
    batch_dir = (
        ws / CLEANUP_RECYCLE_DIR_NAME / f"{CLEANUP_RECYCLE_BATCH_PREFIX}{stamp}_{os.getpid()}"
    )
    manifest = audit_manifest or ws / f"{DELETE_MANIFEST_PREFIX}{stamp}_{os.getpid()}.jsonl"
    delete_audit = _DeleteAudit(manifest, ws)

    # 硬要求：删除前打印待删数量（仅实际删除模式需要打印；护栏拦截时不打印，
    # 避免日志与实际"一张不删"的行为矛盾）
    if not dry_run and not guard_triggered and not confirm_required:
        get_logger().warning("即将删除 %d 张低分图（位于 %s）", len(to_delete), ws)

    for s in to_delete:
        if guard_triggered:
            # kind 为结构化拦截类别（LOW-2）：调用方（CLI 退出码/MCP/WebUI）按
            # kind 程序化判定，不与 reason 文案耦合；reason 仅供人类阅读。
            blocked_list.append(
                {"path": s.path, "reason": guard_reason, "kind": "guard", "resolved_path": None}
            )
            continue

        if confirm_required:
            blocked_list.append(
                {
                    "path": s.path,
                    "reason": confirm_reason,
                    "kind": "confirm_required",
                    "resolved_path": None,
                }
            )
            continue

        # 检查点 A0（纵深防御，H-4）：对 s.path 本体做 lstat 判定（不解析）。
        # 扫描层 iter_images 已过滤链接文件，此处专防 scored 来自内部扫描之外的
        # 来源（预评分/测试注入）：若经检查点 A 解析后作用目标本体，会出现
        # 「报告/审计记的是链接、实际删的是目标」的审计不一致。dry_run 同样拦截。
        if Path(s.path).is_symlink():
            blocked_list.append(
                {
                    "path": s.path,
                    "reason": "路径是符号链接，已拦截（不作用于链接目标本体）",
                    "kind": "symlink_path",
                    "resolved_path": None,
                }
            )
            continue

        # 检查点 A：重新解析（折叠 .. 与符号链接），不缓存分类阶段的路径
        file_path = Path(s.path).resolve()

        # 检查点 B：relative_to 边界校验，符号链接逃逸在此被拒
        if not is_within_directory(file_path, ws):
            blocked_list.append(
                {
                    "path": s.path,
                    "reason": "路径在工作空间外，已拦截",
                    "kind": "outside_workspace",
                    "resolved_path": str(file_path),
                }
            )
            continue

        # 检查点 C（TOCTOU）：删除前最终校验文件类型，拒绝符号链接/设备/目录/FIFO/socket
        # 防止检查与删除之间的时间窗口内文件被替换为指向外部的链接
        try:
            st = file_path.stat()
            if not stat.S_ISREG(st.st_mode):
                blocked_list.append(
                    {
                        "path": s.path,
                        "reason": "非常规文件，已跳过",
                        "kind": "not_regular_file",
                        "resolved_path": str(file_path),
                    }
                )
                continue
        except OSError as e:
            blocked_list.append(
                {
                    "path": s.path,
                    "reason": f"stat 失败: {e}",
                    "kind": "stat_failed",
                    "resolved_path": str(file_path),
                }
            )
            continue

        if dry_run:
            pending_list.append({**asdict(s), "resolved_path": str(file_path)})
        else:
            # 删除前先算摘要（best-effort）：文件移走/删除后就再也读不到原字节
            digest = delete_audit.hash_of(file_path)
            trash: Path | None = None
            try:
                if recycle:
                    trash = _recycle_target(batch_dir, file_path.relative_to(ws))
                    trash.parent.mkdir(parents=True, exist_ok=True)
                    file_path.replace(trash)
                else:
                    file_path.unlink()
            except OSError as e:
                # 删除失败可观测：进入 blocked 并携带原因，不静默吞掉。
                # 注意：回收站移动失败绝不降级为 unlink——那会制造"以为进了回收站
                # 其实直接删了"的假安全；宁可保留原文件让用户重试。
                blocked_list.append(
                    {
                        "path": s.path,
                        "reason": f"删除失败: {e}",
                        "kind": "delete_failure",
                        "resolved_path": str(file_path),
                    }
                )
                continue
            deleted_list.append({**asdict(s), "resolved_path": str(file_path)})
            deleted_count += 1
            delete_audit.add(
                original=file_path,
                trash=trash,
                sha256=digest,
                size=st.st_size,
                score=s.score,
            )

    return {
        "summary": {
            "workspace": str(ws),
            "total": len(scored),
            "selected": len(selected),
            "to_delete": len(to_delete),
            "deleted": deleted_count if not dry_run else 0,
            "pending": len(pending_list) if dry_run else 0,
            "blocked": len(blocked_list),
            "unevaluated": len(unevaluated),
            "mode": "dry_run" if dry_run else "actual_delete",
            # 护栏拦截时为 True：表示"本次未删除任何文件，需显式 force 才可执行"
            "force_required": guard_triggered,
            # 本次待删清单指纹（force 放行凭证）与"确认不足被拦截"标记；
            # 二者与 force_required 同族：True 时本次一张未删
            "fingerprint": fingerprint,
            "confirm_required": confirm_required,
            # 不可逆删除防护：回收站开关、审计清单落点（无实际删除时为 None）、
            # 清单落盘是否失败（best-effort 补偿失败，删除本身仍已完成）
            "recycle": recycle,
            "delete_manifest": str(manifest) if delete_audit.records else None,
            "audit_failed": delete_audit.failed,
            # 评分口径：VLM 参与打分的张数 vs VLM 失败降级纯 CV 的张数。
            # 部分降级会使批内删除边界判定置信度不均一，报告中显式区分两类图。
            "vlm_applied": sum(1 for s in scored if s.vlm_applied),
            "vlm_degraded": sum(1 for s in scored if s.vlm_error),
            "elapsed_ms": 0,
        },
        "pending_delete": pending_list,  # 待删（dry_run 时填充）
        "deleted": deleted_list,  # 已删
        "delete_audit": delete_audit.records,  # 审计记录（与 deleted 一一对应）
        "blocked": blocked_list,  # 拦截（越界/非普通文件/stat失败/删除失败）
        "unevaluated": [asdict(s) for s in unevaluated],  # 损坏图
        "kept": [asdict(s) for s in selected],  # 入选（保留）
    }


def _score_or_raise(image_paths: list[str], config: Config) -> list[ImageScore]:
    """评分并透传供应链异常；通用异常包装为 RuntimeError（供调用方映射 IMAGE_ERROR）。"""
    try:
        return make_scorer(config).score_paths(image_paths)
    except BrisqueIntegrityError:
        # 供应链信号（模型哈希不符）必须响亮失败，不被包装成通用评分异常（C-04 闭环）
        raise
    except Exception as e:
        raise RuntimeError(f"评分过程异常: {e}") from e


def _validate_trusted_scores(scored: list[ImageScore]) -> None:
    """trust_scored=True 时校验入参分数：须为有限值且落在 [0, 100]（C-09）。

    任一违反整体拒绝执行——传入不可信数据不该被静默钳制（钳制会把 1e9 变成
    100，与插件分数校验 H-1 同口径），响亮失败让调用方修正来源。
    """
    for s in scored:
        if not math.isfinite(s.score) or not 0.0 <= s.score <= 100.0:
            raise ValueError(
                "trust_scored=True 收到的预评分含非法分数（须为有限值且落在 [0,100]）："
                f"path={s.path}, score={s.score}，已拒绝执行清理；"
                "请修正 scored 或移除 trust_scored"
            )


def _resolve_scored(
    images: list[str],
    scored: list[ImageScore] | None,
    config: Config,
    *,
    trust_scored: bool = False,
) -> tuple[list[ImageScore], str]:
    """合并预评分与按需重算，返回 (最终评分列表, 来源标注)。

    来源三态（回填至 summary.scored_source，透明标注，C-09）：
    - "engine"：scored 为 None，全部图由评分引擎重算。
    - "caller"：trust_scored=True 且校验通过，按 Path(s.path).resolve() 建索引
      复用入参分数（保留原 error/deduped，selected 由当前 config 的 top/threshold
      统一重算），仅对磁盘新出现的图重算。**仅限显式信任的调用方**（如同一进程内
      先前 score 步骤的原始返回值）；传入前须保证 score 为有限值且落在 [0, 100]，
      否则抛 ValueError 整体拒绝。
    - "engine_with_caller_errors"（默认 trust_scored=False）：入参分数一律丢弃、
      全量重算，仅复用损坏标记（error 非 None 的占位，与 hybrid_scorer 的损坏
      占位同构，不重解码）。防伪造预评分指定删除集合：分数只能由评分引擎产出
      （C-09）；伪造 error 最多把图推入 unevaluated（不删不入选、报告可见），
      危害收敛为「少删」。

    降级路径不调 _reselect：重算项由 score_paths 按当前 config 统一标记 selected
    （missing 即全部非损坏图，top/threshold 全局生效）；error 占位不参与排序，
    selected 恒 False。最终列表顺序均以 images 为准。
    """
    if scored is None:
        return _score_or_raise(images, config), "engine"

    if trust_scored:
        _validate_trusted_scores(scored)
        index = {Path(s.path).resolve(): s for s in scored}
        reused: list[ImageScore] = []
        missing: list[str] = []
        for img in images:
            resolved = Path(img).resolve()
            if resolved in index:
                reused.append(index[resolved])
            else:
                missing.append(img)

        final = reused if not missing else reused + _score_or_raise(missing, config)
        # 复用路径：按当前 config 的 top/threshold 对全部 valid 项（含复用项）统一重算
        # selected，消除"调参无效"陷阱，与 score_paths 行为对称（见 _reselect）。
        return _reselect(final, config), "caller"

    # 默认（C-09）：不信任入参分数，仅复用损坏标记，其余全部重算。
    get_logger().info(
        "收到预评分 %d 条（trust_scored=False）：分数已丢弃并全量重算，仅复用损坏标记；"
        "如需信任复用请显式传 trust_scored=True",
        len(scored),
    )
    corrupt = {Path(s.path).resolve(): s.error for s in scored if s.error}
    missing = [img for img in images if Path(img).resolve() not in corrupt]
    rescored = _score_or_raise(missing, config) if missing else []
    by_resolved = {Path(s.path).resolve(): s for s in rescored}
    final = []
    for img in images:
        resolved = Path(img).resolve()
        if resolved in corrupt:
            final.append(
                ImageScore(
                    file=Path(img).name,
                    path=img,
                    sharpness=0.0,
                    exposure=0.0,
                    composition=None,
                    vlm_adjustment=0.0,
                    score=0.0,
                    selected=False,
                    error=corrupt[resolved],
                )
            )
        else:
            final.append(by_resolved[resolved])
    return final, "engine_with_caller_errors"


def _reselect(
    scored: list[ImageScore],
    config: Config,
) -> list[ImageScore]:
    """复用预评分时按当前 config 的 top/threshold 统一重算 selected（覆盖复用项旧标志）。

    仅用于 scored 非 None 的复用路径；语义严格对齐 HybridScorer.score_paths 中
    _mark_selected + Deduplicator.mark_duplicates 的最终态：
    1. valid = 非 error 项（含 deduped，去重副本仍参与 top-N 名额计数，但最终被覆盖）；
    2. 按 (-score, path) 排序，保证 top-N 选最高分；
    3. threshold 优先于 top：逐项 selected = score >= threshold；否则取前 top_n 置 True；
    4. 末尾对所有 deduped=True 项强制 selected=False（去重优先级高于 top/threshold）。

    原地修改 selected，不触碰 error/deduped/score 等字段；无 scored 时不调用。
    """
    valid = [r for r in scored if not r.error]
    valid.sort(key=lambda s: (-s.score, s.path))
    if config.threshold is not None:
        for r in valid:
            r.selected = r.score >= config.threshold
    else:
        top_n = (
            max(DEFAULT_TOP, 1)
            if config.top is None or config.top < 1
            else min(config.top, len(valid))
        )
        for r in valid[:top_n]:
            r.selected = True
        for r in valid[top_n:]:
            r.selected = False
    for r in scored:
        if r.deduped:
            r.selected = False
    return scored


def run_cleanup(
    workspace: str | Path,
    config: Config,
    dry_run: bool = True,
    scored: list[ImageScore] | None = None,
    force: bool = False,
    *,
    trust_scored: bool = False,
    recycle: bool = True,
    confirm_fingerprint: str | None = None,
    guard_min_sample: int | None = None,
) -> dict[str, Any]:
    """评分并（可选地）原地删除工作空间内的低分图（CLI 便捷入口）。

    安全护栏：仅删 workspace 内、且删除前 stat 校验为普通文件的图片；
    符号链接逃逸由 relative_to 拦截；dry_run=True 时只登记不删除。
    评分逻辑复用 make_scorer(config)，与 MCP/score 命令保持一致。

    当调用方传入预评分 `scored`（如先前 score 步骤的结果）时，默认
    （trust_scored=False）**不信任入参分数**：仅复用损坏标记（error 占位不重解码），
    分数一律重算（C-09，防伪造预评分指定删除集合）；显式传 trust_scored=True
    才复用入参分数（须为有限值且落在 [0, 100]，否则 ValueError 拒绝执行）。
    实际口径回填至 result["summary"]["scored_source"]（engine / caller /
    engine_with_caller_errors）。

    Args:
        workspace: 工作空间目录。
        config: 评分与清理配置。
        dry_run: True 时只登记不删除（默认）。
        scored: 预评分结果，None 时全量重算。
        force: 透传给 classify_and_delete 的显式确认开关（跳过 95% 删除护栏）。
        trust_scored: 显式信任复用 scored 中的分数（默认 False，仅复用损坏标记）。
        recycle: 透传给 classify_and_delete，False 时直接 unlink（无回收站）。
        confirm_fingerprint: 透传给 classify_and_delete 的 dry_run 清单指纹。
        guard_min_sample: None（默认）时取 `config.cleanup_guard_min_sample`，
            由 CLI --guard-min-sample / env / 配置文件统一供给。

    Raises:
        CleanupError: 目录无效 / 无图片 / 评分为空（调用方映射为 NO_IMAGES）。
        RuntimeError: 评分过程异常（调用方映射为 IMAGE_ERROR）。
        ValueError: trust_scored=True 且 scored 含非法分数（调用方经通用异常兜底）。
    """
    ws = Path(workspace).resolve()
    if not ws.is_dir():
        raise CleanupError(f"工作空间目录不存在: {workspace}")

    # C-01：排除导出目录（./精选）与 EXIF 备份目录，避免把精选副本/备份图
    # 重新扫描、评分并误删（重复运行 cleanup 时尤其致命）。排除逻辑统一走
    # exclusion_dirs 单一真源，与 score/export 入口行为一致。
    images = list(iter_images(str(ws), exclude_dirs=exclusion_dirs(config, ws)))
    if not images:
        raise CleanupError("工作空间中无支持格式的图片")

    start = time.time()
    scored_final, scored_source = _resolve_scored(images, scored, config, trust_scored=trust_scored)
    elapsed_ms = int((time.time() - start) * 1000)

    if not scored_final:
        raise CleanupError("评分结果为空")

    result = classify_and_delete(
        ws,
        scored_final,
        dry_run=dry_run,
        force=force,
        recycle=recycle,
        confirm_fingerprint=confirm_fingerprint,
        guard_min_sample=(
            config.cleanup_guard_min_sample if guard_min_sample is None else guard_min_sample
        ),
    )
    result["summary"]["elapsed_ms"] = elapsed_ms
    result["summary"]["scored_source"] = scored_source
    return result


def restore_from_manifest(manifest: str | Path, dry_run: bool = False) -> dict[str, Any]:
    """按删除审计清单把回收站文件搬回原路径（删除—审计—恢复闭环）。

    每条记录先过安全校验再移动，任一不过即计入 failed、绝不半途而废：

    1. 清单必须存在且逐行可解析（不存在抛 CleanupError，由调用方映射参数错误）；
    2. ``original_path`` 必须落在记录声明的 ``workspace`` 内——清单被复制/篡改后
       不得把文件还原到 workspace 外（与删除检查点 B 同款防护）；
    3. 回收站副本必须落在 ``<workspace>/.flashgaze_deleted/`` 内（防清单字段被
       成对伪造后把任意文件搬去任意位置）；
    4. 原路径已被同名文件占用时拒绝恢复，绝不覆盖既有文件；
    5. ``mode="unlink"``（--no-recycle）的记录无回收站副本，如实计失败不误报。

    Args:
        manifest: 删除审计清单路径（``<ws>/.flashgaze_deleted_<UTC>_<pid>.jsonl``）。
        dry_run: True 时只报告可恢复哪些文件，不实际移动。

    Returns:
        结构化 dict：``summary``（manifest / total / restored / pending / failed /
        mode）+ ``restored``（成功或候选明细）+ ``failed``（失败明细，kind 取值
        malformed_record / outside_workspace / target_exists / missing_trash /
        restore_failure）。

    Raises:
        CleanupError: 清单文件不存在。
    """
    manifest_path = Path(manifest)
    if not manifest_path.is_file():
        raise CleanupError(f"删除审计清单不存在: {manifest}")

    restored: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    total = 0
    recycle_root_name = CLEANUP_RECYCLE_DIR_NAME

    for lineno, line in enumerate(manifest_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        total += 1
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            failed.append(
                {
                    "path": None,
                    "reason": f"清单第 {lineno} 行不是合法 JSON: {e}",
                    "kind": "malformed_record",
                }
            )
            continue
        original_raw = rec.get("original_path")
        rec_ws_raw = rec.get("workspace")
        trash_raw = rec.get("trash_path")
        if not original_raw or not rec_ws_raw:
            failed.append(
                {
                    "path": original_raw,
                    "reason": "记录缺少 original_path/workspace 字段",
                    "kind": "malformed_record",
                }
            )
            continue
        original = Path(original_raw)
        rec_ws = Path(rec_ws_raw)
        if not is_within_directory(original, rec_ws):
            failed.append(
                {
                    "path": original_raw,
                    "reason": "原路径不在记录声明的 workspace 内，拒绝恢复",
                    "kind": "outside_workspace",
                }
            )
            continue
        if original.exists():
            failed.append(
                {
                    "path": original_raw,
                    "reason": "原路径已存在同名文件，拒绝覆盖",
                    "kind": "target_exists",
                }
            )
            continue
        if not trash_raw:
            failed.append(
                {
                    "path": original_raw,
                    "reason": "该记录为直接删除（无回收站副本），无法自动恢复",
                    "kind": "missing_trash",
                }
            )
            continue
        trash = Path(trash_raw)
        if not is_within_directory(trash, rec_ws / recycle_root_name) or not trash.is_file():
            failed.append(
                {
                    "path": original_raw,
                    "reason": f"回收站副本缺失或不在 {recycle_root_name}/ 内: {trash_raw}",
                    "kind": "missing_trash",
                }
            )
            continue
        if dry_run:
            restored.append({"original_path": str(original), "trash_path": str(trash)})
            continue
        try:
            original.parent.mkdir(parents=True, exist_ok=True)
            trash.replace(original)
        except OSError as e:
            failed.append(
                {"path": original_raw, "reason": f"恢复失败: {e}", "kind": "restore_failure"}
            )
            continue
        restored.append({"original_path": str(original), "trash_path": str(trash)})

    return {
        "summary": {
            "manifest": str(manifest_path.resolve()),
            "total": total,
            "restored": 0 if dry_run else len(restored),
            "pending": len(restored) if dry_run else 0,
            "failed": len(failed),
            "mode": "dry_run" if dry_run else "actual_restore",
        },
        "restored": restored,
        "failed": failed,
    }
