# -*- mode: python ; coding: utf-8 -*-
import platform

# 副檔名須與 utils/build.py 的 EXT_BY_SYSTEM 一致
LIB = {"Windows": "ai.dll", "Linux": "ai.so", "Darwin": "ai.dylib"}[platform.system()]
NAME = {"Windows": "Gomoku-windows", "Linux": "Gomoku-linux", "Darwin": "Gomoku-macos"}[platform.system()]

a = Analysis(
    ['Gomoku.py'],
    pathex=[],
    binaries=[(LIB, '.')],
    datas=[
        ('200w.gif', '.'),
        ('assets/fonts/NotoSansTC-Subset.ttf', 'assets/fonts'),
        ('assets/fonts/OFL.txt', 'assets/fonts'),
    ],
    hiddenimports=['gomoku_ui'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 環境裡裝了就會被 pygame 的 hook 連帶打包，執行檔大一個數量級；遊戲用不到。
    # pkg_resources 會帶進 pyi_rth_pkgres runtime hook，多一個啟動時可能失敗的環節
    excludes=['numpy', 'cv2', 'tkinter', 'PIL', 'matplotlib', 'scipy', 'pandas',
              'pkg_resources', 'setuptools'],
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
    name=NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=platform.system() != "Windows",
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    # macOS 要 .icns，給 .ico 會在打包時要求 Pillow 轉檔；目前只設 Windows
    icon='assets/icon.ico' if platform.system() == "Windows" else None,
    codesign_identity=None,   # macOS 的 ad-hoc 簽章在 release.yml 裡做
    entitlements_file=None,
)
