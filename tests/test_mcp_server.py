"""MCP Server 工具函数单元测试。

覆盖 _config_from / _filter_image_files / _is_within_directory / _error / _success
以及 5 个 MCP 工具的成功路径与错误码（3/4/6）。
验证 A-01/A-02（_config_from 委托 + env 覆盖）、U-01（六字段统一 Schema）、
C-12（cleanup TOCTOU 防护）等重构落地。
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

pytest.importorskip("mcp")

from flashgaze.mcp_server import (
    _config_from,
    _error,
    _filter_image_files,
    _is_within_directory,
    _success,
    cleanup_workspace_images,
    export_selected_images,
    score_images,
    score_single_image,
    score_uploaded_images,
)
from flashgaze.models.options import ENTRY_MCP, ScoringOptions, knobs_for
from flashgaze.models.schemas import Config

# ── H-12：允许扫描根（allowed roots）路径边界 ──────────


@pytest.fixture(autouse=True)
def _mcp_allowed_roots(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fixtures_dir: Path) -> None:
    """默认把允许扫描根放开到本用例的 tmp_path 与 fixtures 目录。

    隔离「未配置 env 时兜底 CWD」对既有用例的影响；专测兜底行为的用例
    （test_default_root_is_cwd）自行 delenv 覆盖。
    """
    monkeypatch.setenv("FLASHGAZE_MCP_ALLOWED_ROOTS", f"{tmp_path},{fixtures_dir}")


# ── _config_from（A-01/A-02）──────────────────────────


class TestBuildConfig:
    """验证 _config_from 委托 build_config，且旋钮默认 None 时 env 生效。"""

    def test_defaults_return_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """不传任何 override 时，应回落到 defaults.py 默认值。"""
        # 钉住核数，否则 DEFAULT_WORKERS=4 在 2 核 CI 上被钳制成 2，掩盖真正要验的「默认值」语义
        monkeypatch.setattr(os, "cpu_count", lambda: 16)
        cfg = _config_from("/tmp", ScoringOptions())
        assert cfg.directory == "/tmp"
        assert cfg.top == 30  # DEFAULT_TOP
        assert cfg.workers == 4  # DEFAULT_WORKERS
        assert cfg.no_vlm is False
        assert cfg.enable_composition is False

    def test_workers_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """显式传 workers 应覆盖 env 与 default。"""
        # 钉住核数，否则 workers=8 在少核机器上被钳制，掩盖真正要验的「显式参数优先」语义
        monkeypatch.setattr(os, "cpu_count", lambda: 16)
        cfg = _config_from("/tmp", ScoringOptions(workers=8))
        assert cfg.workers == 8

    def test_top_override(self) -> None:
        cfg = _config_from("/tmp", ScoringOptions(top=5))
        assert cfg.top == 5

    def test_env_workers_respected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A-02 核心：MCP 调用方不传 workers 时，FLASHGAZE_WORKERS 应生效（机器无关）。"""
        cpu_count = os.cpu_count() or 4
        cap = min(cpu_count, 16)
        # 取一个明确 ≤ cap 的值，证明 env 覆盖生效且不受钳制影响
        env_val = cap // 2 if cap >= 2 else cap
        monkeypatch.setenv("FLASHGAZE_WORKERS", str(env_val))
        cfg = _config_from("/tmp", ScoringOptions())  # workers 默认 None
        assert cfg.workers == env_val

    def test_env_workers_clamped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """env 超过 cpu 上限时，应被钳制到 min(cpu_count, 16)。"""
        cpu_count = os.cpu_count() or 4
        cap = min(cpu_count, 16)
        monkeypatch.setenv("FLASHGAZE_WORKERS", "999")
        cfg = _config_from("/tmp", ScoringOptions())  # workers 默认 None
        assert cfg.workers == cap

    def test_env_workers_overridden_by_param(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """显式参数优先级高于 env。"""
        monkeypatch.setenv("FLASHGAZE_WORKERS", "16")
        cfg = _config_from("/tmp", ScoringOptions(workers=2))
        assert cfg.workers == 2

    def test_env_api_key_respected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FLASHGAZE_API_KEY", "sk-test")
        cfg = _config_from("/tmp", ScoringOptions())
        assert cfg.api_key == "sk-test"

    def test_env_config_file_respected(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """M-11：FLASHGAZE_CONFIG_FILE 指向的配置文件在 MCP 入口同样生效。"""
        cfg_file = tmp_path / "cfg.json"
        cfg_file.write_text(json.dumps({"enable_noise": True}), encoding="utf-8")
        monkeypatch.setenv("FLASHGAZE_CONFIG_FILE", str(cfg_file))
        cfg = _config_from("/tmp", ScoringOptions())
        assert cfg.enable_noise is True


# ── _error / _success（U-01/U-03 六字段 Schema）─────────


class TestResponseSchema:
    """验证所有响应遵循六字段统一 Schema。"""

    def test_error_has_six_fields(self) -> None:
        raw = _error(3, "目录不存在")
        data = json.loads(raw)
        assert set(data.keys()) == {"status", "code", "message", "summary", "images", "details"}
        assert data["status"] == "error"
        assert data["code"] == 3
        assert data["message"] == "目录不存在"
        assert data["summary"] == {}
        assert data["images"] is None
        assert data["details"] is None

    def test_success_has_six_fields(self) -> None:
        raw = _success(summary={"total": 1}, images=[{"file": "a.jpg"}], details={"k": "v"})
        data = json.loads(raw)
        assert set(data.keys()) == {"status", "code", "message", "summary", "images", "details"}
        assert data["status"] == "success"
        assert data["code"] == 0
        assert data["message"] is None
        assert data["summary"] == {"total": 1}
        assert data["images"] == [{"file": "a.jpg"}]
        assert data["details"] == {"k": "v"}

    def test_success_minimal(self) -> None:
        raw = _success(summary={})
        data = json.loads(raw)
        assert data["images"] is None
        assert data["details"] is None


# ── _filter_image_files ────────────────────────────────


class TestFilterImageFiles:
    def test_empty_list(self) -> None:
        valid, skipped = _filter_image_files([])
        assert valid == []
        assert skipped == []

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        valid, skipped = _filter_image_files([str(tmp_path / "nope.jpg")])
        assert valid == []
        assert len(skipped) == 1
        assert "文件不存在" in skipped[0]

    def test_unsupported_format(self, tmp_path: Path) -> None:
        txt = tmp_path / "note.txt"
        txt.write_text("hello", encoding="utf-8")
        valid, skipped = _filter_image_files([str(txt)])
        assert valid == []
        assert "不支持的格式" in skipped[0]

    def test_valid_image(self, sharp_img: str) -> None:
        valid, skipped = _filter_image_files([sharp_img])
        assert len(valid) == 1
        assert skipped == []


# ── _is_within_directory ───────────────────────────────


class TestIsWithinDirectory:
    def test_file_inside(self, tmp_path: Path) -> None:
        f = tmp_path / "a.jpg"
        f.write_text("x", encoding="utf-8")
        assert _is_within_directory(f, tmp_path) is True

    def test_file_outside(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / "outside.jpg"
        try:
            outside.write_text("x", encoding="utf-8")
            assert _is_within_directory(outside, tmp_path) is False
        finally:
            if outside.exists():
                outside.unlink()

    def test_root_itself(self, tmp_path: Path) -> None:
        # 根目录本身相对自身应为 True
        assert _is_within_directory(tmp_path, tmp_path) is True


# ── score_images ───────────────────────────────────────


class TestScoreImages:
    def test_directory_not_exist(self) -> None:
        raw = score_images("/nonexistent/path/xyz")
        data = json.loads(raw)
        assert data["status"] == "error"
        assert data["code"] == 3

    def test_empty_directory(self, tmp_path: Path) -> None:
        raw = score_images(str(tmp_path))
        data = json.loads(raw)
        assert data["code"] == 3
        assert "无支持格式" in data["message"]

    def test_score_success_no_vlm(self, tmp_path: Path, sharp_img: str) -> None:
        # 复制 sharp.jpg 到测试目录
        import shutil

        dst = tmp_path / "sharp.jpg"
        shutil.copy(sharp_img, dst)
        raw = score_images(str(tmp_path), no_vlm=True)
        data = json.loads(raw)
        assert data["status"] == "success"
        assert data["code"] == 0
        assert data["summary"]["total"] == 1
        assert len(data["images"]) == 1
        # 六字段恒定
        assert "message" in data
        assert "details" in data


# ── score_single_image ─────────────────────────────────


class TestScoreSingleImage:
    def test_file_not_exist(self, tmp_path: Path) -> None:
        # H-12 后边界校验先于存在性检查：根外路径报「允许扫描根之外」(code 1)，
        # 「不存在→code 3」语义改用根内路径表达（见 TestSingleImagePathBoundary）。
        raw = score_single_image(str(tmp_path / "nope.jpg"), no_vlm=True)
        data = json.loads(raw)
        assert data["code"] == 3

    def test_unsupported_format(self, tmp_path: Path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("x", encoding="utf-8")
        raw = score_single_image(str(f), no_vlm=True)
        data = json.loads(raw)
        assert data["code"] == 3
        assert "不支持" in data["message"]

    def test_single_success(self, sharp_img: str) -> None:
        raw = score_single_image(sharp_img, no_vlm=True)
        data = json.loads(raw)
        assert data["status"] == "success"
        # U-02：单图模式 selected 恒为 0，images 为单元素数组
        assert data["summary"]["total"] == 1
        assert data["summary"]["selected"] == 0
        assert len(data["images"]) == 1


# ── export_selected_images ─────────────────────────────


class TestExportSelectedImages:
    def test_directory_not_exist(self) -> None:
        raw = export_selected_images("/nonexistent/xyz")
        data = json.loads(raw)
        assert data["code"] == 3

    def test_export_success(self, tmp_path: Path, sharp_img: str) -> None:
        import shutil

        dst = tmp_path / "src" / "sharp.jpg"
        dst.parent.mkdir()
        shutil.copy(sharp_img, dst)
        # dest_dir 须落在 workspace（directory）内，否则被 M2 路径穿越防护拒绝
        dest = tmp_path / "src" / "out"
        raw = export_selected_images(str(dst.parent), no_vlm=True, dest_dir=str(dest), top=1)
        data = json.loads(raw)
        assert data["status"] == "success"
        assert data["details"]["dest_dir"] == str(dest.resolve())
        assert data["details"]["mode"] == "copy"
        # 导出目录应有文件
        assert any(dest.iterdir())

    def test_dest_dir_outside_workspace_rejected(self, tmp_path: Path, sharp_img: str) -> None:
        """M2 路径穿越防护：dest_dir 越出 workspace 时被硬拒绝（code=1，含越界提示）。

        不进入任何评分/导出逻辑即可拦截，杜绝把选中图写到 workspace 之外的任意路径。
        """
        import shutil

        dst = tmp_path / "ws" / "sharp.jpg"
        dst.parent.mkdir()
        shutil.copy(sharp_img, dst)
        # 指向 workspace 兄弟目录（绝对路径，明确越界）
        outside = tmp_path / "escape" / "out"
        raw = export_selected_images(str(dst.parent), no_vlm=True, dest_dir=str(outside), top=1)
        data = json.loads(raw)
        assert data["status"] == "error"
        assert data["code"] == 1
        assert "之外" in data["message"]
        # 越界目录不得被创建（证明拦截生效，未落入 export_images）
        assert not outside.exists()

    def test_relative_dest_resolves_against_workspace(
        self, tmp_path: Path, sharp_img: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """N-1 契约对齐：相对 dest_dir 以 workspace 为基准解析，与服务进程 CWD 无关。

        服务进程 CWD ≠ workspace 时（MCP 常态），默认 dest_dir=./精选 此前按 CWD
        解析后被 M2 越界防护误拒；现应与 CLI 一致落到 workspace/精选。
        """
        import shutil

        dst = tmp_path / "ws" / "sharp.jpg"
        dst.parent.mkdir()
        shutil.copy(sharp_img, dst)
        monkeypatch.chdir(tmp_path)  # CWD = ws 父目录，≠ workspace
        # 不传 dest_dir，走默认相对路径 ./精选
        raw = export_selected_images(str(dst.parent), no_vlm=True, top=1)
        data = json.loads(raw)
        assert data["status"] == "success", data
        out = dst.parent / "精选"
        assert any(out.iterdir())
        assert data["details"]["dest_dir"] == str(out.resolve())
        # 不得按 CWD 落盘（证明解析基准确为 workspace）
        assert not (tmp_path / "精选").exists()

    def test_export_partial_failure_nonzero(
        self, tmp_path: Path, sharp_img: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """M-13（P0 序 24）：部分导出失败不得返回 success。

        真实走 Exporter（monkeypatch 落盘函数模拟磁盘满/权限不足），断言：
        ① status="partial" 且 code=5（与 CLI 退出码 5 同义）；② summary 暴露
        export_failed 计数；③ details.failures 给出逐项结构化明细。
        """
        dst = tmp_path / "src" / "sharp.jpg"
        dst.parent.mkdir()
        shutil.copy(sharp_img, dst)
        dest = tmp_path / "src" / "out"

        def _boom(*a: object, **k: object) -> None:
            raise OSError("disk full")  # 模拟磁盘满 / 权限不足

        monkeypatch.setattr("flashgaze.core.exporter.shutil.copy2", _boom)
        raw = export_selected_images(str(dst.parent), no_vlm=True, dest_dir=str(dest), top=1)

        data = json.loads(raw)
        assert data["status"] == "partial"
        assert data["code"] == 5
        assert data["summary"]["export_failed"] == 1
        assert data["summary"]["exported"] == 0
        failures = data["details"]["failures"]
        assert len(failures) == 1
        assert failures[0]["file"] == "sharp.jpg"
        assert "disk full" in failures[0]["error"]
        # 六字段 Schema 完整保留，Agent 仍可读统计与落点
        assert data["details"]["dest_dir"] == str(dest.resolve())
        assert data["details"]["mode"] == "copy"

    def test_export_full_success_reports_zero_failures(
        self, tmp_path: Path, sharp_img: str
    ) -> None:
        """反例（R4）：零失败时 status 仍为 success，且 summary 显式给出 export_failed=0。"""
        dst = tmp_path / "src" / "sharp.jpg"
        dst.parent.mkdir()
        shutil.copy(sharp_img, dst)
        dest = tmp_path / "src" / "out"

        raw = export_selected_images(str(dst.parent), no_vlm=True, dest_dir=str(dest), top=1)

        data = json.loads(raw)
        assert data["status"] == "success"
        assert data["code"] == 0
        assert data["summary"]["export_failed"] == 0
        assert data["summary"]["exported"] == 1
        assert (dest / "sharp.jpg").exists()

    def test_relative_dest_escape_rejected(
        self, tmp_path: Path, sharp_img: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """相对路径的 .. 逃逸同样被 M2 硬拒绝（与绝对路径越界同强度）。"""
        import shutil

        dst = tmp_path / "ws" / "sharp.jpg"
        dst.parent.mkdir()
        shutil.copy(sharp_img, dst)
        monkeypatch.chdir(dst.parent)
        raw = export_selected_images(str(dst.parent), no_vlm=True, dest_dir="../escape", top=1)
        data = json.loads(raw)
        assert data["status"] == "error"
        assert data["code"] == 1
        assert "之外" in data["message"]
        assert not (tmp_path / "escape").exists()


# ── score_uploaded_images ──────────────────────────────


class TestScoreUploadedImages:
    def test_empty_list(self) -> None:
        raw = score_uploaded_images([])
        data = json.loads(raw)
        assert data["code"] == 1

    def test_all_invalid(self) -> None:
        raw = score_uploaded_images(["/nonexistent.jpg"])
        data = json.loads(raw)
        assert data["code"] == 3

    def test_success_with_skipped(self, sharp_img: str, tmp_path: Path) -> None:
        txt = tmp_path / "x.txt"
        txt.write_text("x", encoding="utf-8")
        raw = score_uploaded_images([sharp_img, str(txt)], no_vlm=True)
        data = json.loads(raw)
        assert data["status"] == "success"
        # skipped 在 details 中
        assert "skipped" in data["details"]
        assert len(data["details"]["skipped"]) == 1

    def test_scores_exactly_the_uploaded_paths(self, sharp_img: str, tmp_path: Path) -> None:
        """跨目录上传：只评这 3 张，不漏其它目录的、也不吞同目录的诱饵图。"""
        uploads = []
        for i in range(3):
            d = tmp_path / f"upload_{i}"
            d.mkdir()
            target = d / f"img_{i}.jpg"
            shutil.copy(sharp_img, target)
            uploads.append(str(target))

        # 诱饵与首张上传图同目录，但不在 image_paths 中，绝不能被评分
        decoy = tmp_path / "upload_0" / "decoy.jpg"
        shutil.copy(sharp_img, decoy)

        raw = score_uploaded_images(uploads, no_vlm=True)
        data = json.loads(raw)

        assert data["status"] == "success"
        assert data["summary"]["total"] == 3
        scored = {Path(img["path"]).resolve() for img in data["images"]}
        assert scored == {Path(p).resolve() for p in uploads}
        assert decoy.resolve() not in scored


# ── H-12：上传评分 / 单图评分的允许扫描根边界 ──────────


class TestUploadPathBoundary:
    def test_upload_rejects_outside_workspace(self, sharp_img: str, tmp_path: Path) -> None:
        """H-12 核心回归：允许根外的图片被拒，拒绝原因出现在 details.skipped。"""
        outside = tmp_path.parent / "h12_outside.jpg"
        try:
            shutil.copy(sharp_img, outside)
            raw = score_uploaded_images([sharp_img, str(outside)], no_vlm=True)
            data = json.loads(raw)
            assert data["status"] == "success"
            skipped = data["details"]["skipped"]
            assert len(skipped) == 1
            assert "位于允许扫描根之外" in skipped[0]
            assert str(outside) in skipped[0]
            # 根内图片不受牵连，正常评分
            assert data["summary"]["total"] == 1
        finally:
            if outside.exists():
                outside.unlink()

    def test_upload_all_outside_rejected(self, sharp_img: str, tmp_path: Path) -> None:
        """全部越界时收敛为 code 3，消息附当前允许根与配置指引。"""
        outside = tmp_path.parent / "h12_outside_all.jpg"
        try:
            shutil.copy(sharp_img, outside)
            raw = score_uploaded_images([str(outside)], no_vlm=True)
            data = json.loads(raw)
            assert data["status"] == "error"
            assert data["code"] == 3
            assert "位于允许扫描根之外" in data["message"]
            assert "FLASHGAZE_MCP_ALLOWED_ROOTS" in data["message"]
        finally:
            if outside.exists():
                outside.unlink()

    def test_upload_inside_roots_not_flagged(self, sharp_img: str, tmp_path: Path) -> None:
        """反例：允许根内的图片不得被误拒，skipped 为空。"""
        inside = tmp_path / "h12_inside.jpg"
        shutil.copy(sharp_img, inside)
        raw = score_uploaded_images([str(inside)], no_vlm=True)
        data = json.loads(raw)
        assert data["status"] == "success"
        assert data["details"]["skipped"] == []
        assert data["summary"]["total"] == 1

    def test_default_root_is_cwd(
        self, sharp_img: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """未配置 env 时兜底允许根 = 进程启动目录（CWD）。"""
        monkeypatch.delenv("FLASHGAZE_MCP_ALLOWED_ROOTS")
        monkeypatch.chdir(tmp_path)
        inside = tmp_path / "h12_cwd_inside.jpg"
        shutil.copy(sharp_img, inside)
        raw = score_uploaded_images([str(inside)], no_vlm=True)
        assert json.loads(raw)["status"] == "success"

        outside = tmp_path.parent / "h12_cwd_outside.jpg"
        try:
            shutil.copy(sharp_img, outside)
            raw = score_uploaded_images([str(outside)], no_vlm=True)
            data = json.loads(raw)
            assert data["status"] == "error"
            assert data["code"] == 3
            assert "位于允许扫描根之外" in data["message"]
        finally:
            if outside.exists():
                outside.unlink()

    def test_allowed_roots_env_parsing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """env 解析：逗号分隔、忽略空白项、去重；未配置或全空白回退 CWD。"""
        import flashgaze.mcp_server as mcp_mod

        root_a = tmp_path / "a"
        root_b = tmp_path / "b"
        monkeypatch.setenv("FLASHGAZE_MCP_ALLOWED_ROOTS", f" {root_a} ,,{root_b} ,{root_a}")
        assert mcp_mod._allowed_scan_roots() == [root_a.resolve(), root_b.resolve()]

        monkeypatch.setenv("FLASHGAZE_MCP_ALLOWED_ROOTS", "  , ,")
        assert mcp_mod._allowed_scan_roots() == [Path.cwd()]

        monkeypatch.delenv("FLASHGAZE_MCP_ALLOWED_ROOTS")
        assert mcp_mod._allowed_scan_roots() == [Path.cwd()]


class TestSingleImagePathBoundary:
    def test_single_image_rejects_outside_workspace(self, sharp_img: str, tmp_path: Path) -> None:
        """H-12 核心回归：允许根外的图片被拒（code 1），消息含边界说明与配置指引。"""
        outside = tmp_path.parent / "h12_single_outside.jpg"
        try:
            shutil.copy(sharp_img, outside)
            raw = score_single_image(str(outside), no_vlm=True)
            data = json.loads(raw)
            assert data["status"] == "error"
            assert data["code"] == 1
            assert "允许扫描根" in data["message"]
            assert "FLASHGAZE_MCP_ALLOWED_ROOTS" in data["message"]
        finally:
            if outside.exists():
                outside.unlink()

    def test_inside_root_nonexistent_still_code3(self, tmp_path: Path) -> None:
        """边界先于存在性检查，但根内不存在的文件仍报 code 3 文件不存在。"""
        raw = score_single_image(str(tmp_path / "h12_nope.jpg"), no_vlm=True)
        data = json.loads(raw)
        assert data["code"] == 3
        assert "文件不存在" in data["message"]


# ── cleanup_workspace_images（C-12 TOCTOU 防护）────────


class TestCleanupWorkspace:
    def test_workspace_not_exist(self) -> None:
        raw = cleanup_workspace_images("/nonexistent/ws")
        data = json.loads(raw)
        assert data["code"] == 3

    def test_dry_run_default(self, tmp_path: Path, sharp_img: str) -> None:
        """dry_run 默认 True，不实际删除。"""
        import shutil

        f = tmp_path / "sharp.jpg"
        shutil.copy(sharp_img, f)
        raw = cleanup_workspace_images(str(tmp_path), no_vlm=True, top=1)
        data = json.loads(raw)
        assert data["status"] == "success"
        assert data["summary"]["mode"] == "dry_run"
        # dry_run 模式文件仍在
        assert f.exists()

    def test_actual_delete(self, tmp_path: Path, sharp_img: str) -> None:
        """dry_run=False 时实际删除低分图。"""
        import shutil

        f = tmp_path / "sharp.jpg"
        shutil.copy(sharp_img, f)
        raw = cleanup_workspace_images(str(tmp_path), no_vlm=True, top=1, dry_run=False)
        data = json.loads(raw)
        assert data["status"] == "success"
        assert data["summary"]["mode"] == "actual_delete"

    def test_top_below_one_rejected(self, tmp_path: Path, sharp_img: str) -> None:
        """下界守卫：top=0 / -1 必须被拒绝（防清空工作空间），返回 error code 1。"""
        import shutil

        f = tmp_path / "sharp.jpg"
        shutil.copy(sharp_img, f)
        for bad_top in (0, -1):
            raw = cleanup_workspace_images(str(tmp_path), no_vlm=True, top=bad_top)
            data = json.loads(raw)
            assert data["status"] == "error"
            assert data["code"] == 1
            assert "top" in data["message"]
        # 守卫拦截后绝不应触碰任何文件
        assert f.exists()

    def test_blocked_outside_file(
        self, tmp_path: Path, sharp_img: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TOCTOU 防护：文件被移到工作空间外应被拦截。"""
        import shutil

        f = tmp_path / "sharp.jpg"
        shutil.copy(sharp_img, f)
        # mock score_paths 返回一个 path 指向工作空间外的结果
        from flashgaze.models.schemas import ImageScore

        outside_score = ImageScore(
            file="outside.jpg",
            path=str(tmp_path.parent / "outside.jpg"),
            sharpness=0.0,
            exposure=0.0,
            composition=None,
            vlm_adjustment=0.0,
            score=0.0,
        )
        with mock.patch("flashgaze.core.cleanup.make_scorer") as ms:
            scorer = ms.return_value
            scorer.score_paths.return_value = [outside_score]
            raw = cleanup_workspace_images(str(tmp_path), no_vlm=True, top=1, dry_run=False)
        data = json.loads(raw)
        # 工作空间外的文件应被拦截
        assert len(data["details"]["blocked_files"]) >= 1

    def test_deduped_low_score_copy_included_in_delete(
        self, tmp_path: Path, sharp_img: str
    ) -> None:
        """清理语义修正后：去重低分副本（deduped=True 且 selected=False）一并进入待删列表，
        不再被 deduped 标记豁免；普通落选图（deduped=False 且 selected=False）同样删除。
        仅 selected=True 的高分图受保护。
        """
        import shutil

        from flashgaze.models.schemas import ImageScore

        dup_file = tmp_path / "dup.jpg"
        low_file = tmp_path / "low.jpg"
        shutil.copy(sharp_img, dup_file)
        shutil.copy(sharp_img, low_file)

        deduped_score = ImageScore(
            file="dup.jpg",
            path=str(dup_file),
            sharpness=0.0,
            exposure=0.0,
            composition=None,
            vlm_adjustment=0.0,
            score=10.0,
            selected=False,
            deduped=True,  # 去重低分副本，现一并删除
        )
        normal_score = ImageScore(
            file="low.jpg",
            path=str(low_file),
            sharpness=0.0,
            exposure=0.0,
            composition=None,
            vlm_adjustment=0.0,
            score=5.0,
            selected=False,
            deduped=False,  # 普通落选图，删除
        )

        with mock.patch("flashgaze.core.cleanup.make_scorer") as ms:
            scorer = ms.return_value
            scorer.score_paths.return_value = [deduped_score, normal_score]
            raw = cleanup_workspace_images(str(tmp_path), no_vlm=True, top=1, dry_run=True)
        data = json.loads(raw)
        assert data["status"] == "success"

        # to_delete 现在同时包含去重副本与普通落选图
        assert data["summary"]["to_delete"] == 2
        deleted_names = data["details"]["deleted_files"]
        assert "dup.jpg" in deleted_names
        assert "low.jpg" in deleted_names

    def test_deduped_low_score_copy_actually_deleted(self, tmp_path: Path, sharp_img: str) -> None:
        """P5 强化版（dry_run=False 实际删除模式）：去重低分副本（deduped=True 且
        selected=False）必须被实际物理删除（不仅出现在报告里），普通落选图同理。

        与上方 test_deduped_low_score_copy_included_in_delete（仅 dry_run 报告层）互补：
        此处真正执行 unlink，捕获「报告正确但删除循环漏删去重图」这类回归。
        """
        import shutil

        from flashgaze.models.schemas import ImageScore

        dup_file = tmp_path / "dup.jpg"
        low_file = tmp_path / "low.jpg"
        shutil.copy(sharp_img, dup_file)
        shutil.copy(sharp_img, low_file)

        deduped_score = ImageScore(
            file="dup.jpg",
            path=str(dup_file),
            sharpness=0.0,
            exposure=0.0,
            composition=None,
            vlm_adjustment=0.0,
            score=10.0,
            selected=False,
            deduped=True,  # 去重低分副本，现一并物理删除
        )
        normal_score = ImageScore(
            file="low.jpg",
            path=str(low_file),
            sharpness=0.0,
            exposure=0.0,
            composition=None,
            vlm_adjustment=0.0,
            score=5.0,
            selected=False,
            deduped=False,  # 普通落选图，删除
        )

        with mock.patch("flashgaze.core.cleanup.make_scorer") as ms:
            ms.return_value.score_paths.return_value = [deduped_score, normal_score]
            raw = cleanup_workspace_images(str(tmp_path), no_vlm=True, top=1, dry_run=False)
        data = json.loads(raw)
        assert data["status"] == "success"
        assert data["summary"]["mode"] == "actual_delete"

        # 报告层面：to_delete 同时含去重副本与普通落选图
        assert data["summary"]["to_delete"] == 2
        deleted_names = data["details"]["deleted_files"]
        assert "dup.jpg" in deleted_names
        assert "low.jpg" in deleted_names
        assert data["summary"]["deleted"] == 2

        # 磁盘层面（关键增强）：去重低分副本与普通落选图均已被物理删除
        assert not dup_file.exists(), "去重低分副本应被实际删除"
        assert not low_file.exists(), "普通落选图应被物理删除"

    def test_dedup_group_keeps_highest_score_only(self, tmp_path: Path, sharp_img: str) -> None:
        """去重组：组内最高分（representative，deduped=False，selected=True）保留，
        其余低分副本（deduped=True，selected=False）删除——即「仅保留每组最高分」。
        """
        import shutil

        from flashgaze.models.schemas import ImageScore

        best_file = tmp_path / "best.jpg"
        dup_file = tmp_path / "dup.jpg"
        shutil.copy(sharp_img, best_file)
        shutil.copy(sharp_img, dup_file)

        best_score = ImageScore(
            file="best.jpg",
            path=str(best_file),
            sharpness=0.0,
            exposure=0.0,
            composition=None,
            vlm_adjustment=0.0,
            score=90.0,
            selected=True,
            deduped=False,  # 组内最高分，且入选
        )
        dup_score = ImageScore(
            file="dup.jpg",
            path=str(dup_file),
            sharpness=0.0,
            exposure=0.0,
            composition=None,
            vlm_adjustment=0.0,
            score=10.0,
            selected=False,
            deduped=True,  # 低分副本
        )

        with mock.patch("flashgaze.core.cleanup.make_scorer") as ms:
            ms.return_value.score_paths.return_value = [best_score, dup_score]
            raw = cleanup_workspace_images(str(tmp_path), no_vlm=True, top=1, dry_run=False)
        data = json.loads(raw)
        assert data["status"] == "success"
        assert data["summary"]["to_delete"] == 1
        assert "best.jpg" not in data["details"]["deleted_files"]
        assert "dup.jpg" in data["details"]["deleted_files"]
        assert best_file.exists(), "组内最高分应保留"
        assert not dup_file.exists(), "低分副本应删除"

    def test_unevaluated_files_tracked(
        self, tmp_path: Path, sharp_img: str, corrupted_img: str
    ) -> None:
        """F-03：损坏图（有 error）归入 unevaluated_files，既不删除也不入选。"""
        import shutil

        good = tmp_path / "sharp.jpg"
        bad = tmp_path / "corrupted.jpg"
        shutil.copy(sharp_img, good)
        shutil.copy(corrupted_img, bad)
        raw = cleanup_workspace_images(str(tmp_path), no_vlm=True, top=1)
        data = json.loads(raw)
        assert data["status"] == "success"
        # 损坏图应出现在 unevaluated_files，不出现在 deleted_files
        assert data["summary"]["unevaluated"] >= 1
        unevaluated_names = [s["file"] for s in data["details"]["unevaluated_files"]]
        assert "corrupted.jpg" in unevaluated_names
        deleted_names = data["details"]["deleted_files"]
        assert "corrupted.jpg" not in deleted_names


# ── score_images / score_uploaded_images 的 no_downscale 透传（P1-no_downscale-mcp）──


class TestNoDownscalePassthrough:
    """验证 MCP 工具参数 → ScoringOptions → Config.no_downscale 链路（验收标准 2/3）。"""

    def test_score_images_true_disables_downscale(self, tmp_path: Path, sharp_img: str) -> None:
        """传 no_downscale=True 应透传到 Config.no_downscale == True。"""
        import shutil

        dst = tmp_path / "sharp.jpg"
        shutil.copy(sharp_img, dst)
        with mock.patch("flashgaze.mcp_server.make_scorer") as ms:
            captured: dict[str, Any] = {}

            def _spy(config: Config) -> Any:
                captured["config"] = config
                scorer = ms.return_value
                scorer.score_paths.return_value = []
                return scorer

            ms.side_effect = _spy
            score_images(str(tmp_path), no_vlm=True, no_downscale=True)
        assert captured["config"].no_downscale is True

    def test_score_images_default_false(self, tmp_path: Path, sharp_img: str) -> None:
        """不传 no_downscale 应与现行为一致：Config.no_downscale == False。"""
        import shutil

        dst = tmp_path / "sharp.jpg"
        shutil.copy(sharp_img, dst)
        with mock.patch("flashgaze.mcp_server.make_scorer") as ms:
            captured: dict[str, Any] = {}

            def _spy(config: Config) -> Any:
                captured["config"] = config
                scorer = ms.return_value
                scorer.score_paths.return_value = []
                return scorer

            ms.side_effect = _spy
            score_images(str(tmp_path), no_vlm=True)
        assert captured["config"].no_downscale is False

    def test_score_uploaded_images_true_disables_downscale(self, sharp_img: str) -> None:
        """传 no_downscale=True 应透传到 Config.no_downscale == True。"""
        with mock.patch("flashgaze.mcp_server.make_scorer") as ms:
            captured = {}
            ms.side_effect = lambda config: captured.update({"config": config}) or ms.return_value
            ms.return_value.score_paths.return_value = []
            score_uploaded_images([sharp_img], no_vlm=True, no_downscale=True)
        assert captured["config"].no_downscale is True

    def test_score_uploaded_images_default_false(self, sharp_img: str) -> None:
        """不传 no_downscale 应与现行为一致：Config.no_downscale == False。"""
        with mock.patch("flashgaze.mcp_server.make_scorer") as ms:
            captured = {}
            ms.side_effect = lambda config: captured.update({"config": config}) or ms.return_value
            ms.return_value.score_paths.return_value = []
            score_uploaded_images([sharp_img], no_vlm=True)
        assert captured["config"].no_downscale is False


class TestNoDownscaleEntryDeclared:
    """验证 options.py 单一事实来源：no_downscale 已声明暴露给 MCP（验收标准 5）。"""

    def test_mcp_declares_no_downscale(self) -> None:
        assert "no_downscale" in knobs_for(ENTRY_MCP)


class TestNoDownscaleSignature:
    """验证新参数位于签名末尾且默认 False（验收标准 4）。"""

    def test_param_at_signature_end_with_false_default(self) -> None:
        import inspect

        sig_images = inspect.signature(score_images)
        assert sig_images.parameters["no_downscale"].default is False
        names = list(sig_images.parameters)
        assert names.index("no_downscale") > names.index("scene")

        sig_upload = inspect.signature(score_uploaded_images)
        assert sig_upload.parameters["no_downscale"].default is False
        names_u = list(sig_upload.parameters)
        assert names_u.index("no_downscale") > names_u.index("scene")


class TestAllMcpToolsExposeMcpKnobs:
    """遍历所有 @mcp.tool 注册的函数，断言其签名包含该工具应暴露的全部 MCP 旋钮。

    防回归核心：旧测试以点名方式逐个校验 score_images / score_uploaded_images，
    留下 score_single_image 漏接旋钮的盲区（计划 §1.3）。本测试从注册表取全部工具，
    今后任一 MCP 工具漏接 knobs_for(ENTRY_MCP) 中任意旋钮都会立即变红。
    """

    def test_all_tools_expose_expected_knobs(self) -> None:
        import inspect

        from flashgaze.mcp_server import mcp

        MCP_KNOBS = knobs_for(ENTRY_MCP)  # 13 个应在 MCP 暴露的旋钮
        # 单图模式按设计故意不含 top / threshold / workers / dedup（score_single_image 注释明确）；
        # F-02：export / cleanup 现与 score 一致暴露 no_downscale，闭合计划 §5 已知缺口，
        # 故二者契约放宽到完整 MCP_KNOBS（不再减去 no_downscale）。
        EXPECTED_PER_TOOL = {
            "score_images": MCP_KNOBS,
            "score_single_image": MCP_KNOBS - {"top", "threshold", "workers", "dedup"},
            "score_uploaded_images": MCP_KNOBS,
            "export_selected_images": MCP_KNOBS,
            "cleanup_workspace_images": MCP_KNOBS,
        }

        # 优先从 MCP 注册表取工具，保证「新增 @mcp.tool 自动进入契约校验」；
        # 注册表 API 异常时退化为显式 import 的五个工具函数。
        try:
            tools = {t.name: t.fn for t in mcp._tool_manager.list_tools()}
        except Exception:  # noqa: BLE001 — 新版模块缺失时回退旧版导入的兜底
            from flashgaze.mcp_server import (
                cleanup_workspace_images,
                export_selected_images,
                score_images,
                score_single_image,
                score_uploaded_images,
            )

            tools = {
                "score_images": score_images,
                "score_single_image": score_single_image,
                "score_uploaded_images": score_uploaded_images,
                "export_selected_images": export_selected_images,
                "cleanup_workspace_images": cleanup_workspace_images,
            }

        assert tools, "未能从注册表或导入获取任何 MCP 工具"

        for name, fn in tools.items():
            expected = EXPECTED_PER_TOOL.get(name, MCP_KNOBS)
            params = set(inspect.signature(fn).parameters)
            missing = expected - params
            assert not missing, f"工具 {name} 的签名缺少应暴露的 MCP 旋钮: {sorted(missing)}"

    def test_score_single_image_exposes_no_downscale(self) -> None:
        """精准捕获本次修复：score_single_image 必须含 no_downscale 旋钮（契约为真后变绿）。"""
        import inspect

        params = set(inspect.signature(score_single_image).parameters)
        assert "no_downscale" in params


# ── MCP 层：threshold 钳制 + 95% 删除护栏（FIX #sec-threshold）────────


def test_cleanup_workspace_threshold_over_100_clamped_and_guard_blocks(
    tmp_path: Path, sharp_img: str
) -> None:
    """threshold=150 → 钳到 100 → 全部落选 → 护栏整批拦截，一张不删；force 才放行。

    M-11：护栏拦截时 MCP 返回 **非 0 错误码 + status="blocked"**（此前是
    status="success" + code 0，Agent 会误判为「已按要求删除」）。
    """
    from flashgaze.models.schemas import ExitCode, ImageScore

    paths: list[Path] = []
    for i in range(25):
        f = tmp_path / f"img{i:02d}.jpg"
        shutil.copy(sharp_img, f)
        paths.append(f)

    def _scores() -> list[ImageScore]:
        return [
            ImageScore(
                file=p.name,
                path=str(p),
                sharpness=1.0,
                exposure=1.0,
                composition=None,
                vlm_adjustment=0.0,
                score=1.0,  # 远低于钳制后的阈值 100
            )
            for p in paths
        ]

    with mock.patch("flashgaze.core.cleanup.make_scorer") as ms:
        ms.return_value.score_paths.return_value = _scores()
        raw = cleanup_workspace_images(str(tmp_path), no_vlm=True, threshold=150, dry_run=False)
    data = json.loads(raw)
    assert data["status"] == "blocked"
    assert data["code"] == int(ExitCode.PARAM_ERROR)
    assert "force=True" in data["message"]
    assert data["summary"]["deleted"] == 0
    assert data["summary"]["force_required"] is True
    assert len(data["details"]["blocked_files"]) == 25
    assert len(data["details"]["deleted_files"]) == 0
    assert all(p.exists() for p in paths)  # 磁盘完好

    # force=True + 已核对的清单指纹 → 显式放行
    fingerprint = data["summary"]["fingerprint"]
    assert len(fingerprint) == 12
    with mock.patch("flashgaze.core.cleanup.make_scorer") as ms:
        ms.return_value.score_paths.return_value = _scores()
        raw2 = cleanup_workspace_images(
            str(tmp_path),
            no_vlm=True,
            threshold=150,
            dry_run=False,
            force=True,
            confirm_fingerprint=fingerprint,
        )
    data2 = json.loads(raw2)
    assert data2["status"] == "success"  # 显式放行后回归成功语义
    assert data2["code"] == 0
    assert data2["summary"]["deleted"] == 25
    assert data2["summary"]["force_required"] is False
    assert data2["summary"]["confirm_required"] is False
    # 删除进回收站而非 unlink：字节仍可恢复
    assert len(list((tmp_path / ".flashgaze_deleted").rglob("*.jpg"))) == 25


def test_cleanup_workspace_force_without_fingerprint_blocked(tmp_path: Path) -> None:
    """MCP：force=True 缺 confirm_fingerprint → status=blocked + code=1，一张不删。

    Agent 侧同样受「先 dry_run 核对、后 force 放行」约束，不能一步强删。
    """
    from flashgaze.models.schemas import ExitCode

    scores = _low_score_batch(tmp_path)
    with mock.patch("flashgaze.core.cleanup.make_scorer") as ms:
        ms.return_value.score_paths.return_value = scores
        raw = cleanup_workspace_images(str(tmp_path), no_vlm=True, top=1, dry_run=False, force=True)
    data = json.loads(raw)
    assert data["status"] == "blocked"
    assert data["code"] == int(ExitCode.PARAM_ERROR)
    assert data["summary"]["confirm_required"] is True
    assert data["summary"]["deleted"] == 0
    assert len(data["details"]["blocked_files"]) == 25
    assert len(data["details"]["deleted_files"]) == 0
    assert all(p.exists() for p in tmp_path.glob("img*.jpg"))  # 磁盘完好


def test_cleanup_workspace_recycle_default_true() -> None:
    """对外契约：cleanup_workspace_images 暴露 recycle 形参且默认 True（回收站开启）。"""
    import inspect

    sig = inspect.signature(cleanup_workspace_images)
    assert sig.parameters["recycle"].default is True
    assert sig.parameters["confirm_fingerprint"].default is None


def _low_score_batch(ws: Path, n: int = 25) -> list[Any]:
    """构造 n 个占位图片 + 全部低分（score=1.0）的 ImageScore 列表（评分被 mock）。"""
    from flashgaze.models.schemas import ImageScore

    paths: list[Path] = []
    for i in range(n):
        f = ws / f"img{i:02d}.jpg"
        f.write_bytes(b"fake")
        paths.append(f)
    return [
        ImageScore(
            file=p.name,
            path=str(p),
            sharpness=1.0,
            exposure=1.0,
            composition=None,
            vlm_adjustment=0.0,
            score=1.0,
        )
        for p in paths
    ]


def test_cleanup_guard_blocked_response_keeps_six_fields(tmp_path: Path) -> None:
    """M-11：blocked 响应仍是六字段 Schema，summary/details 完整可读（不丢诊断信息）。"""
    scores = _low_score_batch(tmp_path)
    with mock.patch("flashgaze.core.cleanup.make_scorer") as ms:
        ms.return_value.score_paths.return_value = scores
        raw = cleanup_workspace_images(str(tmp_path), no_vlm=True, top=1, dry_run=False)
    data = json.loads(raw)
    assert set(data.keys()) == _SIX_FIELDS
    assert data["status"] == "blocked"
    assert data["code"] != 0
    assert data["summary"]["total"] == 25
    assert data["summary"]["to_delete"] == 25  # 评分被 mock，全部未入选
    assert data["summary"]["force_required"] is True
    assert len(data["details"]["blocked_files"]) == 25
    assert len(data["details"]["deleted_files"]) == 0


def test_cleanup_guard_does_not_fire_in_dry_run(tmp_path: Path) -> None:
    """M-11：护栏只在「实际删除」时触发，dry_run 仍返回 success（报告语义不变）。"""
    scores = _low_score_batch(tmp_path)
    with mock.patch("flashgaze.core.cleanup.make_scorer") as ms:
        ms.return_value.score_paths.return_value = scores
        raw = cleanup_workspace_images(str(tmp_path), no_vlm=True, top=1)
    data = json.loads(raw)
    assert data["status"] == "success"
    assert data["code"] == 0
    assert data["summary"]["force_required"] is False
    assert data["summary"]["pending"] == 25  # 评分被 mock，全部未入选


def test_cleanup_workspace_images_exposes_force_knob() -> None:
    """对外契约：cleanup_workspace_images 暴露 force 形参且默认值 False。"""
    import inspect

    sig = inspect.signature(cleanup_workspace_images)
    assert "force" in sig.parameters
    assert sig.parameters["force"].default is False


# ── 配置装配不向框架裸抛 + int(inf) 不崩（FIX #3-6）────────

_SIX_FIELDS = {"status", "code", "message", "summary", "images", "details"}


def test_score_images_top_infinity_returns_json_not_raise(tmp_path: Path) -> None:
    """top=float('inf')（JSON 1e999）曾使 int(inf) 抛 OverflowError 击穿装配；
    现在逐层收敛：config 装配回退默认，工具层返回标准六字段错误 JSON。"""
    raw = score_images(str(tmp_path), top=float("inf"))
    data = json.loads(raw)
    assert set(data.keys()) == _SIX_FIELDS
    assert data["status"] == "error"
    assert data["code"] == 3  # 空目录 → 无图片；关键是装配未崩


def test_cleanup_workspace_top_infinity_returns_json_not_raise(tmp_path: Path) -> None:
    """同 #3-6：cleanup 的 top=inf 同样收敛为六字段错误 JSON（空工作空间 code 3）。"""
    raw = cleanup_workspace_images(str(tmp_path), top=float("inf"))
    data = json.loads(raw)
    assert set(data.keys()) == _SIX_FIELDS
    assert data["status"] == "error"
    assert data["code"] == 3


def test_score_images_config_assembly_failure_returns_six_field_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#3-6：配置装配异常不再裸抛给 FastMCP，收敛为 code 1 的六字段错误 JSON。"""
    import flashgaze.mcp_server as mcp_mod

    def _boom(directory: str, opts: ScoringOptions) -> Config:
        raise RuntimeError("装配炸了")

    monkeypatch.setattr(mcp_mod, "_config_from", _boom)
    raw = score_images(str(tmp_path))
    data = json.loads(raw)
    assert set(data.keys()) == _SIX_FIELDS
    assert data["status"] == "error"
    assert data["code"] == 1
    assert "配置装配失败" in data["message"]


def test_score_uploaded_images_config_assembly_failure_returns_six_field_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#3-6：上传模式同样受配置装配兜底保护（配置装配先于 _validate_vlm）。"""
    import flashgaze.mcp_server as mcp_mod

    img = tmp_path / "a.jpg"
    img.write_bytes(b"not-a-real-image")  # _filter_image_files 仅查扩展名，无需真图

    def _boom(directory: str, opts: ScoringOptions) -> Config:
        raise RuntimeError("装配炸了")

    monkeypatch.setattr(mcp_mod, "_config_from", _boom)
    raw = score_uploaded_images([str(img)])
    data = json.loads(raw)
    assert set(data.keys()) == _SIX_FIELDS
    assert data["status"] == "error"
    assert data["code"] == 1
    assert "配置装配失败" in data["message"]


# ── H-10：MCP 清理「删除失败」不再谎报 success ───────────


def _occupied_ws(ws: Path, sharp_img: str, n: int = 3) -> list[Path]:
    """在 ws 内铺 n 张真实图片（评分由 make_scorer 桩接管，文件本体走真实删除链路）。"""
    paths: list[Path] = []
    for i in range(n):
        f = ws / f"pic{i:02d}.jpg"
        shutil.copy(sharp_img, f)
        paths.append(f)
    return paths


def _scores_for(paths: list[Path], scores: list[float], keep: int = 1) -> list[Any]:
    """按 (路径, 分数) 逐项构造 ImageScore，前 keep 张标 selected=True。

    scored=None 时 MCP 走 `_score_or_raise`、不经 `_reselect`，selected 由评分器（此处
    为桩）决定，而 ImageScore.selected 默认 False——不显式标注会让 top 参数失效、
    全批落选（三张全进待删）。
    """
    from flashgaze.models.schemas import ImageScore

    return [
        ImageScore(
            file=p.name,
            path=str(p),
            sharpness=1.0,
            exposure=1.0,
            composition=None,
            vlm_adjustment=0.0,
            score=s,
            selected=i < keep,
        )
        for i, (p, s) in enumerate(zip(paths, scores))
    ]


def _synthetic_result(
    blocked: list[dict[str, Any]],
    *,
    dry_run: bool,
    force_required: bool = False,
) -> dict[str, Any]:
    """构造 classify_and_delete 的桩返回值（仅含 MCP 层消费的键）。

    用于注入真实链路不可达的组合（dry_run 携带 delete_failure、护栏与 delete_failure
    同帧），锁定 MCP 层的分支优先级与判据精确性。
    """
    entry = {"file": "a.jpg", "path": "/ws/a.jpg"}
    return {
        "summary": {
            "workspace": "/ws",
            "total": 2,
            "selected": 1,
            "to_delete": 1,
            "deleted": 0 if dry_run else 1,
            "pending": 1 if dry_run else 0,
            "blocked": len(blocked),
            "unevaluated": 0,
            "mode": "dry_run" if dry_run else "actual_delete",
            "force_required": force_required,
            "fingerprint": "0123456789ab",
            "confirm_required": False,
            "recycle": True,
            "delete_manifest": None,
            "audit_failed": False,
            "vlm_applied": 0,
            "vlm_degraded": 0,
            "elapsed_ms": 0,
        },
        "pending_delete": [entry] if dry_run else [],
        "deleted": [] if dry_run else [entry],
        "delete_audit": [],
        "blocked": blocked,
        "unevaluated": [],
        "kept": [{"file": "keep.jpg", "path": "/ws/keep.jpg"}],
    }


def test_cleanup_delete_failure_returns_nonzero(
    tmp_path: Path, sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H-10：回收站移动失败（文件被占用 / 跨卷）→ 非 0 码 + status="partial"。

    真实故障注入（monkeypatch Path.replace 抛 OSError）驱动真实 classify_and_delete，
    不用纯 mock 假装失败——替身会与真实删除语义脱节（M-18 教训）。
    """
    from flashgaze.models.schemas import ExitCode

    paths = _occupied_ws(tmp_path, sharp_img)
    scores = _scores_for(paths, [90.0, 10.0, 5.0])  # top=1 → 后两张待删

    def _deny(self: Path, target: Path) -> None:
        raise OSError(13, "模拟文件被占用")

    monkeypatch.setattr(Path, "replace", _deny)

    with mock.patch("flashgaze.core.cleanup.make_scorer") as ms:
        ms.return_value.score_paths.return_value = scores
        raw = cleanup_workspace_images(str(tmp_path), no_vlm=True, top=1, dry_run=False)
    data = json.loads(raw)

    assert data["status"] == "partial"
    assert data["code"] == int(ExitCode.EXPORT_ERROR)
    assert "删除部分失败" in data["message"]
    assert data["summary"]["to_delete"] == 2
    assert data["summary"]["deleted"] == 0
    assert data["summary"]["blocked"] == 2
    # 结构化计数：Agent 无需解析 details.blocked_files 的文本拼接
    assert data["summary"]["delete_failures"] == 2
    failures = data["details"]["delete_failures"]
    assert len(failures) == 2
    assert all(f["reason"].startswith("删除失败") for f in failures)
    assert {Path(f["path"]).name for f in failures} == {"pic01.jpg", "pic02.jpg"}
    assert data["details"]["deleted_files"] == []
    # 回收站移动失败绝不降级为 unlink：两张低分图仍原样留在磁盘上
    assert all(p.exists() for p in paths)


def test_cleanup_delete_failure_keeps_six_fields_and_blocked_text(
    tmp_path: Path, sharp_img: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H-10：partial 响应仍是六字段 Schema，details.blocked_files 文本格式逐字不变。"""
    paths = _occupied_ws(tmp_path, sharp_img)
    scores = _scores_for(paths, [90.0, 10.0, 5.0])

    def _deny(self: Path, target: Path) -> None:
        raise OSError(13, "模拟文件被占用")

    monkeypatch.setattr(Path, "replace", _deny)

    with mock.patch("flashgaze.core.cleanup.make_scorer") as ms:
        ms.return_value.score_paths.return_value = scores
        raw = cleanup_workspace_images(str(tmp_path), no_vlm=True, top=1, dry_run=False)
    data = json.loads(raw)

    assert set(data.keys()) == _SIX_FIELDS
    assert set(data["details"]) >= {
        "kept_images",
        "deleted_files",
        "blocked_files",
        "unevaluated_files",
    }
    # 新明细走独立键，旧文本拼接格式不被改动（既有消费方按该格式解析）
    for f in data["details"]["delete_failures"]:
        assert f"{f['path']} ({f['reason']})" in data["details"]["blocked_files"]


def test_cleanup_zero_delete_failure_stays_success_with_explicit_zero(
    tmp_path: Path, sharp_img: str
) -> None:
    """H-10：零删除失败仍 success，且显式给 delete_failures=0（Agent 读同一键）。"""
    paths = _occupied_ws(tmp_path, sharp_img)
    scores = _scores_for(paths, [90.0, 10.0, 5.0])

    with mock.patch("flashgaze.core.cleanup.make_scorer") as ms:
        ms.return_value.score_paths.return_value = scores
        raw = cleanup_workspace_images(str(tmp_path), no_vlm=True, top=1, dry_run=False)
    data = json.loads(raw)

    assert data["status"] == "success"
    assert data["code"] == 0
    assert data["summary"]["deleted"] == 2
    assert data["summary"]["delete_failures"] == 0
    assert paths[0].exists()  # 高分图保留
    assert not paths[1].exists() and not paths[2].exists()


def test_cleanup_delete_failure_in_dry_run_not_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """反例：dry_run 下即使 blocked 含 delete_failure，也不得降级为非 0。

    与 CLI「not dry_run and has_delete_failure」判据同构。classify_and_delete 在
    dry_run 下只写 pending_list、结构上不产生该 kind，此处以桩锁定防御语义。
    """
    import flashgaze.mcp_server as mcp_mod

    blocked = [{"path": "/ws/a.jpg", "reason": "删除失败: 模拟", "kind": "delete_failure"}]
    (tmp_path / "a.jpg").write_bytes(b"fake")

    with (
        mock.patch("flashgaze.core.cleanup.make_scorer") as ms,
        monkeypatch.context() as mp,
    ):
        ms.return_value.score_paths.return_value = _scores_for([tmp_path / "a.jpg"], [1.0])
        mp.setattr(
            mcp_mod,
            "classify_and_delete",
            lambda *a, **kw: _synthetic_result(blocked, dry_run=True),
        )
        raw = cleanup_workspace_images(str(tmp_path), no_vlm=True, top=1)  # dry_run 默认 True
    data = json.loads(raw)

    assert data["status"] == "success"
    assert data["code"] == 0


def test_cleanup_other_blocked_kinds_stay_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """反例：非 delete_failure 的安全拦截不触发非 0——判据按 kind 精确匹配。

    「blocked 非空即失败」会让每一次正常的安全拦截（越界/符号链接/非常规文件/stat
    失败）都伪装成清理失败，与 CLI 语义相反。
    """
    import flashgaze.mcp_server as mcp_mod

    blocked = [
        {"path": "/ws/out.jpg", "reason": "路径在工作空间外，已拦截", "kind": "outside_workspace"},
        {"path": "/ws/link.jpg", "reason": "路径是符号链接，已拦截", "kind": "symlink_path"},
        {"path": "/ws/dev.jpg", "reason": "非常规文件，已跳过", "kind": "not_regular_file"},
        {"path": "/ws/gone.jpg", "reason": "stat 失败: 模拟", "kind": "stat_failed"},
    ]
    (tmp_path / "a.jpg").write_bytes(b"fake")

    with (
        mock.patch("flashgaze.core.cleanup.make_scorer") as ms,
        monkeypatch.context() as mp,
    ):
        ms.return_value.score_paths.return_value = _scores_for([tmp_path / "a.jpg"], [1.0])
        mp.setattr(
            mcp_mod,
            "classify_and_delete",
            lambda *a, **kw: _synthetic_result(blocked, dry_run=False),
        )
        raw = cleanup_workspace_images(str(tmp_path), no_vlm=True, top=1, dry_run=False)
    data = json.loads(raw)

    assert data["status"] == "success"
    assert data["code"] == 0
    assert len(data["details"]["blocked_files"]) == 4
    assert data["details"]["deleted_files"] == ["a.jpg"]


def test_cleanup_guard_blocked_precedes_delete_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """反例：护栏拦截（一张未删）与 delete_failure 同帧时，仍以 blocked/1 为准。

    真实链路下二者互斥（护栏拦截时全部待删项被 continue，进不到删除分支），此处以桩
    锁定分支优先级：新增的 delete_failure 分支排在 force_required 之后。
    """
    import flashgaze.mcp_server as mcp_mod
    from flashgaze.models.schemas import ExitCode

    blocked = [
        {"path": "/ws/a.jpg", "reason": "待删比例 100% 超过 95% 安全阈值", "kind": "guard"},
        {"path": "/ws/b.jpg", "reason": "删除失败: 模拟", "kind": "delete_failure"},
    ]
    (tmp_path / "a.jpg").write_bytes(b"fake")

    with (
        mock.patch("flashgaze.core.cleanup.make_scorer") as ms,
        monkeypatch.context() as mp,
    ):
        ms.return_value.score_paths.return_value = _scores_for([tmp_path / "a.jpg"], [1.0])
        mp.setattr(
            mcp_mod,
            "classify_and_delete",
            lambda *a, **kw: _synthetic_result(blocked, dry_run=False, force_required=True),
        )
        raw = cleanup_workspace_images(str(tmp_path), no_vlm=True, top=1, dry_run=False)
    data = json.loads(raw)

    assert data["status"] == "blocked"
    assert data["code"] == int(ExitCode.PARAM_ERROR)
    assert data["summary"]["force_required"] is True
