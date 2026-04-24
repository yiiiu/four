import os
import sys
from pathlib import Path

try:
    from send2trash import send2trash
    HAS_SEND2TRASH = True
except Exception:
    HAS_SEND2TRASH = False

from image_splitter import is_image_file


DELETE_CONFIRM_THRESHOLD = 50
DELETE_CONFIRM_TEXT = "DELETE"


def open_folder(path: str, launch: bool = True):
    try:
        target = Path(path)
        target.mkdir(parents=True, exist_ok=True)
        if not launch:
            return
        if sys.platform.startswith("win"):
            os.startfile(str(target))  # type: ignore
        elif sys.platform.startswith("darwin"):
            os.system(f'open "{target}"')
        else:
            os.system(f'xdg-open "{target}"')
    except Exception:
        pass


def estimate_output_count(input_count: int, grid_mode: str) -> int | None:
    if grid_mode in ("2", "3"):
        grid = int(grid_mode)
        return input_count * grid * grid
    return None


def needs_typed_delete_confirmation(file_count: int) -> bool:
    return file_count >= DELETE_CONFIRM_THRESHOLD


def get_output_dir_for_image(
    image_path: Path,
    output_root: Path,
    input_root: Path | None,
    preserve_structure: bool,
) -> Path:
    if not preserve_structure or input_root is None:
        return output_root

    try:
        relative_parent = image_path.parent.resolve().relative_to(input_root.resolve())
    except ValueError:
        return output_root

    return output_root / relative_parent


def is_dangerous_delete_target(target_dir: Path) -> bool:
    try:
        target = target_dir.expanduser().resolve()
    except Exception:
        return True

    home = Path.home().resolve()
    anchors = {Path(anchor).resolve() for anchor in (target.anchor, home.anchor) if anchor}
    protected = {home, *anchors}
    return target in protected


def delete_files(paths: list[Path], use_trash: bool) -> int:
    deleted = 0
    for p in paths:
        try:
            if use_trash:
                if not HAS_SEND2TRASH:
                    raise RuntimeError("未安装 send2trash")
                send2trash(str(p))
            else:
                p.unlink()
            deleted += 1
        except Exception:
            pass
    return deleted


def delete_images_in_dir(target_dir: Path, recursive: bool, use_trash: bool) -> int:
    if not target_dir.exists() or not target_dir.is_dir():
        return 0

    if recursive:
        files = [p for p in target_dir.rglob("*") if p.is_file() and is_image_file(p)]
    else:
        files = [p for p in target_dir.iterdir() if p.is_file() and is_image_file(p)]

    return delete_files(files, use_trash=use_trash)
