from pathlib import Path

from PIL import Image


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".jfif"}


def is_image_file(p: Path) -> bool:
    return p.suffix.lower() in IMAGE_EXTS


def guess_grid_by_ratio(w: int, h: int) -> int:
    ratio = w / h if h else 1.0
    if 0.45 <= ratio <= 0.70:
        return 2
    if 0.80 <= ratio <= 1.25:
        return 3
    return 2


def split_equal_grid(img: Image.Image, rows: int, cols: int):
    """
    平衡切割：使用 round(i*w/cols) 的边界，避免余数像素全堆到最后导致 1~2px 偏移。
    """
    w, h = img.size
    xs = [round(i * w / cols) for i in range(cols + 1)]
    ys = [round(i * h / rows) for i in range(rows + 1)]

    crops = []
    for r in range(rows):
        for c in range(cols):
            left, right = xs[c], xs[c + 1]
            top, bottom = ys[r], ys[r + 1]
            crops.append(((r, c), img.crop((left, top, right, bottom))))
    return crops


def make_unique_stem(outdir: Path, stem: str, ext: str) -> str:
    ext = ext.lower()
    candidate = stem
    i = 1
    while (outdir / f"{candidate}{ext}").exists():
        candidate = f"{stem}_{i:03d}"
        i += 1
    return candidate


def save_tile(tile: Image.Image, out_path_no_ext: Path, out_mode: str, src_ext: str):
    out_path_no_ext.parent.mkdir(parents=True, exist_ok=True)

    if out_mode == "keep":
        ext = src_ext.lower().lstrip(".")
        if ext in ("jpg", "jpeg"):
            tile.save(out_path_no_ext.with_suffix("." + ext), format="JPEG", quality=100, subsampling=0)
        elif ext == "webp":
            tile.save(out_path_no_ext.with_suffix(".webp"), format="WEBP", lossless=True, quality=100)
        elif ext == "png":
            tile.save(out_path_no_ext.with_suffix(".png"), format="PNG", optimize=False)
        else:
            tile.save(out_path_no_ext.with_suffix(".png"), format="PNG", optimize=False)
        return

    if out_mode == "png":
        tile.save(out_path_no_ext.with_suffix(".png"), format="PNG", optimize=False)
        return

    if out_mode == "webp":
        tile.save(out_path_no_ext.with_suffix(".webp"), format="WEBP", lossless=True, quality=100)
        return

    tile.save(out_path_no_ext.with_suffix(".png"), format="PNG", optimize=False)
