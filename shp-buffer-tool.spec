# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules

datas = [('gui_config.example.yaml', '.')]
hiddenimports = []
datas += collect_data_files('shapely')
datas += collect_data_files('shapefile')
hiddenimports += collect_submodules('pandas')
hiddenimports += collect_submodules('openpyxl')


a = Analysis(
    ['/Users/jayden/Desktop/channels/run/shp_buffer_tool/gui.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='shp-buffer-tool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
app = BUNDLE(
    exe,
    name='shp-buffer-tool.app',
    icon=None,
    bundle_identifier=None,
)
