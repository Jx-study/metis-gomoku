"""從 src/lib/ai_unity.c（各模組 .c 的 unity build）生成 profiler 用的中間檔
（ai_profiled_core.generated.c）。

為什麼需要生成而非 #define 改名：
  用 `#define evaluate prof_real_evaluate` 會把定義與內部呼叫一起改名，
  於是內部呼叫直接跳過 wrapper，所有計數器恆為 0，而且沒有任何警告。
  這裡只改定義處的名字，呼叫處維持原名。連結時就會綁到 ai_profiled.c 的 wrapper。

原始碼本身不被修改；每次編譯都重新生成，所以不會像舊 ai_profiled.c 那樣漂成化石。

ai.c 拆成多檔後，單一 translation unit 只剩 ai_unity.c（一串 #include 各模組
.c）。本腳本把 ai_unity.c 展開的各檔內容串接成一份文字再做改名，等效於
單檔時代直接讀 ai.c；前置宣告改放在展開後最前面（早於任何函數定義，
但晚於 #include "types.h" 帶入的 BOARD_MAX / Move），不再依賴 Move
typedef 的行內 anchor。
"""
import os
import re
import sys

import unity

# 要插樁的函數：呼叫次數 + inclusive 耗時
TARGETS = [
    "evaluate", "quickEvaluate", "miniMax", "sortMoves",
    "endGame", "checkWin", "checkLine", "judgeMove",
    "hasAdjacentPiece", "maxRunAt",
]

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(HERE, "..", "..")            # lib/ -> _bench/ -> src/
LIB_DIR = os.path.join(SRC_DIR, "lib")
UNITY_PATH = os.path.join(LIB_DIR, "ai_unity.c")
OUT = os.path.join(HERE, "ai_profiled_core.generated.c")


def main():
    src = unity.expand(UNITY_PATH)
    original = src

    header = (
        "/* 自動生成，請勿手動編輯。來源 src/lib/ai_unity.c 展開後的各模組，"
        "生成器 src/_bench/lib/gen_profiled.py。\n"
        "   只有函數定義被改名為 prof_real_*；呼叫處維持原名以綁到 wrapper。 */\n"
    )

    # 呼叫處保留原名，但原名的宣告隨定義一起被改掉了，所以要補回 wrapper 的前置宣告。
    # 簽名直接從定義行抽，不手寫一份會漂移的副本。
    protos = []
    for name in TARGETS:
        m = re.search(
            r"^(?:static\s+)?((?:int|void|bool)\s+)" + name + r"\s*\(([^)]*)\)\s*\{",
            original, re.M | re.S)
        if not m:
            sys.exit("gen_profiled: 抽不出 %s 的簽名，該函數的定義格式可能改了。" % name)
        ret, args = m.group(1), " ".join(m.group(2).split())
        protos.append("%s%s(%s);" % (ret, name, args))
    proto_block = ("\n/* wrapper 的前置宣告（簽名抽自各模組 .c）*/\n"
                   + "\n".join(protos) + "\n")

    renamed = []
    for name in TARGETS:
        # 定義處的特徵：行首的回傳型別 + 函數名 + '('
        pattern = re.compile(
            r"^((?:static\s+)?(?:int|void|bool)\s+)" + name + r"(\s*\()",
            re.M,
        )
        src, n = pattern.subn(r"\1prof_real_" + name + r"\2", src)
        if n != 1:
            sys.exit("gen_profiled: %s 的定義找到 %d 處（預期 1），"
                     "該函數的簽名可能改了，請更新 TARGETS 或 pattern。" % (name, n))
        renamed.append(name)

    # 宣告依賴 BOARD_MAX 與 Move（在 types.h），故補一份 include 再接宣告，
    # 擺在展開內容最前面（早於任何函數定義），各模組 .c 本身仍各自 #include
    # 需要的 header，重複 include 由 include guard 擋掉。
    src = '#include "types.h"\n' + proto_block + src

    with open(OUT, "w", encoding="utf-8", newline="") as f:
        f.write(header + src)

    print("generated %s (%d functions instrumented: %s)"
          % (os.path.basename(OUT), len(renamed), ", ".join(renamed)))


if __name__ == "__main__":
    main()
