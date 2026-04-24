from pathlib import Path

from PIL import Image

from file_ops import estimate_output_count, is_dangerous_delete_target, open_folder
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
