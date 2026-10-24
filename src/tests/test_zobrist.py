"""Zobrist 雜湊的正確性測試。

置換表的每一次命中都建立在「同一個局面 ⇒ 同一把 key」與「不同局面 ⇒ 幾乎不可能
同一把 key」之上。這兩件事都不會在對弈時報錯——壞掉的表現是 AI 偶爾走出無法解釋
的爛棋，因此只能靠測試把不變量釘住。

需要先編譯共享庫：
    cd src && gcc -I lib -shared -o ai.dll -fPIC lib/zobrist.c lib/pattern.c lib/boardstate.c lib/lines.c lib/eval.c lib/movegen.c lib/vcf.c lib/search.c ai.c
"""
import ctypes
import os
import platform

import pytest

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 必須與 ai.c 的 TABLE_SIZE 一致；index 取 key 的低 TABLE_BITS 位元
TABLE_BITS = 20


def _lib_filename():
    system = platform.system()
    if system == "Windows":
        return "ai.dll"
    if system == "Darwin":
        return "ai.dylib"
    return "ai.so"


LIB_PATH = os.path.join(SRC_DIR, _lib_filename())

pytestmark = pytest.mark.skipif(
    not os.path.exists(LIB_PATH),
    reason=f"{_lib_filename()} 未編譯；先執行 gcc -I lib -shared -o ai.dll -fPIC lib/zobrist.c lib/pattern.c lib/boardstate.c lib/lines.c lib/eval.c lib/movegen.c lib/vcf.c lib/search.c ai.c",
)


@pytest.fixture(scope="module")
def zob():
    lib = ctypes.CDLL(LIB_PATH)
    lib.getBoardMax.restype = ctypes.c_int
    board_max = lib.getBoardMax()

    board_type = (ctypes.c_int * board_max) * board_max

    lib.initZobristTable.restype = None
    lib.updateZobristKey.restype = None
    lib.updateZobristKey.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    lib.computeZobristKey.restype = ctypes.c_ulonglong
    lib.computeZobristKey.argtypes = [ctypes.POINTER(board_type)]

    lib.initZobristTable()

    table_type = ((ctypes.c_ulonglong * 2) * board_max) * board_max

    class Zob:
        BOARD_MAX = board_max
        current = ctypes.c_ulonglong.in_dll(lib, "currentZobristKey")
        table = table_type.in_dll(lib, "zobristTable")

        @staticmethod
        def all_entries():
            return [Zob.table[i][j][k]
                    for i in range(board_max)
                    for j in range(board_max)
                    for k in range(2)]

        @staticmethod
        def compute(stones):
            """stones = [(x, y, colour)] -> 整盤重算的 key。"""
            board = board_type()
            for x, y, colour in stones:
                board[y][x] = colour
            return lib.computeZobristKey(ctypes.byref(board))

        @staticmethod
        def incremental(stones):
            """從空盤逐手 XOR 累積出來的 key。"""
            Zob.current.value = 0
            for x, y, colour in stones:
                lib.updateZobristKey(x, y, colour)
            return Zob.current.value

    return Zob


class TestKeyEntropy:
    """key 的隨機位元必須鋪滿 64 位元。

    回歸測試：初版用 `(rand1 << 32) | rand2` 組 64 位元亂數，但 Windows/mingw 的
    RAND_MAX 是 32767（15 位元），實際只有 bit 0-14 與 32-46 會是 1——有效熵 30
    位元，且置換表 index 只用得到 32768 / 1048576 個 bucket。
    """

    def test_every_bit_is_used(self, zob):
        or_mask = 0
        for value in zob.all_entries():
            or_mask |= value
        assert or_mask.bit_count() == 64, (
            f"只有 {or_mask.bit_count()} / 64 個位元曾被設定："
            f"OR = 0x{or_mask:016x}"
        )

    def test_every_table_index_bit_is_used(self, zob):
        index_mask = (1 << TABLE_BITS) - 1
        or_mask = 0
        for value in zob.all_entries():
            or_mask |= value & index_mask
        assert or_mask == index_mask, (
            f"置換表 index 只用到 {or_mask.bit_count()} / {TABLE_BITS} 個位元，"
            f"等於只用了 {2 ** or_mask.bit_count()} / {1 << TABLE_BITS} 個 bucket"
        )

    def test_entries_are_distinct(self, zob):
        entries = zob.all_entries()
        assert len(set(entries)) == len(entries), "zobristTable 有重複值"


class TestIncrementalMatchesRecomputed:
    """逐手 XOR 與整盤重算必須得到同一把 key。

    回歸測試：`computeZobristKey` 走 board[i][j]（i 是 row，也就是 y），
    而 `updateZobristKey` 寫的是 zobristTable[x][y]——兩者互為轉置。
    findBestMove 改成進入時整盤重算之後，root 項與搜索中的增量項就對不起來，
    同一個局面在不同手會算出不同的 key，跨手的置換表完全失效。
    """

    @pytest.mark.parametrize("x,y,colour", [
        (3, 5, 1),   # x != y 才驗得出轉置
        (5, 3, 2),
        (0, 1, 1),
        (1, 0, 2),
    ])
    def test_single_stone(self, zob, x, y, colour):
        assert zob.incremental([(x, y, colour)]) == zob.compute([(x, y, colour)])

    def test_move_sequence(self, zob):
        m = zob.BOARD_MAX // 2
        stones = [
            (m, m, 1), (m + 1, m + 2, 2), (m - 2, m + 1, 1),
            (m + 2, m - 1, 2), (m - 1, m + 3, 1), (m + 3, m - 2, 2),
        ]
        assert zob.incremental(stones) == zob.compute(stones)

    def test_order_does_not_matter(self, zob):
        """置換表的意義就在於此：不同手順走到同一盤面要得到同一把 key。

        比對對象是 `compute` 而不是另一次 `incremental`——兩次 incremental 相比只驗到
        XOR 可交換（見 TestXorAlgebra），索引順序錯了也會通過。
        """
        m = zob.BOARD_MAX // 2
        stones = [(m, m, 1), (m + 1, m + 2, 2), (m - 2, m + 1, 1)]
        expected = zob.compute(stones)
        assert zob.incremental(stones) == expected
        assert zob.incremental(list(reversed(stones))) == expected


class TestXorAlgebra:
    """XOR 本身的性質：可交換、自反。

    這些不是索引轉置的回歸測試——它們在 `zobristTable[x][y]` 與 `[y][x]` 下都會通過。
    留著是因為搜索的落子/撤銷直接依賴這兩個性質；釘轉置 bug 的是
    TestIncrementalMatchesRecomputed 裡拿 `compute` 當對照的那幾項。
    """

    def test_undo_restores_key(self, zob):
        """搜索的落子/撤銷靠自反性還原 key。"""
        m = zob.BOARD_MAX // 2
        placed = [(m, m, 1), (m + 1, m + 2, 2)]
        undone = placed + [(m - 2, m + 1, 1), (m - 2, m + 1, 1)]
        assert zob.incremental(undone) == zob.incremental(placed)
