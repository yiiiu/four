import ast
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_delete_defaults_to_recycle_bin():
    source = (ROOT / "gui_splitter_plus.py").read_text(encoding="utf-8")
    assert "self.use_trash_default = tk.BooleanVar(value=True)" in source


def test_dangerous_delete_targets_are_rejected():
    module = _load_module("gui_splitter_plus", "gui_splitter_plus.py")

    assert module.is_dangerous_delete_target(Path.home()) is True
    assert module.is_dangerous_delete_target(Path(Path.home().anchor)) is True
    assert module.is_dangerous_delete_target(ROOT / "output_tiles") is False


def test_gui_splitter_does_not_pass_invalid_combobox_option():
    tree = ast.parse((ROOT / "gui_splitter.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                assert keyword.arg != "earlier"


def test_open_folder_creates_missing_directory(tmp_path):
    module = _load_module("gui_splitter_plus", "gui_splitter_plus.py")
    target = tmp_path / "missing-output"

    module.open_folder(str(target), launch=False)

    assert target.is_dir()


def test_estimate_output_count_uses_grid_mode():
    module = _load_module("gui_splitter_plus", "gui_splitter_plus.py")

    assert module.estimate_output_count(3, "2") == 12
    assert module.estimate_output_count(3, "3") == 27
    assert module.estimate_output_count(3, "auto") is None


def test_worker_split_accepts_config_snapshot():
    source = (ROOT / "gui_splitter_plus.py").read_text(encoding="utf-8")
    assert "def _worker_split(self, tasks: list[Path], outdir: str, grid_mode: str, out_mode: str):" in source
    assert "args=(tasks, outdir, grid_mode, out_mode)" in source


def test_output_format_copy_mentions_jpg_reencoding():
    source = (ROOT / "gui_splitter_plus.py").read_text(encoding="utf-8")
    assert "JPG会重新编码" in source or "JPG 会重新编码" in source
