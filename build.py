"""一键打包脚本（跨平台，但目标主要是 Windows exe）。

用法（先 cd 到 shp_buffer_tool 目录，并激活 venv）：

    python build.py                # 默认 --onefile，单 exe
    python build.py --onedir       # 输出目录形态（启动更快，依赖以文件夹分发）

产物：

    dist/shp-buffer-tool.exe                       (--onefile，默认)
    或 dist/shp-buffer-tool/shp-buffer-tool.exe    (--onedir)

同时会复制 ``gui_config.example.yaml`` 到 dist 目录，便于直接交付。
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP_NAME = "shp-buffer-tool"
ENTRY = HERE / "gui.py"
EXAMPLE_YAML = HERE / "gui_config.example.yaml"


def run(cmd: list[str]) -> None:
    print("[CMD]", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=HERE)
    if proc.returncode != 0:
        sys.exit(proc.returncode)


def ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # type: ignore  # noqa: F401
    except ImportError:
        print("[INFO] 未检测到 PyInstaller，开始安装…", flush=True)
        run([sys.executable, "-m", "pip", "install", "pyinstaller>=6.0"])


def clean() -> None:
    for d in ("build", "dist"):
        path = HERE / d
        if path.exists():
            print(f"[INFO] 清理 {path}", flush=True)
            shutil.rmtree(path, ignore_errors=True)
    for spec in HERE.glob("*.spec"):
        try:
            spec.unlink()
        except OSError:
            pass


def build(onefile: bool, console: bool) -> None:
    sep = ";" if sys.platform.startswith("win") else ":"
    add_data = f"{EXAMPLE_YAML.name}{sep}."

    cmd: list[str] = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name",
        APP_NAME,
        "--onefile" if onefile else "--onedir",
        "--console" if console else "--windowed",
        "--add-data",
        add_data,
        # 这些 collect 是为了避免 pandas / openpyxl / shapely / pyshp 在某些
        # 环境下被遗漏；冗余但稳。
        "--collect-submodules", "pandas",
        "--collect-submodules", "openpyxl",
        "--collect-data", "shapely",
        "--collect-data", "shapefile",
        str(ENTRY),
    ]
    run(cmd)


def post_copy(onefile: bool) -> None:
    dist = HERE / "dist"
    if onefile:
        target_dir = dist
    else:
        target_dir = dist / APP_NAME
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EXAMPLE_YAML, target_dir / EXAMPLE_YAML.name)
    # 不强制创建 gui_config.yaml，让用户首次运行 exe 时自动从 example 复制


def main() -> int:
    parser = argparse.ArgumentParser(description="打包 shp_buffer_tool")
    parser.add_argument(
        "--onedir",
        action="store_true",
        help="输出目录形态（默认产出单 exe）",
    )
    parser.add_argument(
        "--debug-console",
        action="store_true",
        help="保留控制台窗口（默认 --windowed 不显示控制台，方便定位错误时再开）",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="不清理旧的 build/dist",
    )
    args = parser.parse_args()

    if not ENTRY.exists():
        print(f"[ERROR] 入口文件不存在: {ENTRY}", file=sys.stderr)
        return 1
    if not EXAMPLE_YAML.exists():
        print(f"[ERROR] 缺少 {EXAMPLE_YAML.name}", file=sys.stderr)
        return 1

    ensure_pyinstaller()
    if not args.no_clean:
        clean()
    build(onefile=not args.onedir, console=args.debug_console)
    post_copy(onefile=not args.onedir)

    print("\n[OK] 打包完成", flush=True)
    if not args.onedir:
        print(f"[OUT] {HERE / 'dist' / (APP_NAME + ('.exe' if sys.platform.startswith('win') else ''))}")
    else:
        print(f"[OUT] {HERE / 'dist' / APP_NAME}")
    print("[NEXT] 把 dist 中的 exe 与 gui_config.example.yaml 一起拷给用户即可；")
    print("       首次启动会自动在 exe 同目录生成 gui_config.yaml，按需修改后再次运行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
