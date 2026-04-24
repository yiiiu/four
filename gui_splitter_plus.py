import os
import sys
import threading
from pathlib import Path

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


def is_dangerous_delete_target(target_dir: Path) -> bool:
    try:
        target = target_dir.expanduser().resolve()
    except Exception:
        return True

    home = Path.home().resolve()
    anchors = {Path(anchor).resolve() for anchor in (target.anchor, home.anchor) if anchor}
    protected = {home, *anchors}
    return target in protected


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
        self.use_trash_default = tk.BooleanVar(value=True)
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

        # Root split: left controls / right preview+log
        root_paned = ttk.Panedwindow(self, orient="horizontal")
        root_paned.pack(fill="both", expand=True)

        left = ttk.Frame(root_paned, padding=8)
        right = ttk.Frame(root_paned, padding=8)

        root_paned.add(left, weight=0)
        root_paned.add(right, weight=1)

        # 左侧稍微加宽，让右侧不那么空（你也可拖拽分割条）
        left.configure(width=430)
        left.pack_propagate(False)

        # ✅ 默认把分割条往右放一点（减少右侧过宽感）
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
        ttk.Label(fmt_row, text="png/webp无损保存；keep尽量保持原格式，JPG会重新编码", foreground="#666").grid(row=0, column=1, sticky="w", padx=(10, 0))

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
        grid_mode = self.grid_mode.get()
        out_mode = self.out_format.get().lower()
        expected = estimate_output_count(len(tasks), grid_mode)
        if expected is None:
            self.status.set(f"开始处理… 共 {len(tasks)} 个输入，自动判断网格。")
        else:
            self.status.set(f"开始处理… 共 {len(tasks)} 个输入，预计输出 {expected} 张切片。")
        self._log(f"▶ 开始拆分：共 {len(tasks)} 个输入")

        t = threading.Thread(target=self._worker_split, args=(tasks, outdir, grid_mode, out_mode), daemon=True)
        t.start()

    def _worker_split(self, tasks: list[Path], outdir: str, grid_mode: str, out_mode: str):
        ok = 0
        fail = 0
        out_dir_path = Path(outdir)
        out_dir_path.mkdir(parents=True, exist_ok=True)

        for idx, img_path in enumerate(tasks, start=1):
            try:
                with Image.open(img_path) as img:
                    img.load()
                    w, h = img.size

                    g = guess_grid_by_ratio(w, h) if grid_mode == "auto" else int(grid_mode)

                    crops = split_equal_grid(img, g, g)

                    base = img_path.stem
                    src_ext = img_path.suffix
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
            if is_dangerous_delete_target(target):
                messagebox.showerror("危险目录", "为避免误删，不能在磁盘根目录或用户主目录执行删除。", parent=win)
                return
            tip = "递归" if recursive_var.get() else "当前目录"
            mode = "回收站" if use_trash_var.get() else "永久删除"
            preview = "\n".join(str(self._del_list_paths[i].name) for i in sel[:5] if 0 <= i < len(self._del_list_paths))
            if len(sel) > 5:
                preview += f"\n... 另有 {len(sel) - 5} 张"
            ok = messagebox.askyesno(
                "确认删除选中",
                f"将删除选中的 {len(sel)} 张图片（{tip} / {mode}）：\n\n{preview}\n\n目录：{target.resolve()}",
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
            if is_dangerous_delete_target(target):
                messagebox.showerror("危险目录", "为避免误删，不能在磁盘根目录或用户主目录执行删除全部。", parent=win)
                return
            if not _ensure_send2trash_if_needed():
                return

            count = len(self._del_list_paths)
            if count == 0:
                messagebox.showinfo("提示", "该目录下没有可删除的图片。", parent=win)
                return

            tip = "递归" if recursive_var.get() else "当前目录"
            mode = "回收站" if use_trash_var.get() else "永久删除"
            preview = "\n".join(p.name for p in self._del_list_paths[:5])
            if count > 5:
                preview += f"\n... 另有 {count - 5} 张"
            ok = messagebox.askyesno(
                "确认删除全部",
                f"将删除该目录下全部图片：{count} 张（{tip} / {mode}）\n\n{preview}\n\n目录：{target.resolve()}",
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


if __name__ == "__main__":
    App().mainloop()
