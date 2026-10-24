"""把中文字型裁成介面實際用到的字元，輸出到 src/assets/fonts/。

用法（從 src/ 執行）：

    python utils/subset_font.py <來源字型檔>

來源用 Noto Sans TC（SIL OFL 1.1），可變字型會先固定在 Regular（wght 400）。
字元取自 TEXT_SOURCES 裡的字串常值加上可列印 ASCII；改了介面文字後要重跑，
`test_gomoku_ui.py` 會檢查內附字型是否涵蓋所有介面文字。
"""
import io
import os
import sys
import tokenize

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXT_SOURCES = ["Gomoku.py", "gomoku_ui.py"]
OUT_PATH = os.path.join(SRC_DIR, "assets", "fonts", "NotoSansTC-Subset.ttf")

# f-string 在 3.12 起拆成 FSTRING_MIDDLE，之前整段是 STRING
_TEXT_TOKENS = {tokenize.STRING} | ({tokenize.FSTRING_MIDDLE} if hasattr(tokenize, "FSTRING_MIDDLE") else set())


def ui_characters():
    chars = {chr(c) for c in range(0x20, 0x7F)}
    for name in TEXT_SOURCES:
        with open(os.path.join(SRC_DIR, name), encoding="utf-8") as f:
            source = f.read()
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type in _TEXT_TOKENS:
                chars |= {c for c in tok.string if ord(c) > 0x7E}
    return chars


def main(source_path):
    from fontTools.ttLib import TTFont
    from fontTools.subset import Options, Subsetter
    from fontTools.varLib import instancer

    font = TTFont(source_path)
    if "fvar" in font:
        font = instancer.instantiateVariableFont(font, {"wght": 400})
    options = Options()
    options.name_IDs = ["*"]            # 保留版權與授權欄位
    subsetter = Subsetter(options)
    subsetter.populate(text="".join(sorted(ui_characters())))
    subsetter.subset(font)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    font.save(OUT_PATH)
    print(f"{OUT_PATH}: {len(ui_characters())} 字, {os.path.getsize(OUT_PATH)} bytes")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
