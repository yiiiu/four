#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Grid splitter (2x2 or 3x3) with NO quality loss.
- Does not resize.
- Uses crop only.
- Saves as PNG (lossless) by default, or keeps original format if you choose.

Usage:
  python split_grid.py input.png
  python split_grid.py input.jpg --grid 3
  python split_grid.py input.png --grid 2 --outdir out --format png
  python split_grid.py input.webp --grid auto
"""

import argparse
import os
from pathlib import Path
from PIL import Image


def split_equal_grid(img: Image.Image, rows: int, cols: int):
    """Split image into equal rows x cols without resizing (crop only)."""
    w, h = img.size
    tile_w = w // cols
    tile_h = h // rows

    crops = []
    for r in range(rows):
        for c in range(cols):
            left = c * tile_w
            top = r * tile_h
            # Ensure last row/col reaches the edge to avoid 1px loss when not divisible
            right = (c + 1) * tile_w if c < cols - 1 else w
            bottom = (r + 1) * tile_h if r < rows - 1 else h
            crops.append(((r, c), img.crop((left, top, right, bottom))))
    return crops


def guess_grid(img: Image.Image) -> int:
    """
    Heuristic:
    - If width:height ratio looks closer to 2x2 layout vs 3x3, guess.
    - You can override with --grid.
    Works well for typical collage exports.
    """
    w, h = img.size
    ratio = w / h

    # Common: 2x2 often tall (like 9:16 collage), 3x3 often closer to square.
    # We'll use a simple rule:
    # - If ratio between 0.45~0.70 -> often 2x2 in portrait (like your sample 1143/2048≈0.558)
    # - If ratio between 0.80~1.25 -> often 3x3 (near square)
    if 0.45 <= ratio <= 0.70:
        return 2
    if 0.80 <= ratio <= 1.25:
        return 3

    # Fallback: pick 2 by default
    return 2


def save_tiles(crops, outdir: Path, base_name: str, out_format: str, keep_exif: bool, src_info):
    outdir.mkdir(parents=True, exist_ok=True)

    # Try to preserve EXIF if requested and supported by source
    exif_bytes = None
    if keep_exif:
        exif_bytes = src_info.get("exif", None)

    for (r, c), tile in crops:
        out_path = outdir / f"{base_name}_r{r+1}_c{c+1}.{out_format.lower()}"

        save_kwargs = {}
        # PNG is lossless; JPG is lossy; WEBP can be lossy unless lossless=True
        if out_format.lower() == "png":
            # optimize=False to avoid any unexpected processing; still lossless either way
            save_kwargs.update({"optimize": False})
        elif out_format.lower() in ("webp",):
            # If you really want lossless for webp:
            save_kwargs.update({"lossless": True, "quality": 100})
        elif out_format.lower() in ("jpg", "jpeg"):
            # JPG is inherently lossy—avoid if you want truly no quality loss
            save_kwargs.update({"quality": 100, "subsampling": 0})

        if exif_bytes is not None and out_format.lower() in ("jpg", "jpeg", "webp"):
            save_kwargs["exif"] = exif_bytes

        tile.save(out_path, format=out_format.upper(), **save_kwargs)

    return outdir


def main():
    parser = argparse.ArgumentParser(description="Split 2x2 or 3x3 grid image with no quality loss (crop only).")
    parser.add_argument("input", help="Input image path (png/jpg/webp etc.)")
    parser.add_argument("--grid", default="auto", choices=["auto", "2", "3"],
                        help="Grid size: 2 for 2x2, 3 for 3x3, auto to guess (default).")
    parser.add_argument("--outdir", default="output_tiles", help="Output directory (default: output_tiles)")
    parser.add_argument("--format", default="png",
                        help="Output format: png (lossless recommended), webp (lossless), jpg (lossy). Default: png")
    parser.add_argument("--keep-exif", action="store_true", help="Try to preserve EXIF (mostly for jpg/webp).")

    args = parser.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        raise FileNotFoundError(f"Input not found: {in_path}")

    # Load image without resizing
    img = Image.open(in_path)
    src_info = dict(img.info)  # may include exif

    # Decide grid
    if args.grid == "auto":
        g = guess_grid(img)
    else:
        g = int(args.grid)

    rows = cols = g

    crops = split_equal_grid(img, rows=rows, cols=cols)

    base_name = in_path.stem
    outdir = Path(args.outdir)

    save_tiles(
        crops=crops,
        outdir=outdir,
        base_name=base_name,
        out_format=args.format,
        keep_exif=args.keep_exif,
        src_info=src_info
    )

    print(f"Done. Split into {rows}x{cols} = {rows*cols} tiles.")
    print(f"Output folder: {outdir.resolve()}")


if __name__ == "__main__":
    main()
