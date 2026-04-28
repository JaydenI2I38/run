"""tkinter GUI 入口。

支持源码运行 ``python -m shp_buffer_tool.gui``，也可被 PyInstaller 直接打包成
exe。配置文件 ``gui_config.yaml`` 默认放在 exe（或 ``gui.py``）旁边；首次启动
若不存在则会自动从 ``gui_config.example.yaml`` 复制一份。
"""
from __future__ import annotations

import logging
import queue
import shutil
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

# 同时支持两种运行方式：
#   1) cd shp_buffer_tool && python gui.py     （目录就是 sys.path[0]）
#   2) python -m shp_buffer_tool.gui           （作为包导入）
try:
    from service import (  # type: ignore
        GuiToolConfig,
        ProvinceItem,
        app_base_dir,
        find_matching_shp_paths,
        list_provinces,
        load_gui_config,
        process_excel_with_province,
    )
except ImportError:
    from shp_buffer_tool.service import (  # type: ignore
        GuiToolConfig,
        ProvinceItem,
        app_base_dir,
        find_matching_shp_paths,
        list_provinces,
        load_gui_config,
        process_excel_with_province,
    )


CONFIG_FILENAME = "gui_config.yaml"
EXAMPLE_FILENAME = "gui_config.example.yaml"


class TextHandler(logging.Handler):
    def __init__(self, sink_queue: queue.Queue):
        super().__init__()
        self.sink_queue = sink_queue

    def emit(self, record: logging.LogRecord) -> None:
        self.sink_queue.put(self.format(record))


# ---------------------------------------------------------------------------
# 配置文件位置：优先 exe 旁边的 gui_config.yaml；不存在则从 example 拷贝。
# ---------------------------------------------------------------------------


def _bundled_example_path() -> Path | None:
    """返回 PyInstaller 打包时随 exe 一并发布的 example yaml。"""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        p = Path(base) / EXAMPLE_FILENAME
        if p.exists():
            return p
    src = Path(__file__).resolve().parent / EXAMPLE_FILENAME
    return src if src.exists() else None


def resolve_config_path() -> Path:
    """选用配置文件路径。

    优先级：
    1. exe / gui.py 所在目录下的 ``gui_config.yaml``（不存在则尝试自动创建）。
    2. 同目录的 ``gui_config.example.yaml``。
    """
    base = app_base_dir()
    target = base / CONFIG_FILENAME
    if target.exists():
        return target

    example = base / EXAMPLE_FILENAME
    if not example.exists():
        bundled = _bundled_example_path()
        if bundled is not None:
            try:
                shutil.copy2(bundled, example)
            except OSError:
                pass

    if example.exists():
        try:
            shutil.copy2(example, target)
            return target
        except OSError:
            return example

    raise FileNotFoundError(
        f"未找到 {CONFIG_FILENAME} 或 {EXAMPLE_FILENAME}（查找目录: {base}）"
    )


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------


class App:
    def __init__(self, root: tk.Tk, config_path: Path):
        self.root = root
        self.root.title("缓冲区判定工具")
        self.root.geometry("1000x780")
        self.root.minsize(820, 640)
        self.config_path = config_path
        self.cfg: GuiToolConfig = load_gui_config(config_path)
        self.provinces: list[ProvinceItem] = list_provinces(self.cfg)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.running = False

        # 表单变量
        self.var_excel = tk.StringVar()
        self.var_province = tk.StringVar()
        self.var_shp_root = tk.StringVar(value=str(self.cfg.shp_root_dir))
        self.var_output_dir = tk.StringVar(value=str(self.cfg.output_dir))
        self.var_sheet = tk.StringVar(value="0")
        self.var_col_lng = tk.StringVar(value="")
        self.var_col_lat = tk.StringVar(value="")
        if self.provinces:
            self.var_province.set(self.provinces[0].label)

        self._setup_logging()
        self._build_ui()
        self.refresh_shp_preview()
        self._poll_log_queue()

    # ---- 基础 ----
    def _setup_logging(self) -> None:
        handler = TextHandler(self.log_queue)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                "%Y-%m-%d %H:%M:%S",
            )
        )
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        # 避免重复 handler（开发时反复创建 App）
        for h in list(root_logger.handlers):
            if isinstance(h, TextHandler):
                root_logger.removeHandler(h)
        root_logger.addHandler(handler)
        self.text_handler = handler

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)

        # --- 路径区 ---
        paths = ttk.LabelFrame(outer, text="路径")
        paths.pack(fill=tk.X)
        paths.columnconfigure(1, weight=1)

        ttk.Label(paths, text="shp 根目录").grid(row=0, column=0, sticky=tk.W, padx=8, pady=6)
        ttk.Entry(paths, textvariable=self.var_shp_root).grid(row=0, column=1, sticky=tk.EW, padx=4, pady=6)
        ttk.Button(paths, text="选择…", command=self.choose_shp_root).grid(row=0, column=2, padx=4)
        ttk.Button(paths, text="打开", command=lambda: self._open_path(self.var_shp_root.get())).grid(row=0, column=3, padx=(0, 8))

        ttk.Label(paths, text="Excel 文件").grid(row=1, column=0, sticky=tk.W, padx=8, pady=6)
        ttk.Entry(paths, textvariable=self.var_excel).grid(row=1, column=1, sticky=tk.EW, padx=4, pady=6)
        ttk.Button(paths, text="选择…", command=self.choose_excel).grid(row=1, column=2, padx=4)
        ttk.Button(paths, text="打开", command=lambda: self._open_path(self.var_excel.get())).grid(row=1, column=3, padx=(0, 8))

        ttk.Label(paths, text="输出目录").grid(row=2, column=0, sticky=tk.W, padx=8, pady=6)
        ttk.Entry(paths, textvariable=self.var_output_dir).grid(row=2, column=1, sticky=tk.EW, padx=4, pady=6)
        ttk.Button(paths, text="选择…", command=self.choose_output_dir).grid(row=2, column=2, padx=4)
        ttk.Button(paths, text="打开", command=lambda: self._open_path(self.var_output_dir.get())).grid(row=2, column=3, padx=(0, 8))

        # --- 参数区 ---
        params = ttk.LabelFrame(outer, text="参数")
        params.pack(fill=tk.X, pady=(10, 0))
        for col in (1, 3):
            params.columnconfigure(col, weight=1)

        ttk.Label(params, text="省份").grid(row=0, column=0, sticky=tk.W, padx=8, pady=6)
        province_values = [p.label for p in self.provinces]
        self.province_box = ttk.Combobox(
            params,
            textvariable=self.var_province,
            values=province_values,
            state="readonly",
            width=28,
        )
        self.province_box.grid(row=0, column=1, sticky=tk.W, padx=4, pady=6)
        self.province_box.bind("<<ComboboxSelected>>", lambda _e: self.refresh_shp_preview())
        ttk.Button(params, text="刷新 shp 匹配", command=self.refresh_shp_preview).grid(row=0, column=2, padx=8)

        ttk.Label(params, text="Sheet").grid(row=1, column=0, sticky=tk.W, padx=8, pady=6)
        ttk.Entry(params, textvariable=self.var_sheet, width=18).grid(row=1, column=1, sticky=tk.W, padx=4, pady=6)
        ttk.Label(params, text="(序号 0/1/2 或 sheet 名称)").grid(row=1, column=2, sticky=tk.W)

        ttk.Label(params, text="经度列").grid(row=2, column=0, sticky=tk.W, padx=8, pady=6)
        ttk.Entry(params, textvariable=self.var_col_lng, width=18).grid(row=2, column=1, sticky=tk.W, padx=4, pady=6)
        ttk.Label(params, text="纬度列").grid(row=2, column=2, sticky=tk.E, padx=8, pady=6)
        ttk.Entry(params, textvariable=self.var_col_lat, width=18).grid(row=2, column=3, sticky=tk.W, padx=4, pady=6)
        ttk.Label(
            params,
            text="（留空时按 longitude/lng/经度、latitude/lat/纬度 自动识别）",
            foreground="#666",
        ).grid(row=3, column=0, columnspan=4, sticky=tk.W, padx=8)

        # --- 操作 ---
        actions = ttk.Frame(outer)
        actions.pack(fill=tk.X, pady=10)
        self.run_btn = ttk.Button(actions, text="开始处理", command=self.run_task)
        self.run_btn.pack(side=tk.LEFT)
        ttk.Button(actions, text="编辑配置", command=self.open_config_file).pack(side=tk.LEFT, padx=8)
        ttk.Label(actions, text=f"配置文件：{self.config_path}", foreground="#666").pack(side=tk.LEFT, padx=8)

        self.progress = ttk.Progressbar(outer, orient="horizontal", mode="determinate", maximum=100)
        self.progress.pack(fill=tk.X)

        # --- 预览 ---
        preview_frame = ttk.LabelFrame(outer, text="当前省份匹配到的 shp")
        preview_frame.pack(fill=tk.X, pady=(10, 6))
        self.preview_summary = tk.StringVar(value="尚未匹配")
        ttk.Label(preview_frame, textvariable=self.preview_summary).pack(anchor=tk.W, padx=8, pady=(8, 4))
        self.preview_list = tk.Text(preview_frame, height=6, wrap="none")
        self.preview_list.pack(fill=tk.X, padx=8, pady=(0, 8))

        # --- 日志 ---
        ttk.Label(outer, text="日志").pack(anchor=tk.W)
        self.log_text = tk.Text(outer, height=18, wrap="word")
        self.log_text.pack(fill=tk.BOTH, expand=True)

    # ---- 事件 ----
    def choose_excel(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 Excel 文件",
            filetypes=[("Excel Files", "*.xlsx *.xls"), ("所有文件", "*.*")],
        )
        if path:
            self.var_excel.set(path)

    def choose_shp_root(self) -> None:
        path = filedialog.askdirectory(title="选择 shp 根目录")
        if path:
            self.var_shp_root.set(path)
            self.refresh_shp_preview()

    def choose_output_dir(self) -> None:
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.var_output_dir.set(path)

    def open_config_file(self) -> None:
        self._open_path(str(self.config_path))

    def _open_path(self, path: str) -> None:
        path = (path or "").strip()
        if not path:
            return
        target = Path(path).expanduser()
        try:
            if sys.platform.startswith("win"):
                import os
                os.startfile(str(target))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", str(target)])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(target)])
        except Exception as e:  # noqa: BLE001
            messagebox.showwarning("提示", f"无法打开 {target}\n{e}")

    def _selected_province(self) -> ProvinceItem:
        label = self.var_province.get().strip()
        for item in self.provinces:
            if label == item.label:
                return item
        raise ValueError("请先选择省份")

    def _apply_overrides_to_cfg(self) -> None:
        """把 GUI 上的 shp 根目录覆盖到 cfg，便于 find_matching_shp_paths 使用。"""
        shp_root = self.var_shp_root.get().strip()
        if shp_root:
            self.cfg.shp_root_dir = Path(shp_root).expanduser().resolve()

    def refresh_shp_preview(self) -> None:
        self.preview_list.delete("1.0", tk.END)
        try:
            self._apply_overrides_to_cfg()
            province = self._selected_province()
            matches = find_matching_shp_paths(self.cfg, province.code)
            self.preview_summary.set(
                f"共匹配到 {len(matches)} 个 shp（根目录：{self.cfg.shp_root_dir}）"
            )
            for path in matches:
                self.preview_list.insert(tk.END, str(path) + "\n")
        except Exception as e:  # noqa: BLE001
            self.preview_summary.set(f"匹配失败：{e}")
            self.preview_list.insert(tk.END, str(e))

    # ---- 执行 ----
    def run_task(self) -> None:
        if self.running:
            messagebox.showinfo("提示", "任务正在执行，请稍候")
            return
        excel_path = self.var_excel.get().strip()
        if not excel_path:
            messagebox.showerror("错误", "请先选择 Excel 文件")
            return
        try:
            province = self._selected_province()
        except ValueError as e:
            messagebox.showerror("错误", str(e))
            return

        self._apply_overrides_to_cfg()

        sheet_raw = self.var_sheet.get().strip() or "0"
        try:
            sheet: int | str = int(sheet_raw)
        except ValueError:
            sheet = sheet_raw

        overrides: dict[str, str] = {}
        lng = self.var_col_lng.get().strip()
        lat = self.var_col_lat.get().strip()
        if lng:
            overrides["longitude"] = lng
        if lat:
            overrides["latitude"] = lat

        output_dir = self.var_output_dir.get().strip() or str(self.cfg.output_dir)

        self.running = True
        self.run_btn.config(state=tk.DISABLED)
        self.progress["value"] = 0
        self.log_text.delete("1.0", tk.END)

        worker = threading.Thread(
            target=self._worker_run,
            args=(province, excel_path, sheet, overrides, output_dir),
            daemon=True,
        )
        worker.start()

    def _worker_run(
        self,
        province: ProvinceItem,
        excel_path: str,
        sheet: int | str,
        overrides: dict[str, str],
        output_dir: str,
    ) -> None:
        try:
            result = process_excel_with_province(
                self.cfg,
                province,
                excel_path,
                sheet=sheet,
                field_overrides=overrides or None,
                output_dir_override=output_dir or None,
                progress_callback=self._on_progress,
            )
            self.log_queue.put(f"输出文件：{result.output_path}")
            self.root.after(
                0,
                lambda: messagebox.showinfo(
                    "完成",
                    f"处理完成\n命中 {result.hit_count}/{result.total_rows}\n输出文件：{result.output_path}",
                ),
            )
        except Exception as e:  # noqa: BLE001
            log_msg = f"ERROR: {e}"
            self.log_queue.put(log_msg)
            self.root.after(0, lambda: messagebox.showerror("执行失败", str(e)))
        finally:
            self.root.after(0, self._finish_run)

    def _on_progress(self, message: str, percent: float | None) -> None:
        if percent is not None:
            self.root.after(
                0,
                lambda p=percent: self.progress.configure(value=max(0, min(100, p))),
            )
        self.log_queue.put(message)

    def _finish_run(self) -> None:
        self.running = False
        self.run_btn.config(state=tk.NORMAL)

    def _poll_log_queue(self) -> None:
        while True:
            try:
                msg = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_text.insert(tk.END, msg + "\n")
            self.log_text.see(tk.END)
        self.root.after(150, self._poll_log_queue)


def main() -> int:
    try:
        config_path = resolve_config_path()
    except FileNotFoundError as e:
        # 在 GUI 中提示，避免双击 exe 没反应
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("启动失败", str(e))
        return 1

    root = tk.Tk()
    try:
        App(root, config_path)
    except Exception as e:  # noqa: BLE001
        root.withdraw()
        messagebox.showerror("启动失败", f"加载配置失败：\n{e}")
        return 1
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
