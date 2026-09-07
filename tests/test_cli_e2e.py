"""端到端 CLI 测试。

用 subprocess 真实调用 `python -m flashgaze`，验证返回码与输出。
模拟 AI Agent 通过 subprocess 调用的真实场景。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

FLASHGAZE_CMD = [sys.executable, "-m", "flashgaze"]


def _run(
    args: list[str],
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """调用 flashgaze，返回 CompletedProcess。"""
    env = os.environ.copy()
    # 默认清理 API Key，避免环境污染 CONFIG_ERROR 测试
    env.pop("FLASHGAZE_API_KEY", None)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        FLASHGAZE_CMD + args,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        encoding="utf-8",
        check=False,  # 返回码由各用例自行断言（含预期失败场景）
    )


@pytest.fixture
def photo_dir(tmp_path: Path, fixtures_dir: Path) -> str:
    """复制 sharp/blurry/corrupted 到临时目录。"""
    for name in ("sharp.jpg", "blurry.jpg", "corrupted.jpg"):
        src = fixtures_dir / name
        if src.exists():
            shutil.copy2(src, tmp_path / name)
    return str(tmp_path)


# ---------- ExitCode.SUCCESS (0) ----------


def test_e2e_success_no_vlm_json(photo_dir: str) -> None:
    """正常评分 + --no-vlm + --json → exit 0，stdout 是合法 JSON。"""
    result = _run([photo_dir, "--no-vlm", "--top", "2", "--json"])
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["status"] == "success"
    assert data["code"] == 0
    assert data["summary"]["total"] == 3
    assert data["summary"]["selected"] == 2
    # sharp.jpg 应是最高分
    assert data["images"][0]["file"] == "sharp.jpg"
    assert data["images"][0]["selected"] is True


def test_e2e_success_csv_output(photo_dir: str, tmp_path: Path) -> None:
    """--csv 生成 CSV 文件。"""
    csv_path = tmp_path / "result.csv"
    result = _run([photo_dir, "--no-vlm", "--csv", "--csv-output", str(csv_path)])
    assert result.returncode == 0
    assert csv_path.exists()
    content = csv_path.read_text(encoding="utf-8-sig")
    assert "file" in content
    assert "sharp.jpg" in content


def test_e2e_json_output_to_both_stdout_and_file(photo_dir: str, tmp_path: Path) -> None:
    """--json --output <file> --no-vlm → exit 0，stdout 仍含合法 JSON，文件也写入。

    验证 _emit_json 修改后行为：无论是否指定 --output，只要 --json 为真，
    JSON 同时打印到 stdout 且（若有 output_path）原子写入文件。
    """
    out_path = tmp_path / "result.json"
    result = _run(
        [
            photo_dir,
            "--no-vlm",
            "--top",
            "1",
            "--json",
            "--output",
            str(out_path),
        ]
    )
    assert result.returncode == 0
    # stdout 非空且可解析为 JSON（不再因 --output 而只写文件）
    assert result.stdout.strip() != ""
    data = json.loads(result.stdout)
    assert data["code"] == 0
    assert data["summary"]["total"] == 3
    # 文件同样被原子写入
    assert out_path.exists()
    file_data = json.loads(out_path.read_text(encoding="utf-8"))
    assert file_data["code"] == 0


def test_e2e_cleans_stale_tmp_before_writing(photo_dir: str, tmp_path: Path) -> None:
    """启动时清理上次崩溃遗留的原子写临时文件，正常结果文件照常生成。"""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    stale = out_dir / ".result.json.tmp.999999"
    stale.write_text("half-written", encoding="utf-8")
    # M-10：cleanup_stale_tmp 跳过 mtime 距今 1 小时内的新鲜 tmp，须拨老模拟崩溃残留
    old = time.time() - 2 * 3600
    os.utime(stale, (old, old))
    out_path = out_dir / "result.json"
    result = _run(
        [
            photo_dir,
            "--no-vlm",
            "--top",
            "1",
            "--json",
            "--output",
            str(out_path),
        ]
    )
    assert result.returncode == 0
    assert not stale.exists()
    assert json.loads(out_path.read_text(encoding="utf-8"))["code"] == 0


def test_e2e_export_creates_dest(photo_dir: str, tmp_path: Path) -> None:
    """--export + --export-dir 创建目标目录并复制 selected 图。"""
    dest_dir = tmp_path / "精选"
    result = _run([photo_dir, "--no-vlm", "--top", "1", "--export", "--export-dir", str(dest_dir)])
    assert result.returncode == 0
    assert dest_dir.exists()
    files = list(dest_dir.iterdir())
    assert len(files) == 1
    assert files[0].name == "sharp.jpg"


# ---------- ExitCode.NO_IMAGES (3) ----------


def test_e2e_nonexistent_directory(tmp_path: Path) -> None:
    """不存在的目录 → exit 3。"""
    result = _run([str(tmp_path / "nope")])
    assert result.returncode == 3


def test_e2e_empty_directory(tmp_path: Path) -> None:
    """空目录 → exit 3。"""
    result = _run([str(tmp_path)])
    assert result.returncode == 3


# ---------- ExitCode.CONFIG_ERROR (6) ----------


def test_e2e_missing_api_key_without_no_vlm(photo_dir: str) -> None:
    """未配 API Key 且未 --no-vlm → exit 6。"""
    result = _run([photo_dir, "--top", "1"])
    assert result.returncode == 6
    assert "API Key" in result.stderr


def test_e2e_api_key_from_env(photo_dir: str) -> None:
    """环境变量提供 API Key 时不报 CONFIG_ERROR（但 VLM 调用会失败，降级为 0）。"""
    result = _run(
        [photo_dir, "--top", "1", "--json"],
        env_overrides={"FLASHGAZE_API_KEY": "fake-key-for-test"},
    )
    # VLM 调用 fake endpoint 会失败，但降级为 CV-only，整体仍 SUCCESS
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["code"] == 0


# ---------- ExitCode.PARAM_ERROR (1) ----------


def test_e2e_missing_directory_arg() -> None:
    """缺必选参数 → exit 1。"""
    result = _run(["--no-vlm"])
    assert result.returncode == 1


# ---------- 损坏图不中断 ----------


def test_e2e_corrupted_image_does_not_crash(photo_dir: str) -> None:
    """corrupted.jpg 在目录中不中断流程，JSON 里该图有 error。"""
    result = _run([photo_dir, "--no-vlm", "--json"])
    assert result.returncode == 0
    data = json.loads(result.stdout)
    corrupted = [img for img in data["images"] if img["file"] == "corrupted.jpg"]
    assert len(corrupted) == 1
    assert corrupted[0]["error"] is not None
    assert corrupted[0]["score"] == 0.0


# ---------- --version ----------


def test_e2e_version() -> None:
    """--version 正常退出。"""
    result = _run(["--version"])
    assert result.returncode == 0
    assert "flashgaze" in result.stdout


# ---------- stdout/stderr 分离 ----------


def test_e2e_json_goes_to_stdout_not_stderr(photo_dir: str) -> None:
    """JSON 数据走 stdout，stderr 不含 JSON。"""
    result = _run([photo_dir, "--no-vlm", "--json"])
    assert result.returncode == 0
    json.loads(result.stdout)  # stdout 是合法 JSON
    # stderr 不应含 JSON 数据
    assert "status" not in result.stderr
    assert "summary" not in result.stderr


# ---------- CV 增强维度端到端（M10）----------


def test_e2e_default_json_has_null_for_optional_fields(photo_dir: str) -> None:
    """默认不启用任何新维度时，JSON 中 noise/color/face_count 等字段为 null/0。"""
    result = _run([photo_dir, "--no-vlm", "--top", "1", "--json"])
    assert result.returncode == 0
    data = json.loads(result.stdout)
    img = data["images"][0]
    # 未启用新维度 → noise/color 为 None，face_count/portrait_bonus 为 0，deduped 为 False
    assert img["noise"] is None
    assert img["color"] is None
    assert img["face_count"] == 0
    assert img["portrait_bonus"] == 0.0
    assert img["deduped"] is False


def test_e2e_enable_color_outputs_color_field(photo_dir: str) -> None:
    """启用 --enable-color 后 JSON 中 color 字段非 null（OpenCV 内置，依赖必可用）。"""
    result = _run([photo_dir, "--no-vlm", "--enable-color", "--top", "1", "--json"])
    assert result.returncode == 0
    data = json.loads(result.stdout)
    # 至少有一张有效图的 color 字段非 None
    valid_imgs = [img for img in data["images"] if img["error"] is None]
    assert valid_imgs, "应至少有一张有效图"
    for img in valid_imgs:
        assert img["color"] is not None
        assert 0.0 <= img["color"] <= 100.0


def test_e2e_enable_all_features_does_not_crash(photo_dir: str) -> None:
    """同时启用全部 CV 增强维度（含依赖可能缺失的）不崩溃，整体返回 0。

    依赖缺失的维度（noise/portrait/dedup）字段为 null/0/false，
    依赖内置的 color 维度正常输出。
    """
    result = _run(
        [
            photo_dir,
            "--no-vlm",
            "--top",
            "1",
            "--json",
            "--enable-noise",
            "--enable-color",
            "--enable-portrait",
            "--enable-dedup",
        ]
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["code"] == 0
    # 验证 JSON 结构完整，未因依赖缺失而异常
    assert "images" in data
    assert len(data["images"]) > 0


def test_e2e_enable_composition_with_partial_weights_injects_composition() -> None:
    """回归：--enable-composition 配缺 composition key 的 --weights 时，composition 进入最终分。

    复现命令（评分口径变更 PLAN-weight-injection）：
        flashgaze ./tests --enable-composition \\
            --weights '{"sharpness":0.7,"exposure":0.3}' --no-vlm --json
    此前 composition 零贡献；修复后按注入权重 0.56/0.24/0.20 计入最终分。
    """
    tests_dir = str(Path(__file__).resolve().parent)  # 即仓库 ./tests
    result = _run(
        [
            tests_dir,
            "--no-vlm",
            "--json",
            "--enable-composition",
            "--weights",
            '{"sharpness": 0.7, "exposure": 0.3}',
        ]
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    valid = [img for img in data["images"] if img["error"] is None]
    assert valid, "应至少有一张有效图"
    for img in valid:
        # composition 必须被注入并计入最终分
        assert img["composition"] is not None
        expected = round(
            0.56 * img["sharpness"] + 0.24 * img["exposure"] + 0.20 * img["composition"], 2
        )
        assert img["score"] == expected, "最终分未按注入权重加权（composition 未贡献）"


def test_e2e_csv_contains_new_columns(photo_dir: str, tmp_path: Path) -> None:
    """CSV 输出包含 noise/color/face_count/face_sharpness/portrait_bonus/deduped 列。"""
    csv_path = tmp_path / "result.csv"
    result = _run(
        [
            photo_dir,
            "--no-vlm",
            "--enable-color",
            "--csv",
            "--csv-output",
            str(csv_path),
        ]
    )
    assert result.returncode == 0
    assert csv_path.exists()
    content = csv_path.read_text(encoding="utf-8-sig")
    # 表头必须包含所有新列
    header_line = content.splitlines()[0]
    for col in ("noise", "color", "face_count", "face_sharpness", "portrait_bonus", "deduped"):
        assert col in header_line, f"CSV 表头缺少列: {col}"


def test_e2e_enable_dedup_without_dependency_does_not_crash(photo_dir: str) -> None:
    """启用 --enable-dedup 但 imagededup 缺失时不报错（优雅降级）。

    依赖缺失时去重逻辑跳过，所有图保持原 selected 状态。
    """
    result = _run([photo_dir, "--no-vlm", "--enable-dedup", "--json"])
    assert result.returncode == 0
    data = json.loads(result.stdout)
    # 即使去重未生效，整体仍应成功
    assert data["code"] == 0


# ---------- VLM 扩展端到端（M9）----------


def test_e2e_no_vlm_json_has_empty_vlm_fields(photo_dir: str) -> None:
    """--no-vlm 模式下 JSON 输出包含 vlm_reason='' / vlm_provider=''。"""
    result = _run([photo_dir, "--no-vlm", "--top", "1", "--json"])
    assert result.returncode == 0
    data = json.loads(result.stdout)
    img = data["images"][0]
    assert img["vlm_reason"] == ""
    assert img["vlm_provider"] == ""
    assert img["vlm_adjustment"] == 0.0


def test_e2e_scene_portrait_with_no_vlm_succeeds(photo_dir: str) -> None:
    """--scene portrait + --no-vlm 组合正常执行（场景提示词不生效但不报错）。"""
    result = _run(
        [
            photo_dir,
            "--no-vlm",
            "--scene",
            "portrait",
            "--top",
            "1",
            "--json",
        ]
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["code"] == 0


def test_e2e_vlm_provider_qwen_no_litellm_runs_as_before(photo_dir: str) -> None:
    """--vlm-provider qwen（默认路径）+ 假 API Key + 不装 litellm 时降级为纯 CV。

    与原版行为完全一致：VLM 调用失败回退纯 CV，整体 SUCCESS。
    """
    result = _run(
        [
            photo_dir,
            "--vlm-provider",
            "qwen",
            "--top",
            "1",
            "--json",
        ],
        env_overrides={"FLASHGAZE_API_KEY": "fake-key-for-test"},
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["code"] == 0
    # VLM 失败 → vlm_reason/vlm_provider 为空串
    img = data["images"][0]
    assert img["vlm_reason"] == ""
    assert img["vlm_provider"] == ""


def test_e2e_vlm_provider_openai_without_litellm_falls_back(photo_dir: str) -> None:
    """--vlm-provider openai 但未装 litellm 时降级为纯 CV，主流程不阻塞。"""
    result = _run(
        [
            photo_dir,
            "--vlm-provider",
            "openai",
            "--scene",
            "portrait",
            "--top",
            "1",
            "--json",
        ],
        env_overrides={"FLASHGAZE_API_KEY": "fake-key-for-test"},
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["code"] == 0
    # litellm 未安装 → vlm_reason/vlm_provider 为空串
    img = data["images"][0]
    assert img["vlm_reason"] == ""
    assert img["vlm_provider"] == ""


def test_e2e_csv_includes_vlm_reason_and_provider_columns(photo_dir: str, tmp_path: Path) -> None:
    """CSV 输出包含 vlm_reason / vlm_provider 列。"""
    csv_path = tmp_path / "result.csv"
    result = _run(
        [
            photo_dir,
            "--no-vlm",
            "--csv",
            "--csv-output",
            str(csv_path),
        ]
    )
    assert result.returncode == 0
    assert csv_path.exists()
    content = csv_path.read_text(encoding="utf-8-sig")
    header_line = content.splitlines()[0]
    assert "vlm_reason" in header_line
    assert "vlm_provider" in header_line


def test_e2e_invalid_scene_rejected_by_argparse(photo_dir: str) -> None:
    """--scene 非法值被 argparse 拒绝（exit code=1）。"""
    result = _run([photo_dir, "--no-vlm", "--scene", "macro"])
    assert result.returncode == 1


def test_e2e_invalid_vlm_provider_rejected_by_argparse(photo_dir: str) -> None:
    """--vlm-provider 非法值被 argparse 拒绝（exit code=1）。"""
    result = _run([photo_dir, "--no-vlm", "--vlm-provider", "claude"])
    assert result.returncode == 1


def test_e2e_output_path_outside_workspace_rejected(photo_dir: str, tmp_path: Path) -> None:
    """--output 指向被扫描目录之外：硬拒绝，进程退出码 1（PARAM_ERROR）。

    破坏性变更（CHANGELOG [未发布]）的进程边界回归：sys.exit(2) 经 main()
    收敛为 1；此前同类场景仅 warning 后照常写入（exit 0）。
    """
    outside = tmp_path.parent / "escaped_e2e.json"  # photo_dir（=tmp_path）的兄弟目录
    result = _run([photo_dir, "--no-vlm", "--json", "--output", str(outside)])
    assert result.returncode == 1
    assert not outside.exists()  # 越界文件不落盘


def test_e2e_cleanup_output_path_outside_rejected_before_delete(
    photo_dir: str, tmp_path: Path
) -> None:
    """cleanup --apply + 越界 --output：退出码 1，且删除未发生（校验前置）。

    Agent 场景回归：修复前实删已完成才在报告渲染层拒绝——图片已删而
    退出码 1 与事实矛盾，且报告既不落盘也不打印，结果记录全丢。
    """
    outside = tmp_path.parent / "escaped_cleanup_e2e.json"
    args = ["cleanup", photo_dir, "--no-vlm", "--top", "1", "--apply", "--json", "--output"]
    result = _run([*args, str(outside)])
    assert result.returncode == 1
    assert "拒绝越界" in result.stderr
    assert not outside.exists()
    # 校验先于 run_cleanup：三张固件图一张未删
    for name in ("sharp.jpg", "blurry.jpg", "corrupted.jpg"):
        assert (tmp_path / name).exists()
