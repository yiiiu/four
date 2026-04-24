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


def format_split_summary(
    ok: int,
    fail: int,
    output_count: int,
    outdir: Path,
    failures: list[tuple[str, str]],
) -> tuple[str, str, str]:
    output_dir = outdir.resolve()
    status = f"完成：成功 {ok}，失败 {fail}，输出 {output_count} 张切片。输出目录：{output_dir}"
    dialog_lines = [
        f"成功 {ok}，失败 {fail}",
        f"输出切片：{output_count} 张",
        f"输出目录：{output_dir}",
    ]
    log_lines = [f"■ 完成：成功 {ok}，失败 {fail}，输出 {output_count} 张切片"]

    if failures:
        shown = failures[:5]
        dialog_lines.extend(["", "失败文件："])
        dialog_lines.extend(f"{name}：{error}" for name, error in shown)
        if len(failures) > len(shown):
            dialog_lines.append(f"... 另有 {len(failures) - len(shown)} 个失败")
        log_lines.extend(f"失败文件：{name}：{error}" for name, error in shown)

    return status, "\n".join(dialog_lines), "\n".join(log_lines)


def format_output_preview(
    tasks: list[Path],
    output_root: Path,
    input_root: Path | None,
    preserve_structure: bool,
    out_mode: str,
    limit: int = 3,
) -> str:
    lines = ["输出预览："]
    shown = tasks[:limit]

    for image_path in shown:
        output_dir = get_output_dir_for_image(image_path, output_root, input_root, preserve_structure)
        input_label = image_path.name
        if input_root is not None:
            try:
                input_label = str(image_path.relative_to(input_root))
            except ValueError:
                input_label = image_path.name

        ext = image_path.suffix.lower()
        if out_mode == "png":
            ext = ".png"
        elif out_mode == "webp":
            ext = ".webp"
        elif ext == ".jpeg":
            ext = ".jpg"

        lines.extend([
            f"输入：{input_label}",
            f"目录：{output_dir.resolve()}",
            f"示例：{image_path.stem}_r1_c1{ext}",
        ])

    if len(tasks) > len(shown):
        lines.append(f"... 另有 {len(tasks) - len(shown)} 个输入")

    return "\n".join(lines)


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
