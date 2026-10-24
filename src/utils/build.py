"""跨平台編譯腳本：把 lib/ 下的 C 模組與 ai.c 編成共享庫。

輸出檔名依平台自動選副檔名（Windows: ai.dll，Linux: ai.so，macOS: ai.dylib），
放在 src/ 根目錄，與 Gomoku.py 載入的路徑一致。

用法（在 src/ 下執行）：
    python utils/build.py            # 正式編譯，-O2
    python utils/build.py --debug    # 除錯編譯，-O0 -g
"""
import argparse
import platform
import subprocess
import sys
from pathlib import Path

MODULES = [
    "zobrist.c", "pattern.c", "boardstate.c", "lines.c",
    "eval.c", "movegen.c", "vcf.c", "search.c",
]

EXT_BY_SYSTEM = {"Windows": "dll", "Linux": "so", "Darwin": "dylib"}

# gcc 未指定 -O 時等同 -O0：變數全程存回記憶體、不內聯
RELEASE_FLAGS = ["-O2"]
# 關優化並帶符號，讓除錯器的行號與變數值對得回原始碼
DEBUG_FLAGS = ["-O0", "-g"]


def main():
    parser = argparse.ArgumentParser(description="編譯 ai 共享庫")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="改用 -O0 -g 編譯，供除錯器逐行追蹤使用",
    )
    args = parser.parse_args()

    src_dir = Path(__file__).resolve().parent.parent
    lib_dir = src_dir / "lib"

    ext = EXT_BY_SYSTEM.get(platform.system())
    if ext is None:
        sys.exit(f"build: 不支援的平台：{platform.system()}")

    output = src_dir / f"ai.{ext}"
    sources = [str(lib_dir / m) for m in MODULES] + ["ai.c"]
    opt_flags = DEBUG_FLAGS if args.debug else RELEASE_FLAGS
    cmd = [
        "gcc", "-I", str(lib_dir), "-shared", "-o", str(output),
        "-fPIC", *opt_flags, *sources,
    ]

    print(" ".join(cmd))
    subprocess.run(cmd, cwd=src_dir, check=True)
    # 兩種模式寫同一個檔名，標出來避免把除錯版誤當正式版量測
    mode = "debug (-O0 -g)" if args.debug else "release (-O2)"
    print(f"build: {mode} -> {output.name}")


if __name__ == "__main__":
    main()
