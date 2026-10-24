"""確認打包後的執行檔帶著執行期需要的檔案。

CI 前面的關卡測的都是原始碼樹，PyInstaller 漏收 DLL 或模組不會被發現。
不啟動 GUI：CI 沒有互動桌面，視窗跑不起來不代表打包有問題。

用法：python utils/verify_bundle.py <執行檔路徑>
"""
import platform
import sys
import tempfile
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader

# 副檔名須與 utils/build.py 的 EXT_BY_SYSTEM 一致
LIB_BY_SYSTEM = {"Windows": "ai.dll", "Linux": "ai.so", "Darwin": "ai.dylib"}

# 資料檔與共享庫在 CArchive 頂層，純 Python 模組在 PYZ 內
REQUIRED_FILES = (LIB_BY_SYSTEM[platform.system()], "200w.gif",
                  "assets/fonts/NotoSansTC-Subset.ttf", "assets/fonts/OFL.txt")
REQUIRED_MODULES = ("game_state", "gomoku_ui", "theme", "pygame")


def main(exe_path):
    archive = CArchiveReader(exe_path)
    toc = [name.lower().replace("\\", "/") for name in archive.toc]

    missing = [f for f in REQUIRED_FILES if f.lower() not in toc]

    with tempfile.TemporaryDirectory() as tmp:
        pyz_path = Path(tmp) / "PYZ.pyz"
        payload = archive.extract("PYZ.pyz")
        pyz_path.write_bytes(payload if isinstance(payload, bytes) else payload[1])
        modules = set(ZlibArchiveReader(str(pyz_path)).toc)

    missing += [m for m in REQUIRED_MODULES if m not in modules]

    if missing:
        print(f"FAIL: 沒被打包進去：{', '.join(missing)}", file=sys.stderr)
        return 1

    print(f"BUNDLE OK: {len(toc)} files, {len(modules)} modules")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
