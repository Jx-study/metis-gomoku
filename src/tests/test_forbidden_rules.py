"""連珠禁手規則測試（透過 ctypes 驗證 `ai.dll` 的 `checkUnValid`）。

規則依據 RIF / 日本連珠社：
  - 禁手只適用於黑棋；白棋完全無禁手，長連對白棋算勝
  - 黑棋禁手三種：三三、四四、長連（>=6）
  - 五連優先：同時成五連與禁手時不算禁手，黑棋勝
  - 四三（一個四 + 一個活三）是黑棋唯一的合法致勝手，不可誤判為禁手

`checkUnValid` 回傳值：1 = 合法，0 = 該點已有棋子，負數 = 禁手代碼。
本檔一律只判斷「合法與否」（`== 1`），不依賴特定的負數代碼——註解說
-5 是長連但實作回傳 -6，兩者不一致，而所有呼叫端都只檢查 `!= 1`。

需要先編譯共享庫：
    cd src && gcc -I lib -shared -o ai.dll -fPIC lib/zobrist.c lib/pattern.c lib/boardstate.c lib/lines.c lib/eval.c lib/movegen.c lib/vcf.c lib/search.c ai.c
找不到時整個模組會被 skip。
"""
import ctypes
import os
import platform

import pytest

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BLACK = 1
WHITE = 2


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
def judge():
    """回傳 judge(stones, x, y, player) -> checkUnValid 的結果。

    stones = [(x, y, colour)]，代表落子前已在盤上的棋子。
    """
    lib = ctypes.CDLL(LIB_PATH)
    lib.getBoardMax.restype = ctypes.c_int
    board_max = lib.getBoardMax()

    lib.checkUnValid.restype = ctypes.c_int
    lib.checkUnValid.argtypes = [
        ctypes.POINTER(ctypes.c_int * board_max * board_max),
        ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ]
    lib.initZobristTable()
    lib.initTranspositionTable()

    board_type = (ctypes.c_int * board_max) * board_max

    def _judge(stones, x, y, player=BLACK):
        board = board_type()
        for sx, sy, colour in stones:
            board[sy][sx] = colour
        return lib.checkUnValid(ctypes.byref(board), x, y, player)

    _judge.board_max = board_max
    _judge.mid = board_max // 2
    return _judge


@pytest.fixture(scope="module")
def raw_judge():
    """回傳 raw_judge(stones, x, y, player) -> judgeMove 的原始回傳值。

    與 `judge` 不同，這裡不把「勝著」摺疊成 1，因此可以直接驗證
    2 = 五連/白棋長連。
    """
    lib = ctypes.CDLL(LIB_PATH)
    lib.getBoardMax.restype = ctypes.c_int
    board_max = lib.getBoardMax()

    lib.judgeMove.restype = ctypes.c_int
    lib.judgeMove.argtypes = [
        ctypes.POINTER(ctypes.c_int * board_max * board_max),
        ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ]

    board_type = (ctypes.c_int * board_max) * board_max

    def _judge(stones, x, y, player=BLACK):
        board = board_type()
        for sx, sy, colour in stones:
            board[sy][sx] = colour
        return lib.judgeMove(ctypes.byref(board), x, y, player)

    _judge.mid = board_max // 2
    return _judge


def is_legal(result):
    return result == 1


def line(fixed, positions, colour=BLACK, horizontal=True):
    """產生一條直線上的棋子。horizontal=True 時 fixed 是 y，否則是 x。"""
    if horizontal:
        return [(p, fixed, colour) for p in positions]
    return [(fixed, p, colour) for p in positions]


class TestWhiteHasNoForbiddenMoves:
    """白棋不受任何禁手限制——長連對白棋是勝利而非違規。"""

    def test_white_overline_allowed(self, judge):
        stones = line(5, [3, 4, 5, 6], WHITE) + line(5, [8], WHITE)
        assert is_legal(judge(stones, 7, 5, WHITE))

    def test_white_double_three_allowed(self, judge):
        stones = [(5, 7, WHITE), (6, 7, WHITE), (7, 5, WHITE), (7, 6, WHITE)]
        assert is_legal(judge(stones, 7, 7, WHITE))

    def test_white_double_four_allowed(self, judge):
        stones = [(4, 7, WHITE), (5, 7, WHITE), (6, 7, WHITE),
                  (7, 4, WHITE), (7, 5, WHITE), (7, 6, WHITE)]
        assert is_legal(judge(stones, 7, 7, WHITE))


class TestBlackDoubleThree:
    def test_cross_double_open_three_forbidden(self, judge):
        stones = [(6, 7, BLACK), (8, 7, BLACK), (7, 6, BLACK), (7, 8, BLACK)]
        assert not is_legal(judge(stones, 7, 7))

    def test_adjacent_double_open_three_forbidden(self, judge):
        stones = [(5, 7, BLACK), (6, 7, BLACK), (7, 5, BLACK), (7, 6, BLACK)]
        assert not is_legal(judge(stones, 7, 7))

    def test_single_open_three_legal(self, judge):
        stones = [(5, 7, BLACK), (6, 7, BLACK)]
        assert is_legal(judge(stones, 7, 7))

    def test_blocked_three_does_not_count(self, judge):
        """被白棋擋住的是眠三，不該與另一個活三湊成雙三。

        窗口 `..#SSS.....`：左端被白子封死，右端補滿只能成衝四，
        沒有任何一格填了會變活四，依 RIF 不是三。
        """
        stones = [(4, 7, WHITE), (5, 7, BLACK), (6, 7, BLACK),
                  (7, 5, BLACK), (7, 6, BLACK)]
        assert is_legal(judge(stones, 7, 7))

    def test_edge_three_does_not_count(self, judge):
        """三連完全貼死盤邊，往左無格可補，只能成衝四，不是三。

        窗口 `###SSS.....`：左端就是牆，與 test_blocked_three_does_not_count
        同理。注意這與「牆外還留一格」的情形不同，見 TestWallLimitsThree。
        """
        stones = [(0, 7, BLACK), (1, 7, BLACK), (7, 5, BLACK), (7, 6, BLACK)]
        assert is_legal(judge(stones, 2, 7))


class TestThreeNeedsOnlyOneWayToStraightFour:
    """RIF 的三是「能再加一子成活四」，一種填法就夠，不要求兩種。

    「兩種不同填法」是活四的定義（straight four: in two different ways），
    不是三的定義。碼 11/13（tp==1）依字面也是三，三三加總已納入這兩碼。

    這仰賴 `fivePoints`/`makesFive` 先補上「恰好五」守衛：沒有守衛時
    「填了會變六連」的點也會被當成成五點，tp>=1 就不等於真能成活四，
    全枚舉會有假三（碼 11 588/1296、碼 13 162/486 個窗口其實不是三）。
    """

    def test_reported_game_double_three_is_forbidden(self, judge):
        """使用者實戰回報的漏判：第 11 手同時成一個跳三與一個活三。

        以天元為原點，相對座標（右 +x、下 +y）：
              cx: -2 -1  0  1
          cy=-2:     白 黑 白
          cy=-1:        黑 黑
          cy= 0:  ★  .  黑 黑
          cy= 1:        白 白

        落 ★ 後：
          水平   `.....S.SS..`  填缺口成活四 -> 跳三（碼 11）
          副對角 `...SSS.....`  兩種填法成活四 -> 活三（碼 3）
        兩個三交於 ★，是三三禁手。
        """
        mid = judge.mid
        stones = [(mid + cx, mid + cy, colour) for cx, cy, colour in [
            (0, 0, BLACK), (1, 1, WHITE), (-1, -1, BLACK), (-2, -2, WHITE),
            (0, -1, BLACK), (1, -2, WHITE), (1, 0, BLACK), (-1, -2, WHITE),
            (0, -2, BLACK), (0, 1, WHITE),
        ]]
        assert not is_legal(judge(stones, mid - 2, mid))

    def test_jump_three_plus_open_three(self, judge):
        """跳三與活三交於落子點。

        水平黑子在 x=5,8、落 x=6，成 `.SS.S.`：填 x=7 的缺口即得
        `.SSSS.` 活四，所以是三。垂直是單純活三。兩者相交 -> 三三禁手。

        落子點必須是「造出跳形」的那一顆，不能是填缺口的那一顆——
        填缺口直接成四，那是合法的四三。
        """
        stones = (line(7, [5, 8], BLACK)
                  + [(6, 5, BLACK), (6, 6, BLACK)])
        assert not is_legal(judge(stones, 6, 7))

    def test_two_jump_threes(self, judge):
        """`..S.S*.S...` 形似跳三，實際上不是三，這一手合法。

        填缺口（index 3 或 6）的另一個成五點會拉到 6 連，依 RIF 是長連
        不算成五，所以那格只能成衝四，不是活四。makesFive 補上恰好五
        守衛前，這個窗口曾被誤判成碼 9（跳活三），見 renju-rules.md。
        """
        stones = (line(7, [4, 6, 9], BLACK)
                  + line(7, [4, 6, 9], BLACK, horizontal=False))
        assert is_legal(judge(stones, 7, 7))

    def test_two_jump_threes_forbidden(self, judge):
        """兩個跳活三相交才是真正的三三禁手，不需要任何一個是實心活三。

        兩個方向都是 `..S.SS..S..`，分類為碼 9（跳活三）：填 index 3
        或 index 6 都恰好成五連的活四，兩端不觸及長連。
        """
        stones = (line(7, [4, 6, 10], BLACK)
                  + line(7, [4, 6, 10], BLACK, horizontal=False))
        assert judge(stones, 7, 7) == -3

    def test_wall_side_three_plus_open_three(self, judge):
        """牆外仍留一格時，三連往開放端補滿可成活四，仍是三。

        落子 x=1、黑子在 x=2,3，窗口 `####.SSS...`：
        填 x=4 得 `####.SSSS..`，成五點在 x=0 與 x=5 兩處 = 活四。
        因此貼牆這一側不影響它是三，與垂直活三構成三三禁手。
        """
        stones = [(2, 7, BLACK), (3, 7, BLACK), (1, 6, BLACK), (1, 8, BLACK)]
        assert not is_legal(judge(stones, 1, 7))

    def test_three_flush_against_wall_is_not_a_three(self, judge):
        """三連緊貼盤邊、牆外一格都不剩，兩端都只能成衝四，不是三。

        落子 x=0、黑子在 x=1,2，窗口 `#####SSS...`：
        填 x=3 或 x=5 都只有一個成五點。與上一個測試只差一格。
        """
        stones = [(1, 7, BLACK), (2, 7, BLACK), (0, 6, BLACK), (0, 8, BLACK)]
        assert is_legal(judge(stones, 0, 7))

    def test_chong_only_three_still_does_not_count(self, judge):
        """碼 7/14（tp==0，只能成衝四）仍然不是三，放寬到 tp>=1 不該波及。

        水平 `..#SSS.....` 一端封死，配上垂直活三仍應合法。
        """
        stones = [(4, 7, WHITE), (5, 7, BLACK), (6, 7, BLACK),
                  (7, 5, BLACK), (7, 6, BLACK)]
        assert is_legal(judge(stones, 7, 7))

    def test_single_jump_three_is_legal(self, judge):
        """只有一個三時不構成禁手，放寬判準不可把單三也擋掉。"""
        stones = line(7, [5, 6, 8], BLACK)
        assert is_legal(judge(stones, 7, 7))

    def test_code11_with_overline_five_points_is_not_a_three(self, judge):
        """碼 11 不等於三：成活四的唯一填法其實只成衝四，因為另一個成五點會長連。

        水平窗口 `#...SS.S.S.`（落子 x=4）被 classifyWindow 判成碼 11，
        但填 x=6 之後真正的成五點只有 x=2 一個（填 x=8 會讓 x=4..8 成五而
        x=9 是黑子，屬長連，不算成五），所以那是衝四不是活四，原形不是三。

        配上垂直的真活三，若把碼 11 無條件計入三三就會誤判成禁手，
        擋掉黑棋的合法著法。這個測試釘住反向錯誤，防止日後草率放寬。
        """
        stones = [(4, 5, BLACK), (4, 6, BLACK),          # 垂直活三
                  (3, 7, BLACK), (6, 7, BLACK), (8, 7, BLACK)]
        assert is_legal(judge(stones, 4, 7))


class TestWallLimitsThree:
    """牆限制三的條件是「沒有任何一格填了會成活四」，不是「貼著牆」。

    RIF 的三是功能定義：「能再加一子成為活四」，一種填法就夠。活四才
    要求兩個成五點。因此關鍵不在三子離牆多遠，而在往開放端補滿之後
    還剩幾個成五點：

      x=1 落子、黑子 x=2,3  ->  `####.SSS...`  填 x=4 得兩個成五點，是三
      x=0 落子、黑子 x=1,2  ->  `#####SSS...`  兩端補滿都只剩一個成五點，不是三

    兩者只差一格，判定相反。
    """

    def _shapes(self, x):
        """回傳（水平三子中的兩顆, 垂直三子中的兩顆）。落子點為 (x, 7)。"""
        return ([(x + 1, 7, BLACK), (x + 2, 7, BLACK)],
                [(x, 6, BLACK), (x, 8, BLACK)])

    def test_center_double_open_three_forbidden(self, judge):
        """對照組：同一形狀在盤面中央，兩側都有空間 -> 三三禁手。"""
        horizontal, vertical = self._shapes(5)
        assert not is_legal(judge(horizontal + vertical, 5, 7))

    def test_wall_leaving_one_gap_is_still_a_three(self, judge):
        """牆外還留一格：往右補滿後兩端各有一個成五點，仍是三 -> 禁手。

        水平被分類成碼 13（tp==1）。
        """
        horizontal, vertical = self._shapes(1)
        assert not is_legal(judge(horizontal + vertical, 1, 7))

    def test_flush_against_wall_is_not_a_three(self, judge):
        """三子完全貼死牆：兩端補滿都只成衝四，不是三 -> 合法。"""
        horizontal, vertical = self._shapes(0)
        assert is_legal(judge(horizontal + vertical, 0, 7))


class TestWallDoesNotHideFour:
    """牆不得讓衝四整個消失——四四加總認 line[12]，漏判就會放行四四。

    形狀 1011 後接白子：填滿缺口即成五，依 RIF 是四。牆封住的是背面那端，
    成五點仍在，所以它仍是四——四只需要一個成五點，這點與三不同。
    """

    def test_center_four_with_blocked_far_end_counts(self, judge):
        """對照組：同形狀在中央，背面是空格 -> 判為跳四，湊成四四。"""
        stones = line(7, [7, 8, 9], BLACK) + [(10, 7, WHITE)]
        stones += line(5, [7, 8, 9], BLACK, horizontal=False) + [(5, 10, WHITE)]
        assert not is_legal(judge(stones, 5, 7))

    def test_edge_four_with_blocked_far_end_counts(self, judge):
        """貼牆的同形狀。牆封住的是背面，成五點仍在，依 RIF 仍是四。"""
        stones = line(7, [2, 3, 4], BLACK) + [(5, 7, WHITE)]
        stones += line(0, [9, 10, 11], BLACK, horizontal=False) + [(0, 12, WHITE)]
        assert not is_legal(judge(stones, 0, 7))


class TestBlackDoubleFour:
    def test_double_four_forbidden(self, judge):
        stones = [(4, 7, BLACK), (5, 7, BLACK), (6, 7, BLACK),
                  (7, 4, BLACK), (7, 5, BLACK), (7, 6, BLACK)]
        assert not is_legal(judge(stones, 7, 7))

    def test_single_four_legal(self, judge):
        stones = [(4, 7, BLACK), (5, 7, BLACK), (6, 7, BLACK)]
        assert is_legal(judge(stones, 7, 7))


class TestSameLineDoubleFour:
    """同一直線上也可能形成兩個四，依 RIF 與連珠通則同樣是四四禁手。

    出處：https://587.renju.org.tw/teach/teach018.htm
      「一子同時形成二個四，無論是活四或死四。另外四四有可能形成在同一線上」

    棋型碼加總數不出來：`checkLine` 每個方向只回傳一個最強碼，一條線上
    有兩個四時仍只貢獻 1。`judgeMove` 因此改為逐方向呼叫 countFours，
    用「四顆子集合」去重來數，活四的兩個成五點共用同一組四子算一個四。
    """

    def _horizontal(self, window):
        """window 是落子前以 (7,7) 為中心、左右各 5 格的字串（10 格，不含中心）。"""
        stones = []
        for off, ch in zip(list(range(-5, 0)) + list(range(1, 6)), window):
            x = 7 + off
            if ch == "S":
                stones.append((x, 7, BLACK))
            elif ch == "O":
                stones.append((x, 7, WHITE))
        return stones

    def test_two_fours_on_one_line(self, judge):
        """`S.S.SS.S..` 落中心後左右各一個四，只靠棋型碼會漏判。"""
        assert not is_legal(judge(self._horizontal("S.S.SS.S.."), 7, 7))

    def test_two_jump_fours_on_one_line(self, judge):
        """另一組同線雙四的跳形。"""
        assert not is_legal(judge(self._horizontal("S.SS.S.SS."), 7, 7))

    def test_straight_four_is_one_four(self, judge):
        """活四的兩個成五點屬同一組四子，是一個四，不能誤判成四四。"""
        assert is_legal(judge(self._horizontal("..SSS....."), 7, 7))

    def test_chong_four_is_one_four(self, judge):
        """一端被白子封死的衝四同樣只有一個四。"""
        assert is_legal(judge(self._horizontal(".OSSS....."), 7, 7))

    def test_overline_takes_priority_over_four_count(self, judge):
        """`..SSS*SSS..` 落子後是七連，判長連（-6）而不是四四。

        長連在 judgeMove 早於四四判定，數四的結果不影響這一條。
        """
        assert judge(self._horizontal("..SSSSSS.."), 7, 7) == -6

    def test_overline_blocked_direction_is_not_a_four(self, judge):
        """填了會超過五子的點不算成五點，該方向因此不算四。

        587 的「不算四」圖例：因長連關係，無任一點可形成五。
        水平 `SS.SS*SS.SS`：兩個空點填下去都成六連以上，水平一個四都不算。
        垂直另給一個真四。若水平被誤算成四就會湊成四四；正解是只有一個四，合法。

        這一手本身不是長連（水平最長連續是 3），所以不會被 -6 提前攔截，
        真的會走到數四那一段。
        """
        stones = (self._horizontal("SS.SSSS.SS")
                  + line(7, [4, 5, 6], BLACK, horizontal=False))
        assert judge(stones, 7, 7) != -4

    def test_four_not_through_move_point_does_not_count(self, judge):
        """四要在落子點與另一個四相會才算數，本來就存在的舊四不算。

        `X.XXX.H.`（黑子 x=3,5,6,7，落子 H=x=9）：填 x=4 得 x=3..7 五連，
        這組四子（3,5,6,7）落子前就已成立，不經過本次落子點 x=9，
        依 RIF「meet each other in this intersection」不算與這手相關的四。
        填 x=8 得 x=5..9 五連，這組（5,6,7,9）才經過落子點，是唯一的四。
        """
        stones = line(7, [3, 5, 6, 7], BLACK)
        assert is_legal(judge(stones, 9, 7))


class TestFourThreeIsLegal:
    """四三是黑棋唯一的合法致勝手，誤判成禁手會讓黑棋無法取勝。"""

    def test_four_plus_open_three(self, judge):
        stones = [(4, 7, BLACK), (5, 7, BLACK), (6, 7, BLACK),
                  (7, 5, BLACK), (7, 6, BLACK)]
        assert is_legal(judge(stones, 7, 7))

    def test_blocked_four_plus_open_three(self, judge):
        stones = [(3, 7, WHITE), (4, 7, BLACK), (5, 7, BLACK), (6, 7, BLACK),
                  (7, 5, BLACK), (7, 6, BLACK)]
        assert is_legal(judge(stones, 7, 7))


class TestRecursiveForbiddenIsNotImplemented:
    """RIF §9.3：雙三只在兩個以上的三都能推進到合法活四時才禁手。

    判斷一個表面雙三合不合法，要對每個三的活四點模擬落子，遞迴判定
    那個活四點本身合不合法（會不會同時成五、長連、四四，或觸發另一個
    禁手雙三）。只剩一個三能推進，這個表面雙三就豁免、可以下。

    `judgeMove` 在判定表面雙三成立那一刻才觸發這個檢查（`threeSpotsInDirection`
    + 對活四點遞迴呼叫 `judgeMove`），不需要更動 `patternTable` 的單方向查表。
    """

    # 水平跳三 `S*S`：落 (7,7) 後為 x=6,7,8 的形，兩個活四點是 (5,7) 與 (9,7)
    HORIZONTAL = [(6, 7, BLACK), (8, 7, BLACK)]
    DIAGONAL = [(5, 5, BLACK), (6, 6, BLACK)]
    # 讓 (5,7) 落黑即成雙三
    MAKES_LEFT_FORBIDDEN = [(5, 5, BLACK), (5, 6, BLACK), (3, 5, BLACK), (4, 6, BLACK)]
    # 讓 (9,7) 落黑即成雙三
    MAKES_RIGHT_FORBIDDEN = [(9, 5, BLACK), (9, 6, BLACK), (11, 5, BLACK), (10, 6, BLACK)]

    def test_both_straight_four_points_are_indeed_forbidden(self, judge):
        """前置條件：兩個活四點確實都是黑棋禁手點。

        驗證下面測試案例的布局前提，不是遞迴規則本身。前提壞掉時這裡
        會先紅，才不會讓下一個測試的通過失去意義。
        """
        base = self.HORIZONTAL + self.DIAGONAL
        assert not is_legal(judge(base + self.MAKES_LEFT_FORBIDDEN, 5, 7))
        assert not is_legal(judge(base + self.MAKES_RIGHT_FORBIDDEN, 9, 7))

    def test_three_whose_straight_four_points_are_all_forbidden(self, judge):
        """水平形的兩個活四點都是黑棋禁手點，依 RIF 該水平形不算三。

        不算三就湊不成三三，這一手合法。
        """
        stones = (self.HORIZONTAL + self.DIAGONAL
                  + self.MAKES_LEFT_FORBIDDEN + self.MAKES_RIGHT_FORBIDDEN)
        assert is_legal(judge(stones, 7, 7))

    # 水平活三 `SS*`：落 (7,7) 後兩個活四點是 (4,7) 與 (8,7)；縱向另成一個活三
    OPEN_THREE_H = [(5, 7, BLACK), (6, 7, BLACK)]
    OPEN_THREE_V = [(7, 5, BLACK), (7, 6, BLACK)]
    # (4,7) 在主對角線、(8,7) 在副對角線各自恰好成五
    FIVE_THROUGH_LEFT = [(0, 3, BLACK), (1, 4, BLACK), (2, 5, BLACK), (3, 6, BLACK)]
    FIVE_THROUGH_RIGHT = [(12, 3, BLACK), (11, 4, BLACK), (10, 5, BLACK), (9, 6, BLACK)]

    def test_straight_four_points_indeed_make_five(self, raw_judge):
        """前置條件：兩個活四點落黑確實成五（judgeMove 回傳 2）。"""
        stones = (self.OPEN_THREE_H + self.OPEN_THREE_V
                  + self.FIVE_THROUGH_LEFT + self.FIVE_THROUGH_RIGHT)
        assert raw_judge(stones, 4, 7) == 2
        assert raw_judge(stones, 8, 7) == 2

    def test_three_whose_straight_four_points_all_make_five_elsewhere(self, judge):
        """活四點在另一方向同時成五，落下去是五連不是活四，依 RIF 該形不算三。

        水平形的兩個活四點都同時成五，只剩縱向一個三，這一手合法。
        """
        stones = (self.OPEN_THREE_H + self.OPEN_THREE_V
                  + self.FIVE_THROUGH_LEFT + self.FIVE_THROUGH_RIGHT)
        assert is_legal(judge(stones, 7, 7))

    def test_three_with_one_straight_four_point_making_five_still_counts(self, judge):
        """只有一個活四點同時成五時，另一點仍能成活四，水平形仍是三，構成三三禁手。"""
        stones = self.OPEN_THREE_H + self.OPEN_THREE_V + self.FIVE_THROUGH_LEFT
        assert judge(stones, 7, 7) == -3


class TestExactFive:
    def test_exact_five_legal(self, judge):
        stones = line(7, [3, 4, 5, 6], BLACK)
        assert is_legal(judge(stones, 7, 7))

    def test_five_takes_priority_over_other_shapes(self, judge):
        """五連與其他棋型同時成立時，五連優先，黑棋勝。"""
        stones = line(7, [3, 4, 5, 6], BLACK) + [
            (7, 5, BLACK), (7, 6, BLACK), (7, 9, BLACK)]
        assert is_legal(judge(stones, 7, 7))


class TestBlackOverline:
    """長連（>=6）對黑棋是禁手。"""

    def test_six_by_extending_right(self, judge):
        stones = line(7, [3, 4, 5, 6, 7], BLACK)
        assert not is_legal(judge(stones, 8, 7))

    def test_six_by_extending_left(self, judge):
        stones = line(7, [4, 5, 6, 7, 8], BLACK)
        assert not is_legal(judge(stones, 3, 7))

    @pytest.mark.parametrize("left,right", [
        ([4, 5, 6], [8, 9]),        # 左3右2
        ([5, 6], [8, 9, 10]),       # 左2右3
        ([6], [8, 9, 10, 11]),      # 左1右4
    ])
    def test_six_by_filling_gap(self, judge, left, right):
        stones = line(7, left, BLACK) + line(7, right, BLACK)
        assert not is_legal(judge(stones, 7, 7))

    def test_seven_in_a_row(self, judge):
        stones = line(7, [2, 3, 4, 5, 6], BLACK) + line(7, [8], BLACK)
        assert not is_legal(judge(stones, 7, 7))

    def test_six_with_four_on_one_side_and_one_on_other(self, judge):
        """左 4 右 1 填中間成六連。

        盤面與 test_six_by_filling_gap 的其他構型完全等價（同樣是連續
        六子）。曾因 checkLine 的棋型分類漏判而判成合法，現由
        judgeMove 經 checkLine 查 patternTable 的長連碼（13）處理。
        """
        stones = line(7, [3, 4, 5, 6], BLACK) + line(7, [8], BLACK)
        assert not is_legal(judge(stones, 7, 7))

    @pytest.mark.parametrize("dx,dy", [(1, 0), (0, 1), (1, 1), (1, -1)])
    def test_six_four_one_split_in_all_directions(self, judge, dx, dy):
        mid = judge.mid
        stones = [(mid + k * dx, mid + k * dy, BLACK) for k in (-4, -3, -2, -1)]
        stones.append((mid + dx, mid + dy, BLACK))
        assert not is_legal(judge(stones, mid, mid))


class TestOccupiedSquare:
    @pytest.mark.parametrize("player", [BLACK, WHITE])
    def test_occupied_returns_zero(self, judge, player):
        assert judge([(7, 7, BLACK)], 7, 7, player) == 0


class TestFiveDetectionIgnoresShape:
    """成五/長連判定必須只看連續長度，不受周圍棋型影響。

    曾有的錯誤：judgeMove 透過 checkLine 的棋型分類判斷勝負，而
    checkLine 的 gaps == 1 分支只處理 count 為 3、4 的情形。當落子點
    隔一格外還有己方棋子時 count >= 5，所有子條件皆落空、回傳全零，
    於是「明明成五」被判成普通著法——AI 因此漏擋而輸棋。
    現改由 checkLine 查 patternTable 的恰好五連碼（5）判定。
    """

    WIN = 2

    @pytest.mark.parametrize("extra", [3, 2, 1, 0])
    @pytest.mark.parametrize("player", [BLACK, WHITE])
    def test_five_detected_with_far_friendly_stone(self, raw_judge, player, extra):
        """落子點左側隔一格外另有己方棋子時，仍須認得五連。

        盤面如 `W . _ W W W W`：填入 _ 成五，額外那顆隔開的遠方棋子
        不該讓判定失效（它與五連之間有空位，不構成長連）。
        """
        stones = line(7, [8, 9, 10, 11], player) + line(7, [extra], player)
        assert raw_judge(stones, 7, 7, player) == self.WIN

    @pytest.mark.parametrize("player", [BLACK, WHITE])
    def test_five_detected_with_gap_on_both_sides(self, raw_judge, player):
        """兩側都隔一格另有己方棋子，中間仍是乾淨的五連。"""
        stones = (line(7, [2], player) + line(7, [4, 5, 6, 7], player)
                  + line(7, [10], player))
        assert raw_judge(stones, 8, 7, player) == self.WIN

    @pytest.mark.parametrize("dx,dy", [(1, 0), (0, 1), (1, 1), (1, -1)])
    @pytest.mark.parametrize("player", [BLACK, WHITE])
    def test_five_detected_in_all_directions(self, raw_judge, player, dx, dy):
        mid = raw_judge.mid
        stones = [(mid + k * dx, mid + k * dy, player) for k in (1, 2, 3, 4)]
        stones.append((mid - 2 * dx, mid - 2 * dy, player))   # 隔一格的遠方棋子（不接續）
        assert raw_judge(stones, mid, mid, player) == self.WIN

    def test_black_five_beats_double_three(self, raw_judge):
        """五連優先於禁手：同時成五連與雙三時，黑棋勝而非違規。"""
        stones = (line(7, [3, 4, 5, 6], BLACK)
                  + [(7, 5, BLACK), (7, 6, BLACK), (7, 8, BLACK), (7, 9, BLACK)])
        assert raw_judge(stones, 7, 7, BLACK) == self.WIN

    def test_black_five_beats_overline_in_another_direction(self, raw_judge):
        """五連優先於禁手：水平恰好五連、垂直長連時，黑棋勝而非長連禁手。

        只取四個方向的最長連續長度會讓垂直的七連蓋過水平的五連，
        因此 patternTable 把恰好五連（碼 5）與長連（碼 13）分開編碼，
        由 checkLine 逐方向讀取，不會互相蓋過。
        """
        stones = (line(7, [8, 9, 10, 11], BLACK)
                  + [(7, y, BLACK) for y in (4, 5, 6, 8, 9, 10)])
        assert raw_judge(stones, 7, 7, BLACK) == self.WIN

    def test_white_five_with_overline_in_another_direction_is_win(self, raw_judge):
        """白棋兩者皆勝，方向如何組合都應回傳勝著。"""
        stones = (line(7, [8, 9, 10, 11], WHITE)
                  + [(7, y, WHITE) for y in (4, 5, 6, 8, 9, 10)])
        assert raw_judge(stones, 7, 7, WHITE) == self.WIN

    def test_black_split_overline_is_forbidden(self, raw_judge):
        """左 3 右 3 填中間成七連，黑棋長連禁手（不可判成勝著）。"""
        stones = line(7, [4, 5, 6], BLACK) + line(7, [8, 9, 10], BLACK)
        assert raw_judge(stones, 7, 7, BLACK) < 0

    def test_white_split_overline_is_win(self, raw_judge):
        stones = line(7, [4, 5, 6], WHITE) + line(7, [8, 9, 10], WHITE)
        assert raw_judge(stones, 7, 7, WHITE) == self.WIN
