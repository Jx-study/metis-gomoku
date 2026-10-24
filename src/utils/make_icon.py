"""從 200w.gif 產生 exe 圖示 src/assets/icon.ico。

用法（從 src/ 執行）：python utils/make_icon.py
需要 Pillow（只在產生圖示時用到，遊戲本身不依賴）。換圖後重跑即可。
"""
import os

from PIL import Image

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(SRC_DIR, "200w.gif")
OUT_PATH = os.path.join(SRC_DIR, "assets", "icon.ico")
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main():
    image = Image.open(SOURCE).convert("RGBA")
    image.save(OUT_PATH, format="ICO", sizes=SIZES)
    print(f"{OUT_PATH}: {os.path.getsize(OUT_PATH)} bytes")


if __name__ == "__main__":
    main()
