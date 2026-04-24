from pathlib import Path

from PIL import Image

from file_ops import (
    DELETE_CONFIRM_THRESHOLD,
    DELETE_CONFIRM_TEXT,
    estimate_output_count,
    format_output_preview,
    format_split_summary,
    get_output_dir_for_image,
    is_dangerous_delete_target,
    needs_typed_delete_confirmation,
    open_folder,
)
from image_splitter import guess_grid_by_ratio, is_image_file, make_unique_stem, split_equal_grid


def test_image_file_detection_supports_known_extensions():
    assert is_image_file(Path("demo.PNG")) is True
    assert is_image_file(Path("demo.jfif")) is True
    assert is_image_file(Path("demo.txt")) is False


def test_guess_grid_by_ratio_matches_existing_rules():
    assert guess_grid_by_ratio(560, 1000) == 2
    assert guess_grid_by_ratio(1000, 1000) == 3
    assert guess_grid_by_ratio(1600, 900) == 2


def test_split_equal_grid_covers_odd_sized_image_without_losing_pixels():
    img = Image.new("RGB", (1001, 999), "white")

    crops = split_equal_grid(img, 3, 3)

    widths_by_row = [sum(tile.size[0] for _, tile in crops[i:i + 3]) for i in range(0, 9, 3)]
    heights_by_col = [sum(crops[r * 3 + c][1].size[1] for r in range(3)) for c in range(3)]
    assert widths_by_row == [1001, 1001, 1001]
    assert heights_by_col == [999, 999, 999]


def test_make_unique_stem_skips_existing_files(tmp_path):
    (tmp_path / "tile.png").write_bytes(b"x")
    (tmp_path / "tile_001.png").write_bytes(b"x")

    assert make_unique_stem(tmp_path, "tile", ".png") == "tile_002"


def test_file_ops_keep_folder_and_delete_safety_behaviour(tmp_path):
    target = tmp_path / "new-output"

    open_folder(str(target), launch=False)

    assert target.is_dir()
    assert estimate_output_count(2, "2") == 8
    assert estimate_output_count(2, "auto") is None
    assert is_dangerous_delete_target(Path.home()) is True
    assert is_dangerous_delete_target(target) is False


def test_output_dir_planning_preserves_relative_folder_for_batch_input(tmp_path):
    input_root = tmp_path / "input"
    image_path = input_root / "chapter-a" / "scene-01" / "grid.png"
    output_root = tmp_path / "output"

    flat_dir = get_output_dir_for_image(image_path, output_root, input_root, preserve_structure=False)
    nested_dir = get_output_dir_for_image(image_path, output_root, input_root, preserve_structure=True)

    assert flat_dir == output_root
    assert nested_dir == output_root / "chapter-a" / "scene-01"


def test_output_dir_planning_ignores_structure_for_single_file(tmp_path):
    image_path = tmp_path / "grid.png"
    output_root = tmp_path / "output"

    assert get_output_dir_for_image(image_path, output_root, None, preserve_structure=True) == output_root


def test_large_delete_confirmation_policy():
    assert DELETE_CONFIRM_TEXT == "DELETE"
    assert needs_typed_delete_confirmation(DELETE_CONFIRM_THRESHOLD - 1) is False
    assert needs_typed_delete_confirmation(DELETE_CONFIRM_THRESHOLD) is True
    assert needs_typed_delete_confirmation(DELETE_CONFIRM_THRESHOLD + 1) is True


def test_split_summary_without_failures(tmp_path):
    status, dialog, log = format_split_summary(
        ok=2,
        fail=0,
        output_count=18,
        outdir=tmp_path / "output",
        failures=[],
    )

    assert "成功 2" in status
    assert "失败 0" in status
    assert "输出 18 张切片" in status
    assert str((tmp_path / "output").resolve()) in status
    assert "成功 2" in dialog
    assert "输出切片：18 张" in dialog
    assert "失败文件" not in dialog
    assert log == "■ 完成：成功 2，失败 0，输出 18 张切片"


def test_split_summary_lists_failures(tmp_path):
    failures = [(f"bad-{i}.jpg", f"错误 {i}") for i in range(1, 7)]

    _, dialog, log = format_split_summary(
        ok=1,
        fail=6,
        output_count=9,
        outdir=tmp_path / "output",
        failures=failures,
    )

    assert "失败文件：" in dialog
    assert "bad-1.jpg：错误 1" in dialog
    assert "bad-5.jpg：错误 5" in dialog
    assert "bad-6.jpg" not in dialog
    assert "另有 1 个失败" in dialog
    assert "失败文件：bad-1.jpg：错误 1" in log


def test_output_preview_single_image_uses_output_root(tmp_path):
    image_path = tmp_path / "grid.png"
    output_root = tmp_path / "output"

    preview = format_output_preview(
        tasks=[image_path],
        output_root=output_root,
        input_root=None,
        preserve_structure=False,
        out_mode="png",
    )

    assert "输出预览：" in preview
    assert "输入：grid.png" in preview
    assert f"目录：{output_root.resolve()}" in preview
    assert "示例：grid_r1_c1.png" in preview


def test_output_preview_batch_preserves_relative_folder(tmp_path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    image_path = input_root / "chapter-a" / "scene-01" / "grid.jpg"

    preview = format_output_preview(
        tasks=[image_path],
        output_root=output_root,
        input_root=input_root,
        preserve_structure=True,
        out_mode="keep",
    )

    assert "输入：chapter-a\\scene-01\\grid.jpg" in preview
    assert f"目录：{(output_root / 'chapter-a' / 'scene-01').resolve()}" in preview
    assert "示例：grid_r1_c1.jpg" in preview


def test_output_preview_limits_batch_examples(tmp_path):
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    tasks = [input_root / f"grid-{i}.png" for i in range(5)]

    preview = format_output_preview(
        tasks=tasks,
        output_root=output_root,
        input_root=input_root,
        preserve_structure=False,
        out_mode="webp",
        limit=3,
    )

    assert "grid-0.png" in preview
    assert "grid-2.png" in preview
    assert "grid-3.png" not in preview
    assert "... 另有 2 个输入" in preview
    assert "示例：grid-0_r1_c1.webp" in preview
