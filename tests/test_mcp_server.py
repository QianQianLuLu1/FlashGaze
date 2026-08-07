"""MCP Server 工具函数单元测试。

覆盖 _build_config / _filter_image_files / _is_within_directory / _error / _success
以及 5 个 MCP 工具的成功路径与错误码（3/4/6）。
验证 A-01/A-02（_build_config 委托 + env 覆盖）、U-01（六字段统一 Schema）、
C-12（cleanup TOCTOU 防护）等重构落地。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

pytest.importorskip("mcp")

from flashgaze.mcp_server import (
    _build_config,
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


# ── _build_config（A-01/A-02）──────────────────────────


class TestBuildConfig:
    """验证 _build_config 委托 build_config，且参数默认 None 时 env 生效。"""

    def test_defaults_return_config(self):
        """不传任何 override 时，应回落到 defaults.py 默认值。"""
        cfg = _build_config(directory="/tmp")
        assert cfg.directory == "/tmp"
        assert cfg.top == 30  # DEFAULT_TOP
        assert cfg.workers == 4  # DEFAULT_WORKERS
        assert cfg.no_vlm is False
        assert cfg.enable_composition is False

    def test_workers_override(self):
        """显式传 workers 应覆盖 env 与 default。"""
        cfg = _build_config(directory="/tmp", workers=8)
        assert cfg.workers == 8

    def test_top_override(self):
        cfg = _build_config(directory="/tmp", top=5)
        assert cfg.top == 5

    def test_env_workers_respected(self, monkeypatch):
        """A-02 核心：MCP 调用方不传 workers 时，FLASHGAZE_WORKERS 应生效（机器无关）。"""
        cpu_count = os.cpu_count() or 4
        cap = min(cpu_count, 16)
        # 取一个明确 ≤ cap 的值，证明 env 覆盖生效且不受钳制影响
        env_val = cap // 2 if cap >= 2 else cap
        monkeypatch.setenv("FLASHGAZE_WORKERS", str(env_val))
        cfg = _build_config(directory="/tmp")  # workers 默认 None
        assert cfg.workers == env_val

    def test_env_workers_clamped(self, monkeypatch):
        """env 超过 cpu 上限时，应被钳制到 min(cpu_count, 16)。"""
        cpu_count = os.cpu_count() or 4
        cap = min(cpu_count, 16)
        monkeypatch.setenv("FLASHGAZE_WORKERS", "999")
        cfg = _build_config(directory="/tmp")  # workers 默认 None
        assert cfg.workers == cap

    def test_env_workers_overridden_by_param(self, monkeypatch):
        """显式参数优先级高于 env。"""
        monkeypatch.setenv("FLASHGAZE_WORKERS", "16")
        cfg = _build_config(directory="/tmp", workers=2)
        assert cfg.workers == 2

    def test_env_api_key_respected(self, monkeypatch):
        monkeypatch.setenv("FLASHGAZE_API_KEY", "sk-test")
        cfg = _build_config(directory="/tmp")
        assert cfg.api_key == "sk-test"


# ── _error / _success（U-01/U-03 六字段 Schema）─────────


class TestResponseSchema:
    """验证所有响应遵循六字段统一 Schema。"""

    def test_error_has_six_fields(self):
        raw = _error(3, "目录不存在")
        data = json.loads(raw)
        assert set(data.keys()) == {"status", "code", "message", "summary", "images", "details"}
        assert data["status"] == "error"
        assert data["code"] == 3
        assert data["message"] == "目录不存在"
        assert data["summary"] == {}
        assert data["images"] is None
        assert data["details"] is None

    def test_success_has_six_fields(self):
        raw = _success(summary={"total": 1}, images=[{"file": "a.jpg"}], details={"k": "v"})
        data = json.loads(raw)
        assert set(data.keys()) == {"status", "code", "message", "summary", "images", "details"}
        assert data["status"] == "success"
        assert data["code"] == 0
        assert data["message"] is None
        assert data["summary"] == {"total": 1}
        assert data["images"] == [{"file": "a.jpg"}]
        assert data["details"] == {"k": "v"}

    def test_success_minimal(self):
        raw = _success(summary={})
        data = json.loads(raw)
        assert data["images"] is None
        assert data["details"] is None


# ── _filter_image_files ────────────────────────────────


class TestFilterImageFiles:
    def test_empty_list(self):
        valid, skipped = _filter_image_files([])
        assert valid == []
        assert skipped == []

    def test_nonexistent_file(self, tmp_path):
        valid, skipped = _filter_image_files([str(tmp_path / "nope.jpg")])
        assert valid == []
        assert len(skipped) == 1
        assert "文件不存在" in skipped[0]

    def test_unsupported_format(self, tmp_path):
        txt = tmp_path / "note.txt"
        txt.write_text("hello", encoding="utf-8")
        valid, skipped = _filter_image_files([str(txt)])
        assert valid == []
        assert "不支持的格式" in skipped[0]

    def test_valid_image(self, sharp_img):
        valid, skipped = _filter_image_files([sharp_img])
        assert len(valid) == 1
        assert skipped == []


# ── _is_within_directory ───────────────────────────────


class TestIsWithinDirectory:
    def test_file_inside(self, tmp_path):
        f = tmp_path / "a.jpg"
        f.write_text("x", encoding="utf-8")
        assert _is_within_directory(f, tmp_path) is True

    def test_file_outside(self, tmp_path):
        outside = tmp_path.parent / "outside.jpg"
        try:
            outside.write_text("x", encoding="utf-8")
            assert _is_within_directory(outside, tmp_path) is False
        finally:
            if outside.exists():
                outside.unlink()

    def test_root_itself(self, tmp_path):
        # 根目录本身相对自身应为 True
        assert _is_within_directory(tmp_path, tmp_path) is True


# ── score_images ───────────────────────────────────────


class TestScoreImages:
    def test_directory_not_exist(self):
        raw = score_images("/nonexistent/path/xyz")
        data = json.loads(raw)
        assert data["status"] == "error"
        assert data["code"] == 3

    def test_empty_directory(self, tmp_path):
        raw = score_images(str(tmp_path))
        data = json.loads(raw)
        assert data["code"] == 3
        assert "无支持格式" in data["message"]

    def test_score_success_no_vlm(self, tmp_path, sharp_img):
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
    def test_file_not_exist(self):
        raw = score_single_image("/nonexistent.jpg", no_vlm=True)
        data = json.loads(raw)
        assert data["code"] == 3

    def test_unsupported_format(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("x", encoding="utf-8")
        raw = score_single_image(str(f), no_vlm=True)
        data = json.loads(raw)
        assert data["code"] == 3
        assert "不支持" in data["message"]

    def test_single_success(self, sharp_img):
        raw = score_single_image(sharp_img, no_vlm=True)
        data = json.loads(raw)
        assert data["status"] == "success"
        # U-02：单图模式 selected 恒为 0，images 为单元素数组
        assert data["summary"]["total"] == 1
        assert data["summary"]["selected"] == 0
        assert len(data["images"]) == 1


# ── export_selected_images ─────────────────────────────


class TestExportSelectedImages:
    def test_directory_not_exist(self):
        raw = export_selected_images("/nonexistent/xyz")
        data = json.loads(raw)
        assert data["code"] == 3

    def test_export_success(self, tmp_path, sharp_img):
        import shutil

        dst = tmp_path / "src" / "sharp.jpg"
        dst.parent.mkdir()
        shutil.copy(sharp_img, dst)
        dest = tmp_path / "out"
        raw = export_selected_images(
            str(dst.parent), no_vlm=True, dest_dir=str(dest), top=1
        )
        data = json.loads(raw)
        assert data["status"] == "success"
        assert data["details"]["dest_dir"] == str(dest.resolve())
        assert data["details"]["mode"] == "copy"
        # 导出目录应有文件
        assert any(dest.iterdir())


# ── score_uploaded_images ──────────────────────────────


class TestScoreUploadedImages:
    def test_empty_list(self):
        raw = score_uploaded_images([])
        data = json.loads(raw)
        assert data["code"] == 1

    def test_all_invalid(self):
        raw = score_uploaded_images(["/nonexistent.jpg"])
        data = json.loads(raw)
        assert data["code"] == 3

    def test_success_with_skipped(self, sharp_img, tmp_path):
        txt = tmp_path / "x.txt"
        txt.write_text("x", encoding="utf-8")
        raw = score_uploaded_images([sharp_img, str(txt)], no_vlm=True)
        data = json.loads(raw)
        assert data["status"] == "success"
        # skipped 在 details 中
        assert "skipped" in data["details"]
        assert len(data["details"]["skipped"]) == 1


# ── cleanup_workspace_images（C-12 TOCTOU 防护）────────


class TestCleanupWorkspace:
    def test_workspace_not_exist(self):
        raw = cleanup_workspace_images("/nonexistent/ws")
        data = json.loads(raw)
        assert data["code"] == 3

    def test_dry_run_default(self, tmp_path, sharp_img):
        """dry_run 默认 True，不实际删除。"""
        import shutil

        f = tmp_path / "sharp.jpg"
        shutil.copy(sharp_img, f)
        raw = cleanup_workspace_images(str(tmp_path), no_vlm=True, top=0)
        data = json.loads(raw)
        assert data["status"] == "success"
        assert data["summary"]["mode"] == "dry_run"
        # dry_run 模式文件仍在
        assert f.exists()

    def test_actual_delete(self, tmp_path, sharp_img):
        """dry_run=False 时实际删除低分图。"""
        import shutil

        f = tmp_path / "sharp.jpg"
        shutil.copy(sharp_img, f)
        raw = cleanup_workspace_images(
            str(tmp_path), no_vlm=True, top=0, dry_run=False
        )
        data = json.loads(raw)
        assert data["status"] == "success"
        assert data["summary"]["mode"] == "actual_delete"

    def test_blocked_outside_file(self, tmp_path, sharp_img, monkeypatch):
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
        with mock.patch("flashgaze.mcp_server.make_scorer") as ms:
            scorer = ms.return_value
            scorer.score_paths.return_value = [outside_score]
            raw = cleanup_workspace_images(
                str(tmp_path), no_vlm=True, top=0, dry_run=False
            )
        data = json.loads(raw)
        # 工作空间外的文件应被拦截
        assert len(data["details"]["blocked_files"]) >= 1

    def test_unevaluated_files_tracked(self, tmp_path, sharp_img, corrupted_img):
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
