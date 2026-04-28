# shp_buffer_tool

一个把 Excel 点位 (经纬度) 与缓冲区 shp 做"是否在缓冲区内"判定的 GUI 小工具，
可直接打包为 Windows 单 exe 给非技术用户使用。

> 这个目录是**自包含**的，所有命令都在 `shp_buffer_tool/` 目录下执行；
> 不依赖外面的 `run/`、`lib/` 等。

## 特性

- tkinter GUI：选 Excel + 选省份 + 一键执行；按行政编码自动匹配多份 shp 合并判定。
- 自包含：PyInstaller 直接打包不需要 `--paths ..` 之类的耦合。
- 配置外置：`gui_config.yaml` 与 exe 同目录；首次启动若不存在会自动从
  `gui_config.example.yaml` 复制一份。
- 路径友好：yaml 中相对路径以**配置文件所在目录**为基准，整套目录
  （exe + yaml + shp_input + output）拷到任何盘符都能用。
- 性能：使用 `shapely.contains_xy` 向量化点-面包含判定，万级点位毫秒级。

## 用 GitHub Actions 在云端打包 Windows exe（推荐）

不用自己装 Windows / Python 也能拿到 exe：

1. 把仓库推到 GitHub。
2. 进入仓库 → **Actions** 标签页 → 选 `Build Windows EXE` → **Run workflow**，等待跑完即可。
3. 跑完后在该次运行的 *Artifacts* 区域下载 `shp-buffer-tool-windows.zip`，里面包含：
   - `shp-buffer-tool.exe`
   - `gui_config.example.yaml`
   - 空的 `shp_input/`、`output/` 目录
   - `使用说明.txt`

如果想正式发布，给一次提交打 tag 即可自动创建 Release：

```bash
git tag v0.1.0
git push origin v0.1.0
```

workflow 会把同一个 zip 作为 Release 资产上传，普通用户在 Releases 页面直接下载就能用。

## 在 Windows 上本地打包成 exe

所有命令都在 `shp_buffer_tool/` 目录下执行：

```bat
:: 1. 进入工具目录
cd shp_buffer_tool

:: 2. 在当前目录建虚拟环境并装依赖
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt

:: 3. 一键打包（默认产出单 exe）
build_exe.bat
```

也可以直接调 `build.py`（同样在 `shp_buffer_tool/` 下）：

```bat
.venv\Scripts\python.exe build.py            :: 默认 onefile：dist\shp-buffer-tool.exe
.venv\Scripts\python.exe build.py --onedir   :: 目录形态：dist\shp-buffer-tool\shp-buffer-tool.exe
.venv\Scripts\python.exe build.py --debug-console  :: 排错时保留控制台
```

## 部署给最终用户

把以下东西打成压缩包给用户：

```
shp-buffer-tool.exe
gui_config.example.yaml
shp_input/        # 放各省 .shp 数据（按行政编码匹配）
output/           # 结果 Excel 会写到这里（不存在会自动建）
```

用户首次双击 exe 时会自动在同目录生成 `gui_config.yaml`，按需修改后再启动即可。

## 在 GUI 里能直接改什么

- shp 根目录、Excel 文件、输出目录（按钮选择，不用动 yaml）。
- Sheet（序号或名称）、经度列名、纬度列名（留空时自动识别）。
- 省份下拉（来自 yaml 的 `region.provinces`）。

## 不打包，直接源码运行

```bat
cd shp_buffer_tool
.venv\Scripts\python.exe gui.py
```

## 作为模块在代码里调用

```python
from service import load_gui_config, process_excel_with_province

cfg = load_gui_config("gui_config.yaml")
province = cfg.find_province("湖北省")
result = process_excel_with_province(
    cfg, province, "/path/to/points.xlsx",
    sheet=0,
    field_overrides={"longitude": "经度", "latitude": "纬度"},
)
print(result.output_path, result.hit_count, "/", result.total_rows)
```
