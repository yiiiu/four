import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image


def split_equal_grid(img: Image.Image, rows: int, cols: int):
    w, h = img.size
    tile_w = w // cols
    tile_h = h // rows

    crops = []
    for r in range(rows):
        for c in range(cols):
            left = c * tile_w
            top = r * tile_h
            right = (c + 1) * tile_w if c < cols - 1 else w
            bottom = (r + 1) * tile_h if r < rows - 1 else h
            crops.append(((r, c), img.crop((left, top, right, bottom))))
    return crops


def do_split(input_path: str, outdir: str, grid: int, out_format: str):
    in_path = Path(input_path)
    out_path = Path(outdir)
    out_path.mkdir(parents=True, exist_ok=True)

    img = Image.open(in_path)

    crops = split_equal_grid(img, grid, grid)
    base = in_path.stem

    # 选择输出格式：png（无损推荐）或 webp（lossless）或 jpg（有损，不推荐）
    fmt = out_format.lower()
    for (r, c), tile in crops:
        filename = out_path / f"{base}_r{r+1}_c{c+1}.{fmt}"

        save_kwargs = {}
        if fmt == "png":
            save_kwargs = {"optimize": False}  # 仍然无损
        elif fmt == "webp":
            save_kwargs = {"lossless": True, "quality": 100}
        elif fmt in ("jpg", "jpeg"):
            # JPG 天生有损（即使100也会有一点损失）
            save_kwargs = {"quality": 100, "subsampling": 0}

        tile.save(filename, format=fmt.upper(), **save_kwargs)

    return len(crops), str(out_path.resolve())


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("四宫格/九宫格 图片拆分工具（无损裁切）")
        self.geometry("640x260")
        self.resizable(False, False)

        self.input_var = tk.StringVar()
        self.outdir_var = tk.StringVar(value=str(Path.cwd() / "output_tiles"))
        self.grid_var = tk.IntVar(value=2)  # 默认四宫格
        self.format_var = tk.StringVar(value="png")

        self._build_ui()

    def _build_ui(self):
        pad = {"padx": 10, "pady": 8}

        # 输入图片
        row1 = ttk.Frame(self)
        row1.pack(fill="x", **pad)
        ttk.Label(row1, text="输入图片：").pack(side="left")
        ttk.Entry(row1, textvariable=self.input_var, width=60).pack(side="left", padx=6)
        ttk.Button(row1, text="选择…", command=self.pick_input).pack(side="left")

        # 输出目录
        row2 = ttk.Frame(self)
        row2.pack(fill="x", **pad)
        ttk.Label(row2, text="输出目录：").pack(side="left")
        ttk.Entry(row2, textvariable=self.outdir_var, width=60).pack(side="left", padx=6)
        ttk.Button(row2, text="选择…", command=self.pick_outdir).pack(side="left")

        # 参数
        row3 = ttk.Frame(self)
        row3.pack(fill="x", **pad)

        ttk.Label(row3, text="网格：").pack(side="left")
        ttk.Radiobutton(row3, text="四宫格 2×2", variable=self.grid_var, value=2).pack(side="left", padx=8)
        ttk.Radiobutton(row3, text="九宫格 3×3", variable=self.grid_var, value=3).pack(side="left", padx=8)

        ttk.Label(row3, text="输出格式：").pack(side="left", padx=(20, 6))
        fmt = ttk.Combobox(row3, textvariable=self.format_var, values=["png", "webp", "jpg"], width=6, state="readonly")
        fmt.pack(side="left")

        # 提示
        row4 = ttk.Frame(self)
        row4.pack(fill="x", **pad)
        tip = "提示：PNG / WEBP(lossless) 不降画质；JPG 天生有损（不推荐）。"
        ttk.Label(row4, text=tip, foreground="#555").pack(side="left")

        # 按钮
        row5 = ttk.Frame(self)
        row5.pack(fill="x", **pad)
        ttk.Button(row5, text="开始拆分", command=self.run).pack(side="left")
        ttk.Button(row5, text="打开输出目录", command=self.open_outdir).pack(side="left", padx=10)

    def pick_input(self):
        path = filedialog.askopenfilename(
            title="选择图片",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.webp *.bmp"), ("All files", "*.*")]
        )
        if path:
            self.input_var.set(path)

    def pick_outdir(self):
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.outdir_var.set(path)

    def open_outdir(self):
        outdir = self.outdir_var.get().strip()
        if outdir and Path(outdir).exists():
            os.startfile(outdir)
        else:
            messagebox.showwarning("提示", "输出目录不存在，请先选择或先拆分一次。")

    def run(self):
        input_path = self.input_var.get().strip()
        outdir = self.outdir_var.get().strip()
        grid = int(self.grid_var.get())
        out_format = self.format_var.get().strip().lower()

        if not input_path or not Path(input_path).exists():
            messagebox.showerror("错误", "请先选择有效的输入图片！")
            return
        if not outdir:
            messagebox.showerror("错误", "请设置输出目录！")
            return

        try:
            count, out_abs = do_split(input_path, outdir, grid, out_format)
            messagebox.showinfo("完成", f"✅ 已拆分 {grid}×{grid} = {count} 张\n输出目录：{out_abs}")
        except Exception as e:
            messagebox.showerror("错误", f"拆分失败：\n{e}")


if __name__ == "__main__":
    App().mainloop()
