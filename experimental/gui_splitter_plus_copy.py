import sys
import json
import requests
import threading
from pathlib import Path
import os, csv, math, re
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
from PIL import Image, ImageTk

# 可选：进回收站
try:
    from send2trash import send2trash
    HAS_SEND2TRASH = True
except Exception:
    HAS_SEND2TRASH = False


# ------------------------
# Config / Helpers
# ------------------------

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


# ------------------------
# App
# ------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("四宫格/九宫格 拆分工具 Pro（无损裁切）")
        self.geometry("1150x700")
        self.minsize(1050, 650)
        self.use_trash_default = tk.BooleanVar(value=False)
        self.color_preset = tk.StringVar(value="浅色")

        # state
        self.input_type = tk.StringVar(value="single")  # single | folder
        self.input_path = tk.StringVar()
        self.outdir = tk.StringVar(value=str(Path.cwd() / "output_tiles"))
        self.grid_mode = tk.StringVar(value="auto")  # auto | 2 | 3
        self.out_format = tk.StringVar(value="png")  # png | webp | keep
        self.delete_recursive = tk.BooleanVar(value=False)

        # ✅ 网格线可调
        self.grid_line_width = tk.IntVar(value=2)
        self.grid_line_color = tk.StringVar(value="#00A3FF")

        self.status = tk.StringVar(value="请选择图片或文件夹。")

        # preview data (main)
        self._preview_src: Image.Image | None = None

        # delete panel caches
        self._del_list_paths: list[Path] = []

        self._build_ui()
        self.apply_theme()
        self._log("就绪：请选择输入。")
        self._sync_input_ui()

    # ---------------- UI Layout ----------------

    def _build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        self.configure(padx=8, pady=8)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)

        tab_split = ttk.Frame(nb)  # 你现有拆分工具UI放这里
        tab_shots = ttk.Frame(nb)  # 新增镜头表生成UI放这里

        nb.add(tab_split, text="拼图拆分")
        nb.add(tab_shots, text="镜头表生成")

        ShotTableFrame(tab_shots).pack(fill="both", expand=True)
        self._build_split_tab(tab_split)

        # Root split: left controls / right preview+log
    def _build_split_tab(self, parent):
        # Root split: left controls / right preview+log
        root_paned = ttk.Panedwindow(parent, orient="horizontal")
        root_paned.pack(fill="both", expand=True)

        left = ttk.Frame(root_paned, padding=8)
        right = ttk.Frame(root_paned, padding=8)

        root_paned.add(left, weight=0)
        root_paned.add(right, weight=1)

        left.configure(width=430)
        left.pack_propagate(False)

        def _set_sash():
            try:
                root_paned.sashpos(0, 450)
            except Exception:
                pass
        self.after(50, _set_sash)

        # ✅ 只初始化一次 sash，之后不再改（防止和用户拖动抢控制权）
        self._sash_inited = False

        def _init_sash_once(event=None):
            if self._sash_inited:
                return
            self._sash_inited = True
            self.update_idletasks()
            root_paned.sashpos(0, 450)

        # 窗口第一次显示时初始化
        self.bind("<Map>", _init_sash_once)

        # ---- Left: Groups ----
        lf_in = ttk.LabelFrame(left, text="输入", padding=10, style="Card.TLabelframe")
        lf_in.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        lf_in.columnconfigure(0, weight=1)

        trow = ttk.Frame(lf_in)
        trow.grid(row=0, column=0, sticky="ew")
        ttk.Radiobutton(trow, text="单张图片", variable=self.input_type, value="single",
                        command=self._sync_input_ui).pack(side="left")
        ttk.Radiobutton(trow, text="文件夹批量", variable=self.input_type, value="folder",
                        command=self._sync_input_ui).pack(side="left", padx=12)

        ttk.Label(lf_in, text="输入路径").grid(row=1, column=0, sticky="w", pady=(10, 4))
        in_row = ttk.Frame(lf_in)
        in_row.grid(row=2, column=0, sticky="ew")
        in_row.columnconfigure(0, weight=1)
        ttk.Entry(in_row, textvariable=self.input_path).grid(row=0, column=0, sticky="ew")
        ttk.Button(in_row, text="选择…", command=self.pick_input, width=10).grid(row=0, column=1, padx=(8, 0))

        lf_out = ttk.LabelFrame(left, text="输出", padding=10,style="Card.TLabelframe")
        lf_out.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        lf_out.columnconfigure(0, weight=1)

        ttk.Label(lf_out, text="输出目录").grid(row=0, column=0, sticky="w", pady=(0, 4))
        out_row = ttk.Frame(lf_out)
        out_row.grid(row=1, column=0, sticky="ew")
        out_row.columnconfigure(0, weight=1)
        ttk.Entry(out_row, textvariable=self.outdir).grid(row=0, column=0, sticky="ew")
        ttk.Button(out_row, text="选择…", command=self.pick_outdir, width=10).grid(row=0, column=1, padx=(8, 0))

        lf_opts = ttk.LabelFrame(left, text="参数", padding=10)
        lf_opts.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        lf_opts.columnconfigure(0, weight=1)

        ttk.Label(lf_opts, text="网格模式").grid(row=0, column=0, sticky="w")
        gm = ttk.Frame(lf_opts)
        gm.grid(row=1, column=0, sticky="w", pady=(4, 10))
        ttk.Radiobutton(gm, text="自动", variable=self.grid_mode, value="auto",
                        command=self.refresh_preview).pack(side="left")
        ttk.Radiobutton(gm, text="2×2", variable=self.grid_mode, value="2",
                        command=self.refresh_preview).pack(side="left", padx=12)
        ttk.Radiobutton(gm, text="3×3", variable=self.grid_mode, value="3",
                        command=self.refresh_preview).pack(side="left")

        # ✅ 网格线控制：线宽 + 颜色
        line_row = ttk.Frame(lf_opts)
        line_row.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(line_row, text="网格线").pack(side="left")

        sp = ttk.Spinbox(line_row, from_=1, to=12, textvariable=self.grid_line_width, width=4,
                         command=self.refresh_preview)
        sp.pack(side="left", padx=(10, 6))
        ttk.Label(line_row, text="线宽").pack(side="left")
        #主题颜色
        theme_row = ttk.Frame(lf_opts)
        theme_row.grid(row=999, column=0, sticky="ew", pady=(10, 0))  # row号确保不和你已有的冲突
        ttk.Label(theme_row, text="界面主题").pack(side="left")

        theme_cb = ttk.Combobox(theme_row, textvariable=self.color_preset,
                                values=list(self.THEME_PRESETS.keys()),
                                width=10, state="readonly")
        theme_cb.pack(side="left", padx=10)

        # 切换立即生效
        self.color_preset.trace_add("write", lambda *_: self.apply_theme())

        # 颜色按钮用 tk.Button 方便显示背景色
        self._color_btn = tk.Button(line_row, text="颜色", width=6,
                                    bg=self.grid_line_color.get(), fg="white",
                                    command=self.pick_grid_color)
        self._color_btn.pack(side="left", padx=(12, 0))

        ttk.Label(lf_opts, text="输出格式").grid(row=3, column=0, sticky="w")
        fmt_row = ttk.Frame(lf_opts)
        fmt_row.grid(row=4, column=0, sticky="ew", pady=(4, 0))
        fmt_row.columnconfigure(1, weight=1)
        fmt = ttk.Combobox(fmt_row, textvariable=self.out_format, values=["png", "webp", "keep"],
                           width=8, state="readonly")
        fmt.grid(row=0, column=0, sticky="w")
        ttk.Label(fmt_row, text="png/webp无损；keep保持原格式", foreground="#666").grid(row=0, column=1, sticky="w", padx=(10, 0))

        lf_actions = ttk.LabelFrame(left, text="操作", padding=10)
        lf_actions.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        lf_actions.columnconfigure(0, weight=1)

        btn_row = ttk.Frame(lf_actions)
        btn_row.grid(row=0, column=0, sticky="ew")
        ttk.Button(btn_row, text="开始拆分", command=self.run_split).pack(side="left")
        ttk.Button(btn_row, text="打开输出目录", command=lambda: open_folder(self.outdir.get())).pack(side="left", padx=8)

        del_row = ttk.Frame(lf_actions)
        del_row.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(del_row, text="删除图片（可预览/多选）", command=self.delete_images_ui).pack(side="left")
        ttk.Checkbutton(del_row, text="递归包含子目录", variable=self.delete_recursive).pack(side="left", padx=10)

        # progress + status
        self.pbar = ttk.Progressbar(left, mode="determinate",style="Accent.Horizontal.TProgressbar")
        self.pbar.grid(row=4, column=0, sticky="ew", pady=(6, 6))
        ttk.Label(left, textvariable=self.status, foreground="#333", wraplength=410).grid(row=5, column=0, sticky="w")

        left.columnconfigure(0, weight=1)

        # ---- Right: Preview + Log (vertical paned) ----
        right_paned = ttk.Panedwindow(right, orient="vertical")
        right_paned.pack(fill="both", expand=True)

        prev_frame = ttk.LabelFrame(right_paned, text="预览（叠加网格线）", padding=8)
        log_frame = ttk.LabelFrame(right_paned, text="日志", padding=8)

        right_paned.add(prev_frame, weight=3)
        right_paned.add(log_frame, weight=1)

        prev_frame.rowconfigure(0, weight=1)
        prev_frame.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(prev_frame, bg="#f7f7f7", highlightthickness=1, highlightbackground="#ddd")
        self.canvas.grid(row=0, column=0, sticky="nsew")

        # 自适应重绘
        self.canvas.bind("<Configure>", lambda e: self.refresh_preview())

        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)
        yscroll = ttk.Scrollbar(log_frame, orient="vertical")
        yscroll.grid(row=0, column=1, sticky="ns")
        self.log = tk.Text(log_frame, wrap="word", yscrollcommand=yscroll.set)
        self.log.grid(row=0, column=0, sticky="nsew")
        yscroll.config(command=self.log.yview)

    THEME_PRESETS = {
        "浅色": {
            "bg": "#F4F4F1",
            "panel": "#ECEAE6",
            "fg": "#111111",
            "muted": "#666666",
            "border": "#C9C6C0",
            "canvas": "#F7F7F7",
            "text_bg": "#FFFFFF",
            "text_fg": "#111111",
            "select_bg": "#CDE8FF",
            "select_fg": "#111111",
            "btn_fg": "#111111",
            "accent": "#2D8CFF",
            "accent2": "#1E6FD9",
            "btn_bg": "#ECEAE6",
            "btn_hover": "#DAD7D0",
            "btn_pressed": "#CFCBC3",
        },
        "深色": {
            "bg": "#1E1F22",
            "panel": "#2B2D31",
            "fg": "#E6E6E6",
            "muted": "#A0A0A0",
            "border": "#3A3D44",
            "canvas": "#1F2125",
            "text_bg": "#1F2125",
            "text_fg": "#E6E6E6",
            "select_bg": "#355A7A",
            "select_fg": "#FFFFFF",
            "btn_bg": "#2B2D31",
            "btn_hover": "#3A3D44",
            "btn_pressed": "#222429",
            "btn_fg": "#E6E6E6",
            "accent": "#4EA1FF",
            "accent2": "#2F7ED6",
        },
        "护眼灰": {
            "bg": "#2B2B2B",
            "panel": "#333333",
            "fg": "#EDEDED",
            "muted": "#B5B5B5",
            "border": "#444444",
            "canvas": "#2C2C2C",
            "text_bg": "#2C2C2C",
            "text_fg": "#EDEDED",
            "select_bg": "#4A6A88",
            "select_fg": "#FFFFFF",
            "btn_bg": "#333333",
            "btn_hover": "#444444",
            "btn_pressed": "#2A2A2A",
            "btn_fg": "#EDEDED",
            "accent": "#5AA6FF",
            "accent2": "#3C86D6",
        },
    }

    def apply_theme(self):
        """统一换肤：ttk + 所有窗口内的 Canvas/Text/Listbox 等"""
        pal = self.THEME_PRESETS.get(self.color_preset.get(), self.THEME_PRESETS["浅色"])


        # 1) 统一用 clam 主题（跨平台最稳，颜色更可控）
        style = ttk.Style()
        preset = self.color_preset.get()
        try:
            if preset in ("深色", "护眼灰"):
                style.theme_use("clam")
            else:
                # 浅色可以仍然用 clam（最一致），或保留你原本的
                style.theme_use("clam")
        except Exception:
            pass

        # ✅ 进度条：槽/条都跟随主题
        pstyle = "Accent.Horizontal.TProgressbar"

        style.configure(
            pstyle,
            troughcolor=pal["panel"],  # 槽背景（深色下不要亮）
            background=pal.get("accent", pal["select_bg"]),  # 进度条颜色
            bordercolor=pal["border"],
            lightcolor=pal["border"],
            darkcolor=pal["border"],
        )

        # 有些环境下需要明确 layout（让 trough + bar 生效）
        try:
            style.layout(
                pstyle,
                [("Horizontal.Progressbar.trough",
                  {"children": [("Horizontal.Progressbar.pbar", {"side": "left", "sticky": "ns"})],
                   "sticky": "nswe"})]
            )
        except Exception:
            pass

        # 2) ttk 全局样式
        self.configure(bg=pal["bg"])

        style.configure(".", background=pal["bg"], foreground=pal["fg"])
        style.configure("TFrame", background=pal["bg"])
        style.configure("TLabel", background=pal["bg"], foreground=pal["fg"])

        style.configure("TLabelframe", background=pal["panel"], bordercolor=pal["border"])
        style.configure("TLabelframe.Label", background=pal["panel"], foreground=pal["fg"])

        hover_bg = pal.get("hover_bg", pal.get("btn_hover", pal["panel"]))
        press_bg = pal.get("press_bg", pal.get("btn_pressed", pal["panel"]))

        style.configure(
            "TButton",
            padding=(12, 7),
            background=pal["btn_bg"],
            foreground=pal["btn_fg"],
            relief="raised",
            bordercolor=pal["border"],
            lightcolor=pal["border"],
            darkcolor=pal["border"],
        )
        style.map(
            "TButton",
            background=[
                ("disabled", pal["panel"]),
                ("pressed", pal["btn_pressed"]),
                ("active", pal["btn_hover"]),  # hover
                ("!active", pal["btn_bg"]),
            ],
            foreground=[
                ("disabled", pal["muted"]),
                ("!disabled", pal["btn_fg"]),
            ],
            relief=[
                ("pressed", "sunken"),
                ("!pressed", "raised"),
            ],
            bordercolor=[
                ("active", pal.get("accent", pal["border"])),
                ("pressed", pal.get("accent2", pal.get("accent", pal["border"]))),
                ("!active", pal["border"]),
            ],
        )
        style.configure("TEntry",
                        fieldbackground=pal["text_bg"],
                        foreground=pal["text_fg"],
                        insertcolor=pal["text_fg"],
                        bordercolor=pal["border"],
                        lightcolor=pal["border"],
                        darkcolor=pal["border"])
        style.map("TEntry",
                  fieldbackground=[("disabled", pal["panel"]), ("readonly", pal["panel"]),
                                   ("!disabled", pal["text_bg"])],
                  foreground=[("disabled", pal["muted"]), ("!disabled", pal["text_fg"])],
                  bordercolor=[("focus", pal["select_bg"]), ("!focus", pal["border"])])
        # Combobox（下拉框）
        style.configure("TCombobox",
                        fieldbackground=pal["text_bg"],
                        foreground=pal["text_fg"],
                        background=pal["panel"],
                        arrowcolor=pal["text_fg"],
                        bordercolor=pal["border"],
                        lightcolor=pal["border"],
                        darkcolor=pal["border"])

        style.map("TCombobox",
                  fieldbackground=[("readonly", pal["text_bg"]), ("disabled", pal["panel"])],
                  foreground=[("readonly", pal["text_fg"]), ("disabled", pal["muted"])],
                  selectbackground=[("readonly", pal["select_bg"])],
                  selectforeground=[("readonly", pal["select_fg"])],
                  bordercolor=[("focus", pal["select_bg"]), ("!focus", pal["border"])])

        # ✅ Spinbox（线宽输入）跟随主题
        style.configure(
            "TSpinbox",
            fieldbackground=pal["text_bg"],
            foreground=pal["text_fg"],
            background=pal["panel"],
            arrowcolor=pal["text_fg"],
            bordercolor=pal["border"],
            lightcolor=pal["border"],
            darkcolor=pal["border"],
        )

        style.map(
            "TSpinbox",
            fieldbackground=[
                ("disabled", pal["panel"]),
                ("readonly", pal["panel"]),
                ("!disabled", pal["text_bg"])
            ],
            foreground=[
                ("disabled", pal["muted"]),
                ("!disabled", pal["text_fg"])
            ],
            bordercolor=[
                ("focus", pal.get("accent", pal["select_bg"])),
                ("!focus", pal["border"])
            ],
        )

        # ✅ 单选框（hover 不再变白）
        style.configure("TRadiobutton",
                        background=pal["bg"],
                        foreground=pal["fg"])

        style.map("TRadiobutton",
                  background=[
                      ("disabled", pal["bg"]),
                      ("pressed", press_bg),
                      ("active", hover_bg),
                      ("!active", pal["bg"]),
                  ],
                  foreground=[
                      ("disabled", pal["muted"]),
                      ("!disabled", pal["fg"]),
                  ])

        # ✅ 复选框（顺手一起处理）
        style.configure("TCheckbutton",
                        background=pal["bg"],
                        foreground=pal["fg"])

        style.map("TCheckbutton",
                  background=[
                      ("disabled", pal["bg"]),
                      ("pressed", press_bg),
                      ("active", hover_bg),
                      ("!active", pal["bg"]),
                  ],
                  foreground=[
                      ("disabled", pal["muted"]),
                      ("!disabled", pal["fg"]),
                  ])
        style.configure("TProgressbar", background=pal["select_bg"])

        style.configure("Info.TLabel", background=pal["panel"], foreground=pal["fg"])
        style.configure("InfoMuted.TLabel", background=pal["panel"], foreground=pal["muted"])

        # （可选）让输入/输出/参数/操作更像卡片：只要你给 LabelFrame 传 style="Card.TLabelframe"
        style.configure("Card.TLabelframe", background=pal["panel"], bordercolor=pal["border"])
        style.configure("Card.TLabelframe.Label", background=pal["panel"], foreground=pal["fg"])

        # 3) 统一应用到主窗口 + 所有弹窗
        self._apply_theme_recursive(self, pal)
        for w in self.winfo_children():
            if isinstance(w, tk.Toplevel):
                self._apply_theme_recursive(w, pal)

    def _apply_theme_recursive(self, widget, pal):
        """递归应用到 tk 控件（Canvas/Text/Listbox/Button 等）"""
        self._apply_theme_to_widget(widget, pal)
        for child in widget.winfo_children():
            self._apply_theme_recursive(child, pal)

    def _apply_theme_to_widget(self, widget, pal):
        cls = widget.winfo_class()

        # ttk.Entry/ttk.Combobox 某些主题不完全吃 style，这里做兜底
        if isinstance(widget, ttk.Entry):
            try:
                widget.configure(foreground=pal["text_fg"])
            except Exception:
                pass

        if widget.winfo_class() in ("Label", "Message"):
            try:
                widget.configure(bg=pal["panel"], fg=pal["fg"])
            except Exception:
                pass

        if cls == "Text":
            widget.configure(
                bg=pal["text_bg"], fg=pal["text_fg"],
                insertbackground=pal["text_fg"],
                highlightbackground=pal["border"],
                highlightcolor=pal["select_bg"]
            )
        # 顶层 / 普通 tk 容器
        if isinstance(widget, (tk.Tk, tk.Toplevel, tk.Frame)):
            try:
                widget.configure(bg=pal["bg"])
            except Exception:
                pass

        # Canvas 预览区
        if cls == "Canvas":
            try:
                widget.configure(bg=pal["canvas"], highlightbackground=pal["border"])
            except Exception:
                pass

        # Text 日志
        if cls == "Text":
            try:
                widget.configure(bg=pal["text_bg"], fg=pal["text_fg"],
                                 insertbackground=pal["text_fg"])
            except Exception:
                pass

        # Listbox 图片列表
        if cls == "Listbox":
            try:
                widget.configure(bg=pal["text_bg"], fg=pal["text_fg"],
                                 selectbackground=pal["select_bg"],
                                 selectforeground=pal["select_fg"],
                                 highlightbackground=pal["border"])
            except Exception:
                pass

        # 你用到的 tk.Button（比如网格线颜色按钮）
        if cls == "Button":
            try:
                widget.configure(bg=pal["btn_bg"], fg=pal["btn_fg"],
                                 activebackground=pal["btn_hover"],
                                 activeforeground = pal["btn_fg"])
            except Exception:
                pass

    # ---------------- Common: adaptive preview + overlay ----------------

    def _draw_corner_badge(self, canvas: tk.Canvas, text: str):
        """右下角角标（无透明，使用浅色底）"""
        cw = max(1, canvas.winfo_width())
        ch = max(1, canvas.winfo_height())

        pad = 10
        # 先创建文本获取 bbox
        tid = canvas.create_text(cw - pad, ch - pad, anchor="se", text=text, fill="#111",
                                 font=("Segoe UI", 10))
        bbox = canvas.bbox(tid)
        if bbox:
            x1, y1, x2, y2 = bbox
            rid = canvas.create_rectangle(x1 - 6, y1 - 4, x2 + 6, y2 + 4,
                                          fill="#f0f0f0", outline="#cfcfcf")
            canvas.tag_lower(rid, tid)

    def _canvas_draw_fit(self, canvas: tk.Canvas, pil_img: Image.Image | None,
                         grid: int | None = None,
                         line_color: str = "#00A3FF", line_width: int = 2,
                         show_badge: bool = True):
        """
        在 canvas 中自适应预览 pil_img（保持比例contain+居中），可选叠加网格线（2或3）。
        并显示角标：缩放比例/原图尺寸/显示尺寸
        """
        canvas.delete("all")
        if pil_img is None:
            return

        cw = max(1, canvas.winfo_width())
        ch = max(1, canvas.winfo_height())

        iw, ih = pil_img.size
        if iw <= 0 or ih <= 0:
            return

        pad = 10
        cw2 = max(1, cw - pad * 2)
        ch2 = max(1, ch - pad * 2)

        scale = min(cw2 / iw, ch2 / ih)
        pw = max(1, int(iw * scale))
        ph = max(1, int(ih * scale))

        preview = pil_img.resize((pw, ph), resample=Image.LANCZOS)

        imgtk = ImageTk.PhotoImage(preview)
        canvas._imgtk_ref = imgtk  # 防止被回收

        x0 = (cw - pw) // 2
        y0 = (ch - ph) // 2
        canvas.create_image(x0, y0, anchor="nw", image=imgtk)

        if grid in (2, 3):
            for i in range(1, grid):
                x = x0 + int(pw * i / grid)
                canvas.create_line(x, y0, x, y0 + ph, fill=line_color, width=line_width)
            for i in range(1, grid):
                y = y0 + int(ph * i / grid)
                canvas.create_line(x0, y, x0 + pw, y, fill=line_color, width=line_width)

        if show_badge:
            pct = int(round(scale * 100))
            badge = f"{pct}%  |  原图 {iw}×{ih}  |  显示 {pw}×{ph}"
            self._draw_corner_badge(canvas, badge)

    # ---------------- Logging ----------------

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
            self.status.set("请选择一个包含图片的文件夹（会递归批量拆分）。")
        self._log(f"切换输入类型：{self.input_type.get()}")

    # ---------------- Pickers ----------------

    def pick_grid_color(self):
        c = colorchooser.askcolor(title="选择网格线颜色", initialcolor=self.grid_line_color.get())
        if c and c[1]:
            self.grid_line_color.set(c[1])
            try:
                self._color_btn.configure(bg=c[1])
            except Exception:
                pass
            self.refresh_preview()

    def pick_input(self):
        if self.input_type.get() == "single":
            p = filedialog.askopenfilename(
                title="选择图片",
                filetypes=[("Image files", "*.png *.jpg *.jpeg *.webp *.bmp *.jfif"), ("All files", "*.*")]
            )
            if p:
                self.input_path.set(p)
                self._load_preview_from_file(p)
        else:
            p = filedialog.askdirectory(title="选择图片文件夹")
            if p:
                self.input_path.set(p)
                folder = Path(p)
                first = next((x for x in sorted(folder.rglob("*")) if x.is_file() and is_image_file(x)), None)
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

    def _load_preview_from_file(self, path: str):
        try:
            with Image.open(path) as img:
                img.load()
                self._preview_src = img.copy()
            self._log(f"载入预览：{path}  ({self._preview_src.size[0]}x{self._preview_src.size[1]})")
            self.refresh_preview()
        except Exception as e:
            self._preview_src = None
            self.canvas.delete("all")
            self.status.set(f"预览失败：{e}")
            self._log(f"❌ 预览失败：{e}")

    # ---------------- Preview ----------------

    def refresh_preview(self):
        if not self._preview_src:
            self.canvas.delete("all")
            return

        img = self._preview_src
        w, h = img.size

        gm = self.grid_mode.get()
        g = guess_grid_by_ratio(w, h) if gm == "auto" else int(gm)

        # 使用可调线宽/颜色
        self._canvas_draw_fit(
            self.canvas,
            img,
            grid=g,
            line_color=self.grid_line_color.get(),
            line_width=int(self.grid_line_width.get()),
            show_badge=True
        )

        self.status.set(f"预览：{w}×{h} | 网格：{g}×{g} | 输出：{self.out_format.get()}（无损裁切）")

    # ---------------- Split ----------------

    def run_split(self):
        in_path = self.input_path.get().strip()
        outdir = self.outdir.get().strip()

        if not in_path:
            messagebox.showerror("错误", "请先选择输入图片或文件夹。")
            return
        if not outdir:
            messagebox.showerror("错误", "请先选择输出目录。")
            return

        tasks: list[Path] = []
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

        t = threading.Thread(target=self._worker_split, args=(tasks, outdir), daemon=True)
        t.start()

    def _worker_split(self, tasks: list[Path], outdir: str):
        ok = 0
        fail = 0
        out_dir_path = Path(outdir)
        out_dir_path.mkdir(parents=True, exist_ok=True)

        for idx, img_path in enumerate(tasks, start=1):
            try:
                with Image.open(img_path) as img:
                    img.load()
                    w, h = img.size

                    gm = self.grid_mode.get()
                    g = guess_grid_by_ratio(w, h) if gm == "auto" else int(gm)

                    crops = split_equal_grid(img, g, g)

                    base = img_path.stem
                    src_ext = img_path.suffix
                    out_mode = self.out_format.get().lower()

                    for (r, c), tile in crops:
                        raw_stem = f"{base}_r{r+1}_c{c+1}"

                        if out_mode == "keep":
                            ext = src_ext.lower()
                            if ext == ".jpeg":
                                ext = ".jpg"
                        elif out_mode == "png":
                            ext = ".png"
                        else:
                            ext = ".webp"

                        unique_stem = make_unique_stem(out_dir_path, raw_stem, ext)
                        save_tile(tile, out_dir_path / unique_stem, out_mode, src_ext)

                ok += 1
                self._ui_progress(idx, f"✅ {img_path.name} -> {g}x{g} 完成")
            except Exception as e:
                fail += 1
                self._ui_progress(idx, f"❌ {img_path.name} 失败：{e}")

        self._ui_done(ok, fail, outdir)

    def _ui_progress(self, value: int, logmsg: str):
        def _():
            self.pbar["value"] = value
            self._log(logmsg)
        self.after(0, _)

    def _ui_done(self, ok: int, fail: int, outdir: str):
        def _():
            self.status.set(f"完成：成功 {ok}，失败 {fail}。输出目录：{Path(outdir).resolve()}")
            self._log(f"■ 完成：成功 {ok}，失败 {fail}")
            messagebox.showinfo("完成", f"成功 {ok}，失败 {fail}\n输出目录：{Path(outdir).resolve()}")
        self.after(0, _)

    # ---------------- Delete Panel (A: list left, preview right) ----------------

    def delete_images_ui(self):
        win = tk.Toplevel(self)
        win.title("删除图片（列表左 / 预览右）")
        win.geometry("1080x620")
        win.minsize(980, 560)

        dir_var = tk.StringVar(value=self.outdir.get().strip() or str(Path.cwd()))
        recursive_var = tk.BooleanVar(value=bool(self.delete_recursive.get()))
        use_trash_var = self.use_trash_default  # ✅ 默认进回收站更安全

        self._del_list_paths = []

        top = ttk.Frame(win, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="目标目录：").pack(side="left")
        ent = ttk.Entry(top, textvariable=dir_var)
        ent.pack(side="left", fill="x", expand=True, padx=(6, 6))

        def pick_dir():
            p = filedialog.askdirectory(title="选择要删除图片的目录", initialdir=dir_var.get())
            if p:
                dir_var.set(p)
                refresh_list()

        ttk.Button(top, text="选择…", command=pick_dir, width=10).pack(side="left")

        ttk.Checkbutton(top, text="递归包含子目录", variable=recursive_var,
                        command=lambda: refresh_list()).pack(side="left", padx=10)

        trash_cb = ttk.Checkbutton(top, text="进回收站（更安全）", variable=use_trash_var)
        trash_cb.pack(side="left", padx=10)

        ttk.Button(top, text="刷新", command=lambda: refresh_list(), width=8).pack(side="left", padx=(6, 0))

        if use_trash_var.get() and not HAS_SEND2TRASH:
            self._log("[删除面板] ⚠️ 未检测到 send2trash：请 pip install send2trash，否则无法进回收站。")

        mid = ttk.Frame(win, padding=10)
        mid.pack(fill="both", expand=True)
        mid.columnconfigure(0, weight=3)
        mid.columnconfigure(1, weight=2)
        mid.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(mid, text="图片列表（支持多选：Ctrl/Shift）", padding=8)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        list_frame = ttk.Frame(left)
        list_frame.grid(row=0, column=0, sticky="nsew")

        yscroll = ttk.Scrollbar(list_frame, orient="vertical")
        yscroll.pack(side="right", fill="y")

        lb = tk.Listbox(list_frame, selectmode="extended", yscrollcommand=yscroll.set)
        lb.pack(side="left", fill="both", expand=True)
        yscroll.config(command=lb.yview)

        right = ttk.LabelFrame(mid, text="预览", padding=8)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        canvas = tk.Canvas(right, bg="#f7f7f7", highlightthickness=1, highlightbackground="#ddd")
        canvas.grid(row=0, column=0, sticky="nsew")

        info_var = tk.StringVar(value="未选择图片")
        info_label = ttk.Label(right, textvariable=info_var, style="InfoMuted.TLabel", wraplength=360, justify="left")
        info_label.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        def log(msg: str):
            self._log(f"[删除面板] {msg}")

        def render_empty_hint():
            canvas.delete("all")
            cw = max(1, canvas.winfo_width())
            ch = max(1, canvas.winfo_height())
            canvas.create_text(cw // 2, ch // 2, text="请选择左侧图片以预览", fill="#888", font=("Segoe UI", 11))
            info_var.set("未选择图片")

        def refresh_list():
            target = Path(dir_var.get().strip())
            lb.delete(0, "end")
            self._del_list_paths = []
            render_empty_hint()
            self.apply_theme()
            if not target.exists() or not target.is_dir():
                log("目录无效")
                return

            if recursive_var.get():
                files = [p for p in target.rglob("*") if p.is_file() and is_image_file(p)]
            else:
                files = [p for p in target.iterdir() if p.is_file() and is_image_file(p)]

            files = sorted(files, key=lambda x: str(x).lower())
            self._del_list_paths = files

            for p in files:
                show = str(p.relative_to(target)) if recursive_var.get() else p.name
                lb.insert("end", show)

            log(f"刷新列表：找到 {len(files)} 张图片")

        def show_preview(event=None):
            sel = lb.curselection()
            if not sel:
                render_empty_hint()
                return

            idx = sel[0]
            if idx < 0 or idx >= len(self._del_list_paths):
                render_empty_hint()
                return

            p = self._del_list_paths[idx]
            try:
                with Image.open(p) as im:
                    im.load()
                    w, h = im.size
                    preview_img = im.copy()

                # ✅ 自适应居中显示 + 角标
                self._canvas_draw_fit(canvas, preview_img, grid=None, show_badge=True)

                info_var.set(
                    f"文件：{p.name}\n"
                    f"尺寸：{w} × {h}\n"
                    f"路径：{p.parent}"
                )
            except Exception as e:
                canvas.delete("all")
                info_var.set(f"预览失败：{e}")

        # 预览自适应
        canvas.bind("<Configure>", lambda e: show_preview())
        lb.bind("<<ListboxSelect>>", show_preview)

        bottom = ttk.Frame(win, padding=10)
        bottom.pack(fill="x")

        def select_all():
            lb.select_set(0, "end")
            show_preview()

        def clear_sel():
            lb.selection_clear(0, "end")
            render_empty_hint()

        def _ensure_send2trash_if_needed():
            if use_trash_var.get() and not HAS_SEND2TRASH:
                messagebox.showerror(
                    "缺少依赖",
                    "当前选择“进回收站”，但未安装 send2trash。\n\n请执行：pip install send2trash",
                    parent=win
                )
                return False
            return True

        def delete_selected():
            sel = list(lb.curselection())
            if not sel:
                messagebox.showwarning("提示", "请先在列表中选择要删除的图片。", parent=win)
                return
            if not _ensure_send2trash_if_needed():
                return

            target = Path(dir_var.get().strip())
            tip = "递归" if recursive_var.get() else "当前目录"
            mode = "回收站" if use_trash_var.get() else "永久删除"
            ok = messagebox.askyesno(
                "确认删除选中",
                f"将删除选中的 {len(sel)} 张图片（{tip} / {mode}）：\n\n{target.resolve()}",
                parent=win
            )
            if not ok:
                return

            paths = [self._del_list_paths[i] for i in sel if 0 <= i < len(self._del_list_paths)]
            deleted = delete_files(paths, use_trash=use_trash_var.get())
            log(f"删除选中：{deleted} 张（{mode}）")
            refresh_list()

        def delete_all():
            target = Path(dir_var.get().strip())
            if not target.exists() or not target.is_dir():
                messagebox.showerror("错误", "目录无效。", parent=win)
                return
            if not _ensure_send2trash_if_needed():
                return

            count = len(self._del_list_paths)
            if count == 0:
                messagebox.showinfo("提示", "该目录下没有可删除的图片。", parent=win)
                return

            tip = "递归" if recursive_var.get() else "当前目录"
            mode = "回收站" if use_trash_var.get() else "永久删除"
            ok = messagebox.askyesno(
                "确认删除全部",
                f"将删除该目录下全部图片：{count} 张（{tip} / {mode}）\n\n{target.resolve()}",
                parent=win
            )
            if not ok:
                return

            deleted = delete_images_in_dir(target, recursive_var.get(), use_trash=use_trash_var.get())
            log(f"删除全部：{deleted} 张（{mode}）")
            refresh_list()

        ttk.Button(bottom, text="全选", command=select_all, width=10).pack(side="left")
        ttk.Button(bottom, text="清空选择", command=clear_sel, width=10).pack(side="left", padx=8)

        right_btns = ttk.Frame(bottom)
        right_btns.pack(side="right")
        ttk.Button(right_btns, text="删除选中", command=delete_selected, width=12).pack(side="left", padx=8)
        ttk.Button(right_btns, text="删除全部", command=delete_all, width=12).pack(side="left")

        refresh_list()


NEG_DEFAULT = "低质量,模糊,畸形手,重复脸,错位五官,文字水印,logo,马赛克,噪点"

PLATFORM_PRESETS = {
    "短视频通用(竖屏9:16)": dict(aspect="9:16", resolution="1080x1920",
                          duration_sec=60, avg_shot_sec=2.3, hook_sec=3,
                          hit_every_sec=12, export_fps=30),
    "快节奏(强爽)": dict(aspect="9:16", resolution="1080x1920",
                     duration_sec=60, avg_shot_sec=1.9, hook_sec=3,
                     hit_every_sec=10, export_fps=30),
    "甜宠氛围(慢一点)": dict(aspect="9:16", resolution="1080x1920",
                        duration_sec=60, avg_shot_sec=2.7, hook_sec=3,
                        hit_every_sec=15, export_fps=30),
    "横版(16:9)": dict(aspect="16:9", resolution="1920x1080",
                   duration_sec=120, avg_shot_sec=3.0, hook_sec=5,
                   hit_every_sec=20, export_fps=30),
    "自定义": None
}

def _calc_shot_count(duration_sec: float, avg_shot_sec: float) -> int:
    if avg_shot_sec <= 0:
        return 0
    n = int(round(duration_sec / avg_shot_sec))
    return max(16, min(80, n))

def _slug_ep(num: int) -> str:
    return f"EP{num:02d}"

def _slug_sc(num: int) -> str:
    return f"SC{num:02d}"

def _slug_sh(num: int) -> str:
    return f"SH{num:03d}"

def _pick_loc_from_text(text: str) -> str:
    # 很轻量的地点推断，不准也不影响生产：用户可改
    if any(k in text for k in ["电梯", "电梯口"]): return "电梯/电梯口"
    if any(k in text for k in ["走廊", "过道"]): return "公司走廊"
    if any(k in text for k in ["会议", "开会"]): return "办公室会议室"
    if any(k in text for k in ["车", "车内"]): return "车内"
    if any(k in text for k in ["家", "卧室", "客厅"]): return "家中"
    return "办公室/会议室"

def generate_shots(story: str, heroine_card: str, hero_card: str, cfg: dict, ep_num=1, sc_num=1):
    aspect = cfg["aspect"]
    duration = float(cfg["duration_sec"])
    avg = float(cfg["avg_shot_sec"])
    hit_every = float(cfg["hit_every_sec"])

    n = _calc_shot_count(duration, avg)
    loc = _pick_loc_from_text(story)

    # 固定节奏骨架（强爽强宠）
    beats = []
    beats += [
        dict(type="字幕钩子", shot="中景", cam="静帧呼吸", expr="震惊/被羞辱", act="被甩锅/被指责", dialog="（大字幕钩子：她被当众背锅）", bgm="紧张"),
        dict(type="对白", shot="近景", cam="轻推近", expr="嘲讽", act="指责女主", dialog="“这锅她背！”", bgm="紧张"),
        dict(type="特写", shot="特写", cam="静帧呼吸", expr="忍耐/倔强", act="攥紧手/眼神不服", dialog="", bgm="紧张"),
        dict(type="转场", shot="中景", cam="轻推近", expr="冷", act="男主推门入场", dialog="", bgm="压迫"),
        dict(type="对白", shot="近景", cam="静帧呼吸", expr="冰冷", act="扫视全场", dialog="“谁给你的胆子？”", bgm="压迫"),
        dict(type="动作", shot="中景", cam="右移", expr="强宠", act="站到女主身前护短", dialog="", bgm="爽点"),
        dict(type="对白", shot="近景", cam="轻推近", expr="冷笑", act="宣布反转", dialog="“她是项目负责人。”", bgm="反转"),
        dict(type="反应", shot="中景", cam="轻微左右移", expr="慌", act="众人愣住/同事脸白", dialog="", bgm="爽点"),
        dict(type="对白", shot="特写", cam="静帧呼吸", expr="冷", act="逼视对方", dialog="“现在，道歉。”", bgm="压迫"),
        dict(type="动作", shot="近景", cam="轻推近", expr="爽", act="证据/通告落桌", dialog="", bgm="爽点"),
        dict(type="反应", shot="特写", cam="静帧呼吸", expr="崩溃", act="对方哑口无言", dialog="", bgm="爽点"),
        dict(type="强宠", shot="近景", cam="轻推近", expr="宠溺", act="男主贴近耳语", dialog="“委屈了？”", bgm="甜"),
        dict(type="反应", shot="特写", cam="静帧呼吸", expr="脸红/嘴硬", act="别开视线", dialog="“我没事。”", bgm="甜"),
        dict(type="动作", shot="中景", cam="左移", expr="强势", act="牵走/扣住手腕", dialog="", bgm="甜"),
        dict(type="对白", shot="近景", cam="静帧呼吸", expr="认真", act="停下看她", dialog="“以后，没人敢欺负你。”", bgm="甜"),
        dict(type="结尾钩子", shot="特写", cam="轻推近", expr="危险又宠", act="挡住去路", dialog="“跟我走。”", bgm="钩子"),
    ]

    # 为了凑够 n 个镜头：在中间插“爽点/反应/甜宠小动作”填充
    fillers = [
        dict(type="反应", shot="近景", cam="静帧呼吸", expr="震惊", act="女主抬眼", dialog="", bgm="紧张"),
        dict(type="动作", shot="近景", cam="轻推近", expr="压迫", act="男主手指敲桌", dialog="", bgm="压迫"),
        dict(type="对白", shot="近景", cam="轻推近", expr="嘴硬", act="对方狡辩", dialog="“我只是误会…”", bgm="紧张"),
        dict(type="强宠", shot="特写", cam="静帧呼吸", expr="克制温柔", act="递外套/挡镜头", dialog="", bgm="甜"),
        dict(type="爽点", shot="特写", cam="静帧呼吸", expr="", act="撤职/通告提示", dialog="（字幕：撤职/道歉）", bgm="爽点"),
    ]

    # 组装：头/尾固定，中间用 fillers 扩展
    head = beats[:8]
    tail = beats[8:]  # 包含逼道歉、强宠、结尾钩子
    mid_needed = max(0, n - (len(head) + len(tail)))
    mid = []
    for i in range(mid_needed):
        mid.append(fillers[i % len(fillers)])

    seq = head + mid + tail

    # 按 hit_every_sec 把“爽点/强宠”尽量均匀分布（轻微调整：把某些 filler 替换为爽点）
    # 这里不做复杂时间线，只做比例替换，保证观感更稳定
    hit_slots = max(1, int(duration // hit_every))
    for k in range(hit_slots):
        idx = int((k + 1) * (len(seq) / (hit_slots + 1)))
        if 0 <= idx < len(seq):
            seq[idx] = dict(type="爽点", shot="近景", cam="轻推近", expr="强势", act="当众打脸/宣布处理", dialog="“按规矩处理。”", bgm="爽点")

    ep = _slug_ep(ep_num)
    sc = _slug_sc(sc_num)

    rows = []
    for i, s in enumerate(seq, start=1):
        sh = _slug_sh(i)
        sec = round(duration / len(seq), 2)  # 平均分配时长，用户可改
        char = "男主+女主" if "宠" in s["type"] or "护短" in s.get("act","") else ("男主" if "男主" in s.get("act","") else "女主/众人")

        prompt_img = (
            f"竖屏{aspect}，{loc}，二次元漫画风，高质感，人物清晰，细腻线稿与柔和阴影，电影级光影，构图明确。"
            f"女主：{heroine_card.strip()}。男主：{hero_card.strip()}。"
            f"画面：{s['act']}，表情：{s.get('expr','')}，景别：{s['shot']}。"
            f"不要任何文字水印或logo。"
        )
        prompt_vid = s.get("cam", "静帧呼吸")

        rows.append({
            "ep": ep, "sc": sc, "sh": sh, "sec": sec,
            "type": s["type"], "loc": loc, "char": char,
            "shot": s["shot"], "cam": s["cam"],
            "expr": s.get("expr", ""), "act": s["act"],
            "dialog": s.get("dialog", ""),
            "sfx": s.get("sfx", ""),
            "bgm": s.get("bgm", ""),
            "prompt_img": prompt_img,
            "prompt_vid": prompt_vid,
            "neg": NEG_DEFAULT,
            "asset_out": f"{ep}_{sc}_{sh}.png"
        })

    return rows

class ShotTableFrame(ttk.Frame):
    def __init__(self, master, app=None, **kwargs):
        super().__init__(master, **kwargs)
        self.app = app  # 用于复用主题（可选）
        self._build()

    def _build(self):
        self.columnconfigure(0, weight=1)

        self.platform_var = tk.StringVar(value="短视频通用(竖屏9:16)")
        self.duration_var = tk.DoubleVar(value=60.0)   # ✅默认60s
        self.avgshot_var  = tk.DoubleVar(value=2.3)
        self.ep_var = tk.IntVar(value=1)
        self.sc_var = tk.IntVar(value=1)
        self.outdir_var = tk.StringVar(value=os.path.join(os.getcwd(), "shots_out"))

        top = ttk.LabelFrame(self, text="平台与输出", padding=10)
        top.grid(row=0, column=0, sticky="ew")
        for c in range(8): top.columnconfigure(c, weight=0)
        top.columnconfigure(7, weight=1)

        ttk.Label(top, text="平台预设").grid(row=0, column=0, sticky="w")
        cb = ttk.Combobox(top, textvariable=self.platform_var,
                          values=list(PLATFORM_PRESETS.keys()), state="readonly", width=22)
        cb.grid(row=0, column=1, sticky="w", padx=(8, 18))
        cb.bind("<<ComboboxSelected>>", lambda e: self._apply_preset())

        ttk.Label(top, text="EP").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(top, from_=1, to=999, textvariable=self.ep_var, width=6).grid(row=0, column=3, sticky="w", padx=(6, 18))
        ttk.Label(top, text="SC").grid(row=0, column=4, sticky="w")
        ttk.Spinbox(top, from_=1, to=999, textvariable=self.sc_var, width=6).grid(row=0, column=5, sticky="w", padx=(6, 18))

        ttk.Label(top, text="总时长(s)").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Spinbox(top, from_=15, to=300, increment=5, textvariable=self.duration_var, width=10).grid(row=1, column=1, sticky="w", padx=(8, 18), pady=(8, 0))
        ttk.Label(top, text="平均镜头(s)").grid(row=1, column=2, sticky="w", pady=(8, 0))
        ttk.Spinbox(top, from_=1.2, to=6.0, increment=0.1, textvariable=self.avgshot_var, width=10).grid(row=1, column=3, sticky="w", padx=(6, 18), pady=(8, 0))

        ttk.Label(top, text="输出目录").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ent_out = ttk.Entry(top, textvariable=self.outdir_var)
        ent_out.grid(row=2, column=1, columnspan=6, sticky="ew", padx=(8, 8), pady=(8, 0))
        ttk.Button(top, text="选择", command=self._pick_outdir).grid(row=2, column=7, sticky="e", pady=(8, 0))

        mid = ttk.Frame(self)
        mid.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        mid.columnconfigure(0, weight=1)
        mid.columnconfigure(1, weight=1)
        mid.rowconfigure(1, weight=1)

        # ---------------- LLM 配置（可选） ----------------
        llm = ttk.LabelFrame(self, text="LLM生成（可选）", padding=10)
        llm.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        llm.columnconfigure(5, weight=1)

        self.llm_enabled = tk.BooleanVar(value=False)

        self.llm_base_url_var = tk.StringVar(value="https://api.openai.com/v1")
        self.llm_model_var = tk.StringVar(value="gpt-4.1-mini")
        self.llm_key_var = tk.StringVar(value="")
        self.llm_temp_var = tk.DoubleVar(value=0.4)

        ttk.Checkbutton(llm, text="启用LLM生成分镜（替代模板）", variable=self.llm_enabled) \
            .grid(row=0, column=0, columnspan=6, sticky="w")

        ttk.Label(llm, text="Base URL").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(llm, textvariable=self.llm_base_url_var, width=42) \
            .grid(row=1, column=1, columnspan=3, sticky="ew", padx=(8, 10), pady=(8, 0))

        ttk.Label(llm, text="Model").grid(row=1, column=4, sticky="w", pady=(8, 0))
        ttk.Entry(llm, textvariable=self.llm_model_var, width=18) \
            .grid(row=1, column=5, sticky="ew", pady=(8, 0))

        ttk.Label(llm, text="API Key").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(llm, textvariable=self.llm_key_var, show="*", width=42) \
            .grid(row=2, column=1, columnspan=3, sticky="ew", padx=(8, 10), pady=(8, 0))

        ttk.Label(llm, text="温度").grid(row=2, column=4, sticky="w", pady=(8, 0))
        ttk.Spinbox(llm, from_=0.0, to=1.0, increment=0.1, textvariable=self.llm_temp_var, width=8) \
            .grid(row=2, column=5, sticky="w", pady=(8, 0))

        self.btn_test_llm = ttk.Button(llm, text="测试连接", command=self._test_llm)
        self.btn_test_llm.grid(row=3, column=0, sticky="w", pady=(10, 0))

        # 让“生成”按钮对象可控制（下面 bottom 里会复用）
        self.btn_gen = None

        lf_story = ttk.LabelFrame(mid, text="一句梗概/分段剧情（必填）", padding=10)
        lf_story.grid(row=0, column=0, columnspan=2, sticky="ew")
        lf_story.columnconfigure(0, weight=1)

        self.story_txt = tk.Text(lf_story, height=5, wrap="word")
        self.story_txt.grid(row=0, column=0, sticky="ew")

        lf_role1 = ttk.LabelFrame(mid, text="女主角色卡（每次可编辑）", padding=10)
        lf_role2 = ttk.LabelFrame(mid, text="男主角色卡（每次可编辑）", padding=10)
        lf_role1.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        lf_role2.grid(row=1, column=1, sticky="nsew", padx=(6, 0))
        lf_role1.rowconfigure(0, weight=1); lf_role2.rowconfigure(0, weight=1)
        lf_role1.columnconfigure(0, weight=1); lf_role2.columnconfigure(0, weight=1)

        self.heroine_txt = tk.Text(lf_role1, height=10, wrap="word")
        self.hero_txt = tk.Text(lf_role2, height=10, wrap="word")
        self.heroine_txt.grid(row=0, column=0, sticky="nsew")
        self.hero_txt.grid(row=0, column=0, sticky="nsew")

        # 默认角色卡（用户每次都可以改）
        self.heroine_txt.insert("1.0", "清冷职场系，黑发低马尾，浅灰西装，淡妆，眼神倔强，气质克制")
        self.hero_txt.insert("1.0", "冷峻霸总，黑发短碎，深蓝西装白衬衫黑领带，气场强，眼神压迫但护短")

        bottom = ttk.Frame(self)
        bottom.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        bottom.columnconfigure(2, weight=1)

        self.btn_gen = ttk.Button(bottom, text="生成镜头表CSV", command=self._gen_csv)
        self.btn_gen.grid(row=0, column=0, sticky="w")
        ttk.Button(bottom, text="打开输出目录", command=self._open_out).grid(row=0, column=1, sticky="w", padx=8)

        self.status_var = tk.StringVar(value="就绪：填写梗概后点击生成。")
        ttk.Label(bottom, textvariable=self.status_var).grid(row=0, column=2, sticky="w", padx=(12, 0))

        self._apply_preset()  # 初始化一次

    def _pick_outdir(self):
        d = filedialog.askdirectory(title="选择输出目录")
        if d:
            self.outdir_var.set(d)

    def _open_out(self):
        path = self.outdir_var.get().strip()
        if not path:
            return
        os.makedirs(path, exist_ok=True)
        try:
            os.startfile(path)
        except Exception as e:
            messagebox.showerror("打开失败", str(e))

    def _apply_preset(self):
        name = self.platform_var.get()
        preset = PLATFORM_PRESETS.get(name)
        if not preset:
            return
        # ✅ 默认60s（预设里就是60）；用户也可手动改
        self.duration_var.set(float(preset["duration_sec"]))
        self.avgshot_var.set(float(preset["avg_shot_sec"]))

    def _gen_csv(self):
        """分发器：根据 LLM 开关选择生成方式"""
        if self.llm_enabled.get():
            self._gen_csv_llm_async()
        else:
            self._gen_csv_template()

    def _get_cfg(self) -> dict:
        """获取当前配置（平台预设 + 用户覆盖）"""
        preset_name = self.platform_var.get()
        cfg = PLATFORM_PRESETS.get(preset_name) or dict(
            aspect="9:16", resolution="1080x1920",
            duration_sec=float(self.duration_var.get()),
            avg_shot_sec=float(self.avgshot_var.get()),
            hook_sec=3, hit_every_sec=12, export_fps=30
        )
        cfg = dict(cfg)
        cfg["duration_sec"] = float(self.duration_var.get())
        cfg["avg_shot_sec"] = float(self.avgshot_var.get())
        return cfg

    def _gen_csv_template(self):
        """模板生成镜头表（原 _gen_csv 内容）"""
        story = self.story_txt.get("1.0", "end").strip()
        if not story:
            messagebox.showwarning("缺少内容", "请先填写一句梗概或分段剧情。")
            return

        cfg = self._get_cfg()

        heroine_card = self.heroine_txt.get("1.0", "end").strip()
        hero_card = self.hero_txt.get("1.0", "end").strip()

        rows = generate_shots(story, heroine_card, hero_card, cfg, ep_num=int(self.ep_var.get()), sc_num=int(self.sc_var.get()))

        outdir = self.outdir_var.get().strip()
        os.makedirs(outdir, exist_ok=True)

        ep = _slug_ep(int(self.ep_var.get()))
        sc = _slug_sc(int(self.sc_var.get()))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = os.path.join(outdir, f"shots_{ep}_{sc}_{ts}.csv")

        headers = ["ep","sc","sh","sec","type","loc","char","shot","cam","expr","act","dialog","sfx","bgm","prompt_img","prompt_vid","neg","asset_out"]
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=headers)
            w.writeheader()
            for r in rows:
                w.writerow(r)

        self.status_var.set(f"已生成：{os.path.basename(csv_path)}（{len(rows)}镜头）")
        messagebox.showinfo("完成", f"镜头表已生成：\n{csv_path}\n\n镜头数：{len(rows)}")

    # ================== LLM 生成相关方法 ==================

    def _strip_code_fence(self, s: str) -> str:
        s = (s or "").strip()
        if s.startswith("```"):
            # 去掉 ```json ... ```
            s = s.strip("`")
            # 可能还有 json 标记行
            s = s.replace("json\n", "", 1)
        return s.strip()

    def _call_openai_compatible(self, base_url: str, api_key: str, model: str, messages: list,
                               temperature: float = 0.4, max_tokens: int = 3500, timeout: int = 90) -> str:
        base_url = base_url.rstrip("/")
        url = f"{base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        r = requests.post(url, headers=headers, json=payload, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]

    def _build_llm_messages(self, story: str, heroine_card: str, hero_card: str, cfg: dict) -> list:
        aspect = cfg["aspect"]
        total_sec = float(cfg["duration_sec"])
        avg = float(cfg["avg_shot_sec"])
        hook = float(cfg.get("hook_sec", 3))
        hit = float(cfg.get("hit_every_sec", 12))

        sys = (
            "你是短剧漫剧分镜导演，擅长女频强爽强宠。"
            "你必须只输出严格 JSON，不要输出任何 Markdown/解释/多余文字。"
            "输出必须能被 json.loads 直接解析。"
        )

        # 要求 LLM 输出 JSON（稳定）
        user = f"""
题材：女频强爽强宠（强爽强宠，节奏紧凑，前{hook:.0f}秒强钩子）
平台参数：
- aspect: {aspect}
- total_sec: {total_sec}
- avg_shot_sec: {avg}
- hook_sec: {hook}
- hit_every_sec: {hit}

角色卡：
女主：{heroine_card}
男主：{hero_card}

剧情梗概（原文）：
{story}

硬性要求：
1) 镜头数 = round(total_sec / avg_shot_sec)，每个镜头 sec 合理（总和≈total_sec）
2) hook_sec 内必须出现强钩子（背锅/羞辱/对立）+ 明确冲突
3) 每 hit_every_sec 秒必须出现一次爽点/强宠点（护短/打脸/强势带走/贴耳低语）
4) 每条 shot 必须包含字段：
   sec,type,loc,char,shot,cam,expr,act,dialog,sfx,bgm,prompt_img,prompt_vid
5) prompt_img：二次元漫画风、人物清晰高质感、构图明确、光影高级、不要文字水印logo
6) prompt_vid：只写镜头运动：轻推近/轻推远/左移/右移/静帧呼吸/微摇镜
7) 不要提及"AI/模型/提示词"等字眼；不要输出任何 markdown

输出 JSON 格式（必须完全一致）：
{{
  "shots":[
    {{
      "sec": 2.3,
      "type": "对白",
      "loc": "办公室",
      "char": "男主+女主",
      "shot": "近景",
      "cam": "轻推近",
      "expr": "冷",
      "act": "男主护短站到她身前",
      "dialog": "谁给你的胆子？",
      "sfx": "",
      "bgm": "压迫",
      "prompt_img": "...",
      "prompt_vid": "轻推近"
    }}
  ]
}}
""".strip()

        return [{"role": "system", "content": sys}, {"role": "user", "content": user}]

    def _normalize_llm_shots_to_rows(self, shots: list, cfg: dict, ep_num: int, sc_num: int) -> list[dict]:
        """
        将 LLM 返回的 shots -> CSV rows，并补齐 ep/sc/sh/neg/asset_out
        """
        total_sec = float(cfg["duration_sec"])
        ep = _slug_ep(ep_num)
        sc = _slug_sc(sc_num)

        # 1) 提取 sec
        secs = []
        for s in shots:
            try:
                secs.append(float(s.get("sec", 0)))
            except Exception:
                secs.append(0.0)

        # 2) 如果 sec 总和偏差大，按比例缩放到 total_sec（可选但很实用）
        sum_sec = sum(secs) if secs else 0.0
        scale = 1.0
        if sum_sec > 0 and abs(sum_sec - total_sec) / total_sec > 0.12:
            scale = total_sec / sum_sec

        rows = []
        for i, s in enumerate(shots, start=1):
            sh = _slug_sh(i)
            sec = float(s.get("sec", 0) or 0) * scale
            row = {
                "ep": ep,
                "sc": sc,
                "sh": sh,
                "sec": round(sec, 2),
                "type": s.get("type", ""),
                "loc": s.get("loc", ""),
                "char": s.get("char", ""),
                "shot": s.get("shot", ""),
                "cam": s.get("cam", ""),
                "expr": s.get("expr", ""),
                "act": s.get("act", ""),
                "dialog": s.get("dialog", ""),
                "sfx": s.get("sfx", ""),
                "bgm": s.get("bgm", ""),
                "prompt_img": s.get("prompt_img", ""),
                "prompt_vid": s.get("prompt_vid", ""),
                "neg": NEG_DEFAULT,
                "asset_out": f"{ep}_{sc}_{sh}.png",
            }
            rows.append(row)

        return rows

    def _write_rows_to_csv(self, rows: list[dict], outdir: str, ep_num: int, sc_num: int) -> str:
        os.makedirs(outdir, exist_ok=True)
        ep = _slug_ep(ep_num)
        sc = _slug_sc(sc_num)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = os.path.join(outdir, f"shots_{ep}_{sc}_{ts}.csv")

        headers = ["ep","sc","sh","sec","type","loc","char","shot","cam","expr","act","dialog","sfx","bgm","prompt_img","prompt_vid","neg","asset_out"]
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=headers)
            w.writeheader()
            for r in rows:
                w.writerow(r)
        return csv_path

    def _gen_csv_llm_async(self):
        story = self.story_txt.get("1.0", "end").strip()
        if not story:
            messagebox.showwarning("缺少内容", "请先填写一句梗概或分段剧情。")
            return

        base_url = self.llm_base_url_var.get().strip()
        api_key = self.llm_key_var.get().strip()
        model = self.llm_model_var.get().strip()
        temperature = float(self.llm_temp_var.get())

        if not (base_url and api_key and model):
            messagebox.showwarning("缺少配置", "请填写 Base URL / Model / API Key。")
            return

        cfg = self._get_cfg()
        heroine_card = self.heroine_txt.get("1.0", "end").strip()
        hero_card = self.hero_txt.get("1.0", "end").strip()
        ep_num = int(self.ep_var.get())
        sc_num = int(self.sc_var.get())
        outdir = self.outdir_var.get().strip()

        # UI 状态
        self.status_var.set("LLM 生成中…")
        if self.btn_gen:
            self.btn_gen.configure(state="disabled")
        self.btn_test_llm.configure(state="disabled")

        def worker():
            try:
                messages = self._build_llm_messages(story, heroine_card, hero_card, cfg)
                content = self._call_openai_compatible(base_url, api_key, model, messages, temperature=temperature)
                content = self._strip_code_fence(content)
                data = json.loads(content)
                shots = data.get("shots") or []
                if not isinstance(shots, list) or len(shots) == 0:
                    raise ValueError("LLM 返回的 JSON 里 shots 为空或格式不正确。")

                rows = self._normalize_llm_shots_to_rows(shots, cfg, ep_num, sc_num)
                csv_path = self._write_rows_to_csv(rows, outdir, ep_num, sc_num)

                self.after(0, lambda: self._on_llm_done(ok=True, csv_path=csv_path, n=len(rows)))
            except Exception as e:
                self.after(0, lambda: self._on_llm_done(ok=False, err=str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_llm_done(self, ok: bool, csv_path: str = "", n: int = 0, err: str = ""):
        if self.btn_gen:
            self.btn_gen.configure(state="normal")
        self.btn_test_llm.configure(state="normal")

        if ok:
            self.status_var.set(f"已生成：{os.path.basename(csv_path)}（{n}镜头）")
            messagebox.showinfo("完成", f"镜头表已生成：\n{csv_path}\n\n镜头数：{n}")
        else:
            self.status_var.set("LLM 生成失败（可切回模板生成）")
            messagebox.showerror("LLM 生成失败", err)

    def _test_llm(self):
        base_url = self.llm_base_url_var.get().strip()
        api_key = self.llm_key_var.get().strip()
        model = self.llm_model_var.get().strip()

        if not (base_url and api_key and model):
            messagebox.showwarning("缺少配置", "请填写 Base URL / Model / API Key。")
            return

        self.status_var.set("测试连接中…")
        self.btn_test_llm.configure(state="disabled")

        def worker():
            try:
                messages = [
                    {"role": "system", "content": "只输出严格 JSON，不要多余文字。"},
                    {"role": "user", "content": "{\"ok\":true}"}
                ]
                content = self._call_openai_compatible(base_url, api_key, model, messages, temperature=0.0, max_tokens=50, timeout=30)
                content = self._strip_code_fence(content)
                obj = json.loads(content)
                if obj.get("ok") is True:
                    self.after(0, lambda: self._on_test_done(True, "测试成功：LLM 配置可用。"))
                else:
                    self.after(0, lambda: self._on_test_done(False, f"返回非预期：{content[:200]}"))
            except Exception as e:
                self.after(0, lambda: self._on_test_done(False, str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_test_done(self, ok: bool, msg: str):
        self.btn_test_llm.configure(state="normal")
        self.status_var.set("就绪：填写梗概后点击生成。")
        if ok:
            messagebox.showinfo("测试连接", msg)
        else:
            messagebox.showerror("测试连接失败", msg)

if __name__ == "__main__":
    App().mainloop()
