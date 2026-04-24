import os
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import Image, ImageTk


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".jfif"}


def is_image_file(p: Path) -> bool:
    return p.suffix.lower() in IMAGE_EXTS


def guess_grid_by_ratio(w: int, h: int) -> int:
    """
    简单稳定的启发式：
    - 2x2 拼图常见是竖长图（宽/高 ~ 0.45~0.70）
    - 3x3 拼图常见更接近方形（宽/高 ~ 0.80~1.25）
    不准就手动选 2 或 3。
    """
    ratio = w / h if h else 1.0
    if 0.45 <= ratio <= 0.70:
        return 2
    if 0.80 <= ratio <= 1.25:
        return 3
    return 2


def split_equal_grid(img: Image.Image, rows: int, cols: int, trim_remainder: bool = True):
    """
    等分裁切（只crop不resize）
    trim_remainder=True：如果宽/高不能整除，会先从四周居中裁掉余数像素，保证每格尺寸完全一致
    """
    w, h = img.size

    if trim_remainder:
        rw = w % cols
        rh = h % rows
        left_trim = rw // 2
        right_trim = rw - left_trim
        top_trim = rh // 2
        bottom_trim = rh - top_trim

        # 居中裁掉余数像素，使得宽高可被整除
        img = img.crop((left_trim, top_trim, w - right_trim, h - bottom_trim))
        w, h = img.size  # 更新尺寸

    tile_w = w // cols
    tile_h = h // rows

    crops = []
    for r in range(rows):
        for c in range(cols):
            left = c * tile_w
            top = r * tile_h
            right = left + tile_w
            bottom = top + tile_h
            crops.append(((r, c), img.crop((left, top, right, bottom))))
    return crops


def open_folder(path: str):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore
        elif sys.platform.startswith("darwin"):
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}"')
    except Exception:
        pass


def save_tile(tile: Image.Image, out_path: Path, out_mode: str, src_ext: str):
    """
    out_mode:
      - "keep": 保持原格式（用源扩展名）
      - "png": PNG无损
      - "webp": WEBP无损
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_mode == "keep":
        # 保持原格式：直接按源扩展名保存
        ext = src_ext.lower().lstrip(".")
        if ext in ("jpg", "jpeg"):
            tile.save(out_path.with_suffix("." + ext), format="JPEG", quality=100, subsampling=0)
        elif ext == "webp":
            tile.save(out_path.with_suffix(".webp"), format="WEBP", lossless=True, quality=100)
        elif ext == "png":
            tile.save(out_path.with_suffix(".png"), format="PNG", optimize=False)
        else:
            # 兜底：用 PNG
            tile.save(out_path.with_suffix(".png"), format="PNG", optimize=False)
        return

    if out_mode == "png":
        tile.save(out_path.with_suffix(".png"), format="PNG", optimize=False)
        return

    if out_mode == "webp":
        tile.save(out_path.with_suffix(".webp"), format="WEBP", lossless=True, quality=100)
        return

    # 兜底
    tile.save(out_path.with_suffix(".png"), format="PNG", optimize=False)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("四宫格/九宫格 拆分工具 Pro（无损裁切）")
        self.geometry("920x520")
        self.minsize(920, 520)

        # state
        self.input_type = tk.StringVar(value="single")  # single | folder
        self.input_path = tk.StringVar()
        self.outdir = tk.StringVar(value=str(Path.cwd() / "output_tiles"))
        self.grid_mode = tk.StringVar(value="auto")  # auto | 2 | 3
        self.out_format = tk.StringVar(value="png")  # keep | png | webp
        self.status = tk.StringVar(value="请选择图片或文件夹。")

        self._preview_imgtk = None
        self._preview_src = None  # PIL image
        self._preview_canvas_w = 420
        self._preview_canvas_h = 420

        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        left = ttk.Frame(self, padding=10)
        left.pack(side="left", fill="y")

        right = ttk.Frame(self, padding=10)
        right.pack(side="right", fill="both", expand=True)

        # Input type
        ttk.Label(left, text="输入类型").pack(anchor="w")
        row = ttk.Frame(left)
        row.pack(fill="x", pady=(4, 10))
        ttk.Radiobutton(row, text="单张图片", variable=self.input_type, value="single",
                        command=self._sync_input_ui).pack(side="left")
        ttk.Radiobutton(row, text="文件夹批量", variable=self.input_type, value="folder",
                        command=self._sync_input_ui).pack(side="left", padx=10)

        # Input picker
        ttk.Label(left, text="输入路径").pack(anchor="w")
        in_row = ttk.Frame(left)
        in_row.pack(fill="x", pady=(4, 10))
        ttk.Entry(in_row, textvariable=self.input_path, width=36).pack(side="left", fill="x", expand=True)
        ttk.Button(in_row, text="选择…", command=self.pick_input).pack(side="left", padx=(6, 0))

        # Output
        ttk.Label(left, text="输出目录").pack(anchor="w")
        out_row = ttk.Frame(left)
        out_row.pack(fill="x", pady=(4, 10))
        ttk.Entry(out_row, textvariable=self.outdir, width=36).pack(side="left", fill="x", expand=True)
        ttk.Button(out_row, text="选择…", command=self.pick_outdir).pack(side="left", padx=(6, 0))

        # Grid
        ttk.Label(left, text="网格模式").pack(anchor="w")
        gm = ttk.Frame(left)
        gm.pack(fill="x", pady=(4, 10))
        ttk.Radiobutton(gm, text="自动", variable=self.grid_mode, value="auto", command=self.refresh_preview).pack(side="left")
        ttk.Radiobutton(gm, text="2×2", variable=self.grid_mode, value="2", command=self.refresh_preview).pack(side="left", padx=10)
        ttk.Radiobutton(gm, text="3×3", variable=self.grid_mode, value="3", command=self.refresh_preview).pack(side="left")

        # Format
        ttk.Label(left, text="输出格式").pack(anchor="w")
        fr = ttk.Frame(left)
        fr.pack(fill="x", pady=(4, 10))
        fmt = ttk.Combobox(fr, textvariable=self.out_format,
                           values=["png", "webp", "keep"], state="readonly")
        fmt.pack(side="left")
        ttk.Label(fr, text="  (png/webp无损；keep保持原格式)", foreground="#555").pack(side="left")

        # Buttons
        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=(10, 6))
        ttk.Button(btns, text="开始拆分", command=self.run_split).pack(side="left")
        ttk.Button(btns, text="打开输出目录", command=lambda: open_folder(self.outdir.get())).pack(side="left", padx=8)

        # Progress + status
        self.pbar = ttk.Progressbar(left, mode="determinate", length=260)
        self.pbar.pack(fill="x", pady=(10, 4))
        ttk.Label(left, textvariable=self.status, foreground="#333", wraplength=280).pack(anchor="w")

        # Right: preview + log
        ttk.Label(right, text="预览（会叠加网格线，确认切割位置）").pack(anchor="w")
        self.canvas = tk.Canvas(right, width=self._preview_canvas_w, height=self._preview_canvas_h, bg="#f2f2f2", highlightthickness=1, highlightbackground="#ddd")
        self.canvas.pack(fill="none", pady=(6, 10), anchor="nw")

        ttk.Label(right, text="日志").pack(anchor="w")
        self.log = tk.Text(right, height=10, wrap="word")
        self.log.pack(fill="both", expand=True, pady=(6, 0))
        self._log("就绪：请选择输入。")

        self._sync_input_ui()

    def _log(self, msg: str):
        self.log.insert("end", msg + "\n")
        self.log.see("end")

    def _sync_input_ui(self):
        self.input_path.set("")
        self._preview_src = None
        self.canvas.delete("all")
        if self.input_type.get() == "single":
            self.status.set("请选择一张四宫格/九宫格图片。")
        else:
            self.status.set("请选择一个包含图片的文件夹（会批量拆分）。")
        self._log(f"切换输入类型：{self.input_type.get()}")

    # ---------- pickers ----------
    def pick_input(self):
        if self.input_type.get() == "single":
            p = filedialog.askopenfilename(
                title="选择图片",
                filetypes=[("Image files", "*.png *.jpg *.jpeg *.webp *.bmp"), ("All files", "*.*")]
            )
            if p:
                self.input_path.set(p)
                self._load_preview_from_file(p)
        else:
            p = filedialog.askdirectory(title="选择图片文件夹")
            if p:
                self.input_path.set(p)
                # 预览：取文件夹内第一张图
                folder = Path(p)
                first = next((x for x in sorted(folder.iterdir()) if x.is_file() and is_image_file(x)), None)
                if first:
                    self._load_preview_from_file(str(first))
                else:
                    self._preview_src = None
                    self.canvas.delete("all")
                    self.status.set("该文件夹内没有找到支持的图片格式。")
                    self._log("⚠️ 文件夹内未找到图片。")

    def pick_outdir(self):
        p = filedialog.askdirectory(title="选择输出目录")
        if p:
            self.outdir.set(p)

    # ---------- preview ----------
    def _load_preview_from_file(self, path: str):
        try:
            img = Image.open(path)
            self._preview_src = img.copy()
            self._preview_src.load()
            self._preview_src.info = img.info
            self._preview_src.format = img.format  # type: ignore
            self._preview_src.filename = path  # type: ignore
            self._log(f"载入预览：{path}  ({img.size[0]}x{img.size[1]})")
            self.refresh_preview()
        except Exception as e:
            self._preview_src = None
            self.canvas.delete("all")
            self.status.set(f"预览失败：{e}")
            self._log(f"❌ 预览失败：{e}")

    def refresh_preview(self):
        self.canvas.delete("all")
        if not self._preview_src:
            return

        img = self._preview_src
        w, h = img.size

        # decide grid for preview
        gm = self.grid_mode.get()
        if gm == "auto":
            g = guess_grid_by_ratio(w, h)
        else:
            g = int(gm)

        # fit to canvas (only for preview; not for output)
        scale = min(self._preview_canvas_w / w, self._preview_canvas_h / h)
        pw, ph = int(w * scale), int(h * scale)
        preview = img.resize((pw, ph), resample=Image.BICUBIC)  # 仅预览缩放，不影响输出
        self._preview_imgtk = ImageTk.PhotoImage(preview)
        self.canvas.create_image(0, 0, anchor="nw", image=self._preview_imgtk)

        # draw grid lines
        for i in range(1, g):
            x = int(pw * i / g)
            self.canvas.create_line(x, 0, x, ph, fill="#00A3FF", width=2)
        for i in range(1, g):
            y = int(ph * i / g)
            self.canvas.create_line(0, y, pw, y, fill="#00A3FF", width=2)

        self.status.set(f"预览：{w}×{h}  |  网格：{g}×{g}  |  输出：{self.out_format.get()}（无损裁切）")

    # ---------- split ----------
    def run_split(self):
        in_path = self.input_path.get().strip()
        outdir = self.outdir.get().strip()
        if not in_path:
            messagebox.showerror("错误", "请先选择输入图片或文件夹。")
            return
        if not outdir:
            messagebox.showerror("错误", "请先选择输出目录。")
            return

        # collect tasks
        tasks = []
        if self.input_type.get() == "single":
            p = Path(in_path)
            if not p.exists() or not p.is_file() or not is_image_file(p):
                messagebox.showerror("错误", "输入图片无效或格式不支持。")
                return
            tasks = [p]
        else:
            folder = Path(in_path)
            if not folder.exists() or not folder.is_dir():
                messagebox.showerror("错误", "输入文件夹无效。")
                return
            tasks = sorted([p for p in folder.rglob("*") if p.is_file() and is_image_file(p)])

            if not tasks:
                messagebox.showerror("错误", "文件夹内没有找到支持的图片。")
                return

        self.pbar["value"] = 0
        self.pbar["maximum"] = len(tasks)
        self.status.set("开始处理…")
        self._log(f"▶ 开始拆分：共 {len(tasks)} 个输入")

        # worker thread (avoid freezing UI)
        t = threading.Thread(target=self._worker_split, args=(tasks, outdir), daemon=True)
        t.start()

    def _worker_split(self, tasks, outdir):
        ok = 0
        fail = 0
        for idx, img_path in enumerate(tasks, start=1):
            try:
                with Image.open(img_path) as img:
                    img.load()
                    w, h = img.size

                    gm = self.grid_mode.get()
                    if gm == "auto":
                        g = guess_grid_by_ratio(w, h)
                    else:
                        g = int(gm)

                    crops = split_equal_grid(img, g, g)

                    base = img_path.stem
                    src_ext = img_path.suffix
                    out_mode = self.out_format.get().lower()  # png | webp | keep

                    # 输出：每张一张，不降画质（crop only + 无损格式）
                    for (r, c), tile in crops:
                        out_name = f"{base}_r{r+1}_c{c+1}"
                        out_path = Path(outdir) / out_name
                        save_tile(tile, out_path, out_mode, src_ext)

                    ok += 1
                    self._ui_progress(idx, f"✅ {img_path.name} -> {g}x{g} 完成")
            except Exception as e:
                fail += 1
                self._ui_progress(idx, f"❌ {img_path.name} 失败：{e}")

        self._ui_done(ok, fail, outdir)

    def _ui_progress(self, value, logmsg):
        def _():
            self.pbar["value"] = value
            self._log(logmsg)
        self.after(0, _)

    def _ui_done(self, ok, fail, outdir):
        def _():
            self.status.set(f"完成：成功 {ok}，失败 {fail}。输出目录：{Path(outdir).resolve()}")
            self._log(f"■ 完成：成功 {ok}，失败 {fail}")
            messagebox.showinfo("完成", f"成功 {ok}，失败 {fail}\n输出目录：{Path(outdir).resolve()}")
        self.after(0, _)


if __name__ == "__main__":
    App().mainloop()
