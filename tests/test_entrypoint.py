from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_main_entrypoint_exists_and_launches_formal_app():
    source = (ROOT / "main.py").read_text(encoding="utf-8")

    assert "from gui_splitter_plus import App" in source
    assert "App().mainloop()" in source


def test_spec_uses_main_entrypoint():
    spec = (ROOT / "四宫格九宫格拆分工具Pro.spec").read_text(encoding="utf-8")

    assert "['main.py']" in spec
    assert "['gui_splitter_plus.py']" not in spec


def test_readme_points_users_to_main_entrypoint():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "python main.py" in readme
    assert "python gui_splitter_plus.py" not in readme
