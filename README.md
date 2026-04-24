# 四宫格九宫格拆分工具 Pro

多宫格剪切工具。

本项目的正式入口是 `gui_splitter_plus.py`，PyInstaller 打包配置见 `四宫格九宫格拆分工具Pro.spec`。

## 运行

```powershell
python gui_splitter_plus.py
```

## 安装依赖

```powershell
pip install -r requirements.txt
```

## 打包

```powershell
pyinstaller 四宫格九宫格拆分工具Pro.spec
```

## 说明

- `grid_splitter_gui.py` 和 `gui_splitter.py` 是旧版本入口。
- `gui_splitter_plus_copy.py` 是实验版本，包含镜头表生成功能，当前未纳入正式打包入口。
