"""棋型查表的雙實作全枚舉對拍。

`classifyWindow`（C，`ai.c`）把一條方向線的 11 格窗口（中心恆 SELF、牆併入 OPP）
分類成 16 類棋型代碼之一。本檔用一個獨立推導的 Python 版 `classify_window_twin`
對全部 3^10 = 59049 種窗口對拍。

分類依 RIF 定義：四是「能加一子成五」，活四是「能以兩種方式成五」，
三是「能加一子成活四」。牆與敵子都不是空格，成五點自然數不到，
所以不需要區分兩者。

眠三/跳三（code 7/14）不是 RIF 定義，是本專案為了不讓「填了只能成衝四」
的三級棋型完全消失（回傳 0）而新增的次級棋型，見 Note/technical/renju-rules.md。

雙實作的意義：C 版由中心往外數點數（`fivePoints` / `threePoints` / `rushPoints`
各掃一遍窗口）。twin 改用「枚舉所有含中心的 5 格區間、看每個區間缺幾子」的
區間視角推導，兩者結構不同，避免犯同一個錯。

需要先編譯共享庫：
    cd src && gcc -I lib -shared -o ai.dll -fPIC lib/zobrist.c lib/pattern.c lib/boardstate.c lib/lines.c lib/eval.c lib/movegen.c lib/vcf.c lib/search.c ai.c
找不到時整個模組會被 skip。
"""
import ctypes
import itertools
import os
import platform
import random

import pytest

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EMPTY, SELF, OPP = 0, 1, 2
WINDOW = 11
CENTER = 5
TABLE_SIZE = 59049   # 3 ** 10

BLACK, WHITE = 1, 2

# 16 類代碼：[2:活二 3:活三 4:活四 5:五連 6:眠二 7:純衝四眠三 8:衝四
#            9:跳活三 10:跳活四 11:偏活跳三 12:跳四 13:偏活三
#            14:純衝四跳三 15:長連]，0 = 無棋型


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


# --------------------------------------------------------------------------
# 編碼 / 解碼（與 ai.c 的 encodeWindow / initPatternTable 一致）
# --------------------------------------------------------------------------
_DECODE_OFFSETS = [5, 4, 3, 2, 1, -1, -2, -3, -4, -5]   # +5 為最低位


def decode(idx):
    """0..59048 -> cells[11]，中心恆 SELF。"""
    cells = [EMPTY] * WINDOW
    cells[CENTER] = SELF
    rem = idx
    for off in _DECODE_OFFSETS:
        cells[CENTER + off] = rem % 3
        rem //= 3
    return cells


def render(cells):
    glyph = {EMPTY: ".", SELF: "S", OPP: "O"}
    return "".join(glyph[c] for c in cells)


# --------------------------------------------------------------------------
# 獨立 twin
# --------------------------------------------------------------------------
def _true_run(cells):
    """穿過中心的連續 SELF 長度（leftRun + 1 + rightRun）。"""
    left = 0
    for j in range(1, 6):
        if cells[CENTER - j] == SELF:
            left += 1
        else:
            break
    right = 0
    for j in range(1, 6):
        if cells[CENTER + j] == SELF:
            right += 1
        else:
            break
    return left + 1 + right


def _segments():
    """所有含中心的 5 格連續區間。"""
    return [list(range(s, s + 5)) for s in range(CENTER - 4, CENTER + 1)]


def _makes_five(cells):
    """區間視角：存在一個含中心、恰好五連的區間全為 SELF。

    恰好五：區間兩側外一格不得也是 SELF，否則屬於長連而非五連。
    """
    for seg in _segments():
        if not all(cells[i] == SELF for i in seg):
            continue
        s = seg[0]
        if s - 1 >= 0 and cells[s - 1] == SELF:
            continue
        if s + 5 < WINDOW and cells[s + 5] == SELF:
            continue
        return True
    return False


def _fillable_to_five(cells):
    """區間視角：哪些空格填入後能讓某個含中心區間湊滿恰好五子。

    對每個區間算「缺哪幾格」，只缺一格且該格為空時，那格就是成五點；
    區間兩側外一格若已是 SELF，填了會變長連，不算成五點。
    """
    spots = set()
    for seg in _segments():
        missing = [i for i in seg if cells[i] != SELF]
        if len(missing) != 1 or cells[missing[0]] != EMPTY:
            continue
        s = seg[0]
        if s - 1 >= 0 and cells[s - 1] == SELF:
            continue
        if s + 5 < WINDOW and cells[s + 5] == SELF:
            continue
        spots.add(missing[0])
    return spots


def _fillable_to_straight_four(cells):
    """哪些空格填入後成活四（不同時成五）。活四 = 有兩個以上成五點。"""
    spots = set()
    for i in range(WINDOW):
        if cells[i] != EMPTY:
            continue
        trial = list(cells)
        trial[i] = SELF
        if _makes_five(trial):
            continue
        if len(_fillable_to_five(trial)) >= 2:
            spots.add(i)
    return spots


def _fillable_to_rush_four(cells):
    """哪些空格填入後只成衝四（不同時成五，且成五點恰一個）。

    rushPoints：與 threePoints 互斥的三級判準——這格填了不會成活四，
    只會把威脅推進到「只有一個成五點」的衝四，見 renju-rules.md 的 rp。
    """
    spots = set()
    for i in range(WINDOW):
        if cells[i] != EMPTY:
            continue
        trial = list(cells)
        trial[i] = SELF
        if _makes_five(trial):
            continue
        if len(_fillable_to_five(trial)) == 1:
            spots.add(i)
    return spots


def _minor_twin(cells):
    """二級：RIF 未定義，沿用現行的實心二連判法。"""
    if _true_run(cells) != 2:
        return 0
    left_run = 0
    for j in range(1, 6):
        if cells[CENTER - j] == SELF:
            left_run += 1
        else:
            break
    left = CENTER - left_run - 1
    right = left + 3
    left_open = left >= 0 and cells[left] == EMPTY
    right_open = right < WINDOW and cells[right] == EMPTY
    if left_open and left - 1 >= 0 and cells[left - 1] == SELF:
        return 0
    if right_open and right + 1 < WINDOW and cells[right + 1] == SELF:
        return 0
    if left_open and right_open:
        return 2
    if left_open or right_open:
        return 6
    return 0


def classify_window_twin(cells):
    """獨立實作：11 格窗口 -> 棋型代碼 {0, 2..15}。"""
    if cells[CENTER] != SELF:
        return 0

    run = _true_run(cells)
    if run >= 6:
        return 15
    if _makes_five(cells):
        return 5

    five_spots = _fillable_to_five(cells)
    if five_spots:
        solid = run == 4
        if len(five_spots) >= 2:
            return 4 if solid else 10
        return 8 if solid else 12

    three_spots = _fillable_to_straight_four(cells)
    if three_spots:
        solid = run == 3
        if len(three_spots) >= 2:
            return 3 if solid else 9
        return 13 if solid else 11

    rush_spots = _fillable_to_rush_four(cells)
    if rush_spots:
        return 7 if run == 3 else 14

    return _minor_twin(cells)


# --------------------------------------------------------------------------
# 輔助：獨立的「填哪個 EMPTY 能成五」枚舉（四級分類的二次佐證）
# --------------------------------------------------------------------------
def spots_completing_five(cells):
    """回傳「填入後含中心的某個 5 格區間全滿」的 EMPTY 格 index 清單。

    逐格試填再判定，與 `_fillable_to_five` 的區間扣減視角互為佐證。
    """
    out = []
    for i in range(WINDOW):
        if cells[i] != EMPTY:
            continue
        trial = list(cells)
        trial[i] = SELF
        if _makes_five(trial):
            out.append(i)
    return out


# --------------------------------------------------------------------------
# ctypes fixtures
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def lib():
    _lib = ctypes.CDLL(LIB_PATH)
    _lib.getBoardMax.restype = ctypes.c_int
    _lib.classifyWindow.restype = ctypes.c_int
    _lib.classifyWindow.argtypes = [ctypes.POINTER(ctypes.c_int * WINDOW)]
    return _lib


@pytest.fixture(scope="module")
def classify_c(lib):
    def _call(cells):
        return lib.classifyWindow((ctypes.c_int * WINDOW)(*cells))
    return _call


@pytest.fixture(scope="module")
def check_line(lib):
    """回傳 check_line(cells, cx) -> checkLine 在水平方向給出的 slot。

    `cx` 是落子點的 x 座標，可以貼邊——出界的格子不放子，由 `encodeWindow`
    自行編成牆。其餘三個方向只有孤立的中心子，不會觸發任何分支，
    所以 my_line 只反映水平線的貢獻。多 slot 時回傳 tuple。
    """
    board_max = lib.getBoardMax()
    board_type = (ctypes.c_int * board_max) * board_max
    lib.checkLine.restype = None
    lib.checkLine.argtypes = [
        ctypes.POINTER(board_type),
        ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(ctypes.c_int * 16),
    ]
    cy = board_max // 2

    def _horizontal_slot(cells, cx=None):
        if cx is None:
            cx = board_max // 2
        board = board_type()
        board[cy][cx] = BLACK
        for off in range(-CENTER, CENTER + 1):
            if off == 0:
                continue
            nx = cx + off
            if not 0 <= nx < board_max:
                continue   # 出界不放子，encodeWindow 會當成牆
            cell = cells[CENTER + off]
            if cell == SELF:
                board[cy][nx] = BLACK
            elif cell == OPP:
                board[cy][nx] = WHITE
        my_line = (ctypes.c_int * 16)()
        lib.checkLine(ctypes.byref(board), cx, cy, BLACK, my_line)
        slots = [i for i in range(16) if my_line[i] != 0]
        if not slots:
            return 0
        if len(slots) == 1:
            return slots[0]
        return tuple(slots)

    _horizontal_slot.board_max = board_max
    return _horizontal_slot


# --------------------------------------------------------------------------
# 建構期健檢
# --------------------------------------------------------------------------
class TestEncoding:
    def test_decode_center_is_self(self):
        for idx in (0, 1, 12345, TABLE_SIZE - 1):
            assert decode(idx)[CENTER] == SELF

    def test_decode_is_a_bijection(self):
        seen = set()
        for idx in range(TABLE_SIZE):
            seen.add(tuple(decode(idx)))
        assert len(seen) == TABLE_SIZE

    def test_known_shapes_render(self):
        # idx 0 -> 周邊全 EMPTY，中心 SELF
        assert render(decode(0)) == ".....S....."
        # idx 59048 -> 周邊全 OPP
        assert render(decode(TABLE_SIZE - 1)) == "OOOOOSOOOOO"


# --------------------------------------------------------------------------
# Step 2：twin vs classifyWindow 全枚舉對拍
# --------------------------------------------------------------------------
class TestStep2FullEnumeration:
    def test_twin_matches_classifyWindow_for_every_window(self, classify_c):
        """全部 59049 種窗口：twin 與 classifyWindow 必須逐一相等。"""
        mismatches = []
        for idx in range(TABLE_SIZE):
            cells = decode(idx)
            got_c = classify_c(cells)
            got_twin = classify_window_twin(cells)
            if got_c != got_twin:
                mismatches.append((idx, render(cells), got_c, got_twin))

        report = "\n".join(
            f"  idx={i:5d} {w}  classifyWindow={c} twin={t}"
            for i, w, c, t in mismatches[:60]
        )
        assert not mismatches, (
            f"{len(mismatches)} / {TABLE_SIZE} 筆 twin 與 classifyWindow 不一致:\n{report}"
        )

    def test_value_domain(self, classify_c):
        allowed = {0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15}
        for idx in range(TABLE_SIZE):
            v = classify_c(decode(idx))
            assert v in allowed, f"idx={idx} 回傳非法代碼 {v}"


class TestFiveAndOverlineDetection:
    """回歸守門：穿過中心的實心連續 >= 5 一律判 5 / 15。

    曾有的錯誤：有一顆被空格隔開的己方遠子時整組落空回 0，真實成五被
    評為無棋型。五連與長連現在最先判，不受其他棋子干擾。
    """

    def test_every_window_with_run_five_or_more_classifies_as_five_or_overline(self, classify_c):
        checked = 0
        for idx in range(TABLE_SIZE):
            cells = decode(idx)
            true_run = _true_run(cells)
            if true_run < 5:
                continue
            checked += 1
            got = classify_c(cells)
            expected = 15 if true_run > 5 else 5
            assert got == expected, (
                f"idx={idx} {render(cells)} trueRun={true_run} "
                f"classifyWindow={got} 應為 {expected}"
            )
        assert checked > 0

    def test_gap_separated_far_stone_does_not_hide_five(self, classify_c):
        # ....SSSSS.S：中心的實五 + 一顆隔空遠子（gaps==1），仍須認得五連
        cells = list(decode(361))
        assert render(cells) == "....SSSSS.S"
        assert classify_c(cells) == 5
        assert classify_window_twin(cells) == 5

    def test_gap_separated_far_stone_does_not_hide_overline(self, classify_c):
        # ...S.SSSSSS：中心的實六連 + 一顆隔空遠子，仍須認得長連
        cells = list(decode(850))
        assert render(cells) == "...S.SSSSSS"
        assert classify_c(cells) == 15
        assert classify_window_twin(cells) == 15

    def test_four_level_windows_have_a_winning_spot(self, classify_c):
        """獨立佐證：classifyWindow 判為四級（4/8/10/12）的窗口，
        必有 EMPTY 格填入後能穿過中心成五。"""
        for idx in range(TABLE_SIZE):
            cells = decode(idx)
            if classify_c(cells) in (4, 8, 10, 12):
                assert spots_completing_five(cells), (
                    f"idx={idx} {render(cells)} 判為四級卻無成五點"
                )


# --------------------------------------------------------------------------
# 端到端：checkLine 在貼邊落子點的行為
# --------------------------------------------------------------------------
class TestCheckLineAtBoardEdges:
    """端到端：`checkLine` 在貼邊落子點的輸出必須與查表一致。

    原本的對拍只把落子點放在盤面中央，中央永遠碰不到牆，
    整類與邊界互動的行為一次都沒被測到（實測漏掉 31,662 筆差異）。
    這裡改為掃過所有會碰到牆的 x，把出界的格子固定成 OPP 後比對。
    """

    def _wall_adjusted(self, cells, cx, board_max):
        """把出界位置改成 OPP，得到 encodeWindow 實際看到的窗口。"""
        out = list(cells)
        for off in range(-CENTER, CENTER + 1):
            if off == 0:
                continue
            if not 0 <= cx + off < board_max:
                out[CENTER + off] = OPP
        return out

    def test_edge_positions_match_the_table(self, classify_c, check_line):
        board_max = check_line.board_max
        edges = list(range(5)) + list(range(board_max - 5, board_max))
        bad = []
        checked = 0
        for cx in edges:
            for idx in range(TABLE_SIZE):
                cells = decode(idx)
                expected = classify_c(self._wall_adjusted(cells, cx, board_max))
                got = check_line(cells, cx)
                checked += 1
                if got != expected:
                    bad.append((cx, render(cells), got, expected))
        report = "\n".join(
            f"  cx={c} {w}  checkLine={g} table={e}" for c, w, g, e in bad[:40]
        )
        assert checked > 0
        assert not bad, f"{len(bad)} 筆貼邊窗口與查表不一致:\n{report}"


# --------------------------------------------------------------------------
# RIF 定義的不變量（不依賴 twin，直接驗分類語意）
# --------------------------------------------------------------------------
class TestRifInvariants:
    """四級與三級的定義性質，用逐格試填獨立驗證。"""

    def test_four_level_iff_one_move_from_five(self, classify_c):
        """四級（4/8/10/12）等價於「存在成五點」，兩個方向都要成立。"""
        for idx in range(TABLE_SIZE):
            cells = decode(idx)
            code = classify_c(cells)
            if code in (5, 15):
                continue   # 已經成五/長連，不再談「差一子」
            spots = spots_completing_five(cells)
            if code in (4, 8, 10, 12):
                assert spots, f"{render(cells)} 判為四級卻無成五點"
            else:
                assert not spots, f"{render(cells)} 有成五點卻判為 {code}"

    def test_open_four_has_two_winning_spots(self, classify_c):
        """活四與跳活四要有兩個以上成五點，衝四與跳四恰好一個。"""
        for idx in range(TABLE_SIZE):
            cells = decode(idx)
            code = classify_c(cells)
            if code in (4, 10):
                assert len(spots_completing_five(cells)) >= 2, render(cells)
            elif code in (8, 12):
                assert len(spots_completing_five(cells)) == 1, render(cells)

    def test_three_level_can_reach_a_straight_four(self, classify_c):
        """三級能成活四的分支（3/9/11/13）必有一格填入後成活四；
        活三與跳活三（3/9）要有兩格，偏活三/偏活跳三（13/11）恰一格。"""
        for idx in range(TABLE_SIZE):
            cells = decode(idx)
            code = classify_c(cells)
            if code not in (3, 9, 11, 13):
                continue
            ways = _fillable_to_straight_four(cells)
            assert ways, f"{render(cells)} 判為三級卻成不了活四"
            if code in (3, 9):
                assert len(ways) >= 2, f"{render(cells)} 判為活三級卻只有一種成活四填法"
            else:
                assert len(ways) == 1, f"{render(cells)} 判為非活三級卻有多種成活四填法"

    def test_chong_only_three_level_cannot_reach_a_straight_four(self, classify_c):
        """眠三/跳三（7/14）填了只能成衝四，絕不能成活四——這是它們與
        13/11（偏活三/偏活跳三）唯一的區別：後者仍有一格能成活四。"""
        for idx in range(TABLE_SIZE):
            cells = decode(idx)
            code = classify_c(cells)
            if code not in (7, 14):
                continue
            assert not _fillable_to_straight_four(cells), (
                f"{render(cells)} 判為眠三/跳三卻仍有填法能成活四"
            )
            assert _fillable_to_rush_four(cells), (
                f"{render(cells)} 判為眠三/跳三卻連衝四都成不了"
            )

    def test_solid_and_jump_split_by_run_length(self, classify_c):
        """實心與跳型的區分：4/8 與 3/7/13 是實心，10/12 與 9/11/14 有缺口。"""
        for idx in range(TABLE_SIZE):
            cells = decode(idx)
            code = classify_c(cells)
            run = _true_run(cells)
            if code in (4, 8):
                assert run == 4, f"{render(cells)} 判為實心四級但 run={run}"
            elif code in (10, 12):
                assert run != 4, f"{render(cells)} 判為跳四級但 run={run}"
            elif code in (3, 7, 13):
                assert run == 3, f"{render(cells)} 判為實心三級但 run={run}"
            elif code in (9, 11, 14):
                assert run != 3, f"{render(cells)} 判為跳三級但 run={run}"


# --------------------------------------------------------------------------
# 手工 spot check
# --------------------------------------------------------------------------
class TestKnownShapes:
    @pytest.mark.parametrize("window,expected", [
        ("OOOSSSSSOOO", 5),    # 恰五
        ("OOOOSSSSSOO", 5),    # 貼牆恰五
        ("SSSSSSSSSSS", 15),   # 長連
        ("OOOOSSSS.OO", 8),    # 一端封死，只剩一個成五點 -> 衝四
        ("OOO.SSSS.OO", 4),    # 兩端開，兩個成五點 -> 活四
        ("OOO.SS.SS.O", 12),   # 補中間即成五，只有一個成五點 -> 跳四
        ("....SSS....", 3),    # 兩側空間充足，兩種成活四填法 -> 活三
        ("...S.SS....", 11),   # 隔空三子，兩端仍開，只有一種成活四填法 -> 偏活跳三
        ("OOO.SSS.OOO", 7),    # 兩側都只隔一格就是牆，兩個延伸點都只能成衝四 -> 純衝四眠三
        ("OOOO.SS.OOO", 2),    # 二級不走 RIF，沿用現行判法 -> 活二
        (".....SSSO..", 7),    # 緊貼牆，唯一延伸點只能成衝四 -> 純衝四眠三
        (".....SSS.O.", 13),   # 隔空一格才被擋，另一端仍能成活四 -> 偏活三
        ("...OSS.S...", 14),   # 跳三形狀但一端緊貼牆，缺口填了只成衝四 -> 純衝四跳三（曾誤判 0）
    ])
    def test_spot(self, classify_c, window, expected):
        cells = [{"S": SELF, "O": OPP, ".": EMPTY}[ch] for ch in window]
        assert cells[CENTER] == SELF
        assert classify_c(cells) == expected

    def test_locked_solid_three_now_classifies_as_chong_only_mianthree(self, classify_c):
        """緊貼牆的實心三：唯一延伸點只能成衝四，曾被 threePoints 判成 tp==0
        後直接落到 classifyMinor 回傳 0（棋型完全消失）。現由 rushPoints 接住，
        分類成眠三（7），權重應明顯低於偏活三（13）。"""
        cells = [{"S": SELF, "O": OPP, ".": EMPTY}[ch] for ch in ".....SSSO.."]
        assert classify_c(cells) == 7

    def test_locked_jump_three_now_classifies_as_chong_only_tiaothree(self, classify_c):
        """緊貼牆的跳三：唯一的缺口填了只能成衝四（另一端被牆鎖死），
        曾回傳 0，是 loss-analysis-jump-three-gap.md 記錄的漏防根因之一。
        現由 rushPoints 接住，分類成跳三（14）。"""
        cells = [{"S": SELF, "O": OPP, ".": EMPTY}[ch] for ch in "...OSS.S..."]
        assert classify_c(cells) == 14

    def test_open_jump_three_stays_eleven_not_locked(self, classify_c):
        """對照組：同一組跳三棋子，兩端都不緊貼牆 -> 仍是偏活跳三（11），
        缺口填了會變兩端全開的活四，緊急程度跟活三同級，不該與 14 混在一起。"""
        cells = [{"S": SELF, "O": OPP, ".": EMPTY}[ch] for ch in "....SS.S..."]
        assert classify_c(cells) == 11

    def test_open_three_solid(self, classify_c):
        # ...SSS..... 兩側空間足夠成活四 -> 活三
        cells = [EMPTY, EMPTY, EMPTY, SELF, SELF, SELF, EMPTY, EMPTY, EMPTY,
                 EMPTY, EMPTY]
        assert render(cells) == "...SSS....."
        assert classify_c(cells) == 3

    def test_open_four_solid(self, classify_c):
        # .SSSS. 兩端開 -> 活四
        cells = [OPP, OPP, OPP, EMPTY, SELF, SELF, SELF, SELF, EMPTY, OPP, OPP]
        assert classify_c(cells) == 4

    def test_jump_open_three_looking_shape_is_not_a_three(self, classify_c):
        """...S.SS.S.. 形似跳三，實際上不是三，只能成衝四。

        填 index4 或 index7 表面上各自湊出兩個成五點，但其中一個成五點
        會拉到 6 連（長連），恰好五守衛補上前這個窗口曾誤判為碼 9。
        """
        cells = [EMPTY, EMPTY, EMPTY, SELF, EMPTY, SELF, SELF, EMPTY, SELF,
                 EMPTY, EMPTY]
        assert render(cells) == "...S.SS.S.."
        assert classify_c(cells) == 14

    def test_jump_open_three(self, classify_c):
        # ..S.SS..S.. 兩側都能補成恰好五連的活四 -> 跳活三
        cells = [EMPTY, EMPTY, SELF, EMPTY, SELF, SELF, EMPTY, EMPTY, SELF,
                 EMPTY, EMPTY]
        assert render(cells) == "..S.SS..S.."
        assert classify_c(cells) == 9

    def test_blocked_three_reaches_only_chong_four(self, classify_c):
        """兩側被夾死的三連成不了活四，依 RIF 不是三——但兩個延伸點都還能
        成衝四，不是完全沒有棋型；曾誤判回傳 0，現由 rushPoints 接住成眠三。"""
        cells = [OPP, OPP, OPP, EMPTY, SELF, SELF, SELF, EMPTY, OPP, OPP, OPP]
        assert render(cells) == "OOO.SSS.OOO"
        assert classify_c(cells) == 7

    def test_gap_separated_far_stone_does_not_hide_five(self, classify_c):
        # ....SSSSS.S : 中心的實五 + 一顆隔空遠子（gaps==1），仍須認得五連
        cells = list(decode(361))
        assert render(cells) == "....SSSSS.S"
        assert classify_c(cells) == 5
        assert classify_window_twin(cells) == 5


# --------------------------------------------------------------------------
# 把「patternTable 可以取代 maxRunAt」的推導寫成測試
# --------------------------------------------------------------------------
# judgeMove 曾經呼叫 maxRunAt 逐格外掃來判五連/長連，現已改成直接讀
# patternTable 的代碼 5（恰五）與 15（長連，>=6）。這裡證明兩者等價。
# maxRunAt 本身不刪，留著當參考實作，這裡的測試繼續呼叫它、繼續有意義。
def solidRun(cells):
    """穿過中心的連續 SELF 長度，與 `_true_run` 各自獨立寫成，供對拍。

    做法不同於 `_true_run`（逐格 for-break）：這裡把中心兩側切成兩段
    子串列，用 `itertools.takewhile` 數各自能連續匹配 SELF 的前綴長度，
    兩段前綴長度相加再加中心本身。
    """
    left_side = cells[CENTER - 1::-1]     # 中心左側，由近到遠
    right_side = cells[CENTER + 1:]       # 中心右側，由近到遠
    left_run = sum(1 for _ in itertools.takewhile(lambda c: c == SELF, left_side))
    right_run = sum(1 for _ in itertools.takewhile(lambda c: c == SELF, right_side))
    return left_run + 1 + right_run


class TestSolidRunTwin:
    """`solidRun` 自身的健檢：先確定這份獨立實作没寫錯，再拿去對拍。"""

    def test_matches_true_run_reference_on_known_shapes(self):
        # 這裡刻意跟 _true_run 對一次，確保兩份「結構不同」的實作對得上，
        # 但下面的全枚舉對拍不再依賴 _true_run，直接對 classifyWindow。
        cases = [
            ".....S.....",
            "SSSSSSSSSSS",
            "OOOSSSSSOOO",
            "OOOOSSSSSOO",
            "...SSS.....",
            "OOO.SSS.OOO",
            "..S.S.S.S..",
        ]
        for window in cases:
            cells = [{"S": SELF, "O": OPP, ".": EMPTY}[ch] for ch in window]
            assert solidRun(cells) == _true_run(cells), window


class TestWindowLayerFiveAndOverlineEquivalence:
    """窗口層全枚舉：`classifyWindow` 的代碼 5/15 等價於 `solidRun` 的 5 / >=6。

    對拍對象是 `classify_c`（即 `classifyWindow`），不是 `classify_window_twin`——
    後者本身也是重寫的推導，這裡要單獨驗證「五連/長連代碼」與「連續子數」
    這組更窄、更貼近 maxRunAt 語意的等價關係，避免把兩層獨立實作的誤差疊在一起看。
    """

    def test_code_five_iff_solid_run_five(self, classify_c):
        mismatches = []
        for idx in range(TABLE_SIZE):
            cells = decode(idx)
            code = classify_c(cells)
            run = solidRun(cells)
            if (code == 5) != (run == 5):
                mismatches.append((idx, render(cells), code, run))
        report = "\n".join(
            f"  idx={i:5d} {w}  code={c} solidRun={r}" for i, w, c, r in mismatches[:60]
        )
        assert not mismatches, (
            f"{len(mismatches)} / {TABLE_SIZE} 筆 code==5 與 solidRun==5 不等價:\n{report}"
        )

    def test_code_overline_iff_solid_run_at_least_six(self, classify_c):
        mismatches = []
        for idx in range(TABLE_SIZE):
            cells = decode(idx)
            code = classify_c(cells)
            run = solidRun(cells)
            if (code == 15) != (run >= 6):
                mismatches.append((idx, render(cells), code, run))
        report = "\n".join(
            f"  idx={i:5d} {w}  code={c} solidRun={r}" for i, w, c, r in mismatches[:60]
        )
        assert not mismatches, (
            f"{len(mismatches)} / {TABLE_SIZE} 筆 code==13 與 solidRun>=6 不等價:\n{report}"
        )


# --------------------------------------------------------------------------
# ctypes fixture：maxRunAt（board 層對拍才需要，Step 2 之前的 fixture 都不用它）
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def max_run_at(lib):
    """回傳 max_run_at(board, x, y, player) -> (run, hasFive)。"""
    board_max = lib.getBoardMax()
    board_type = (ctypes.c_int * board_max) * board_max
    lib.maxRunAt.restype = ctypes.c_int
    lib.maxRunAt.argtypes = [
        ctypes.POINTER(board_type),
        ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(ctypes.c_int),
    ]

    def _call(board, x, y, player):
        has_five = ctypes.c_int(0)
        run = lib.maxRunAt(ctypes.byref(board), x, y, player, ctypes.byref(has_five))
        return run, has_five.value

    _call.board_max = board_max
    _call.board_type = board_type
    return _call


@pytest.fixture(scope="module")
def check_line_full(lib):
    """回傳 check_line_full(board, x, y, player) -> my_line[16] 的 list。

    跟既有的 `check_line` fixture 不同：這裡吃真正的整個盤面（不是單一窗口
    臨時搭出來的水平線），給板級差分測試用，四個方向都真實參與。
    """
    board_max = lib.getBoardMax()
    board_type = (ctypes.c_int * board_max) * board_max
    lib.checkLine.restype = None
    lib.checkLine.argtypes = [
        ctypes.POINTER(board_type),
        ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(ctypes.c_int * 16),
    ]

    def _call(board, x, y, player):
        my_line = (ctypes.c_int * 16)()
        lib.checkLine(ctypes.byref(board), x, y, player, my_line)
        return list(my_line)

    _call.board_max = board_max
    _call.board_type = board_type
    return _call


# --------------------------------------------------------------------------
# 板級差分：真實盤面上，maxRunAt 與 checkLine 的五連/長連判斷要一致
# --------------------------------------------------------------------------
def _empty_board(board_type, board_max):
    board = board_type()
    for y in range(board_max):
        for x in range(board_max):
            board[y][x] = EMPTY
    return board


def _make_random_boards(board_type, board_max, seeds):
    """隨機盤面：固定種子、隨機撒子（含兩色），拿來覆蓋一般雜亂局面。"""
    boards = []
    for seed in seeds:
        rng = random.Random(seed)
        board = _empty_board(board_type, board_max)
        # 撒約三成格子，兩色都有，密度夠高才容易湊出五連/長連附近的形狀
        for y in range(board_max):
            for x in range(board_max):
                roll = rng.random()
                if roll < 0.15:
                    board[y][x] = BLACK
                elif roll < 0.30:
                    board[y][x] = WHITE
        boards.append(board)
    return boards


def _make_edge_run_boards(board_type, board_max):
    """貼邊/貼角的連續長條：長度涵蓋 3..8，跨過牆截斷與五/六/七連的邊界。

    分別沿最上一列（貼上邊）與最左一欄（貼左邊，且從角落 (0,0) 起跳）鋪子，
    確保窗口在牆邊被截斷時，maxRunAt 與 checkLine 依然一致。
    """
    boards = []
    for length in range(3, 9):
        # 貼上邊的水平長條，從最左邊開始鋪，長度不超過盤面寬度
        length_h = min(length, board_max)
        board = _empty_board(board_type, board_max)
        for x in range(length_h):
            board[0][x] = BLACK
        boards.append(board)

        # 貼左邊、從角落開始的垂直長條
        length_v = min(length, board_max)
        board = _empty_board(board_type, board_max)
        for y in range(length_v):
            board[y][0] = WHITE
        boards.append(board)
    return boards


def _make_diagonal_boards(board_type, board_max):
    """主對角線與副對角線各鋪一條連續長條，覆蓋 checkLine 的另外兩個方向。"""
    boards = []
    for length in range(3, 9):
        n = min(length, board_max)

        # 主對角線（左上到右下），從 (0,0) 開始
        board = _empty_board(board_type, board_max)
        for i in range(n):
            board[i][i] = BLACK
        boards.append(board)

        # 副對角線（右上到左下），從 (board_max - 1, 0) 開始
        board = _empty_board(board_type, board_max)
        for i in range(n):
            board[i][board_max - 1 - i] = WHITE
        boards.append(board)
    return boards


class TestBoardLevelMaxRunAtEquivalence:
    """板級差分：對每個空格、兩個視角，maxRunAt 與 checkLine 的五連/長連判斷要相符。

    覆蓋隨機盤面、貼邊長條、對角線三類，專門去戳窗口被牆截斷、以及
    5/6/7 子邊界這幾個歷史上容易出錯的地方。
    """

    @pytest.fixture(scope="class")
    def boards(self, max_run_at):
        board_type = max_run_at.board_type
        board_max = max_run_at.board_max
        boards = []
        boards += _make_random_boards(board_type, board_max, seeds=(1, 2, 3))
        boards += _make_edge_run_boards(board_type, board_max)
        boards += _make_diagonal_boards(board_type, board_max)
        return boards

    def test_has_five_matches_checkline_slot_five(self, max_run_at, check_line_full, boards):
        board_max = max_run_at.board_max
        mismatches = []
        for board in boards:
            for y in range(board_max):
                for x in range(board_max):
                    if board[y][x] != EMPTY:
                        continue
                    for player in (BLACK, WHITE):
                        _, has_five = max_run_at(board, x, y, player)
                        my_line = check_line_full(board, x, y, player)
                        if bool(has_five) != (my_line[5] > 0):
                            mismatches.append((x, y, player, has_five, my_line[5]))
        report = "\n".join(
            f"  x={x} y={y} player={p} hasFive={h} line[5]={l}"
            for x, y, p, h, l in mismatches[:40]
        )
        assert not mismatches, (
            f"{len(mismatches)} 筆 hasFive 與 checkLine[5] 不等價:\n{report}"
        )

    def test_overline_run_matches_checkline_slot_fifteen(self, max_run_at, check_line_full, boards):
        board_max = max_run_at.board_max
        mismatches = []
        for board in boards:
            for y in range(board_max):
                for x in range(board_max):
                    if board[y][x] != EMPTY:
                        continue
                    for player in (BLACK, WHITE):
                        run, _ = max_run_at(board, x, y, player)
                        my_line = check_line_full(board, x, y, player)
                        if (run > 5) != (my_line[15] > 0):
                            mismatches.append((x, y, player, run, my_line[15]))
        report = "\n".join(
            f"  x={x} y={y} player={p} run={r} line[15]={l}"
            for x, y, p, r, l in mismatches[:40]
        )
        assert not mismatches, (
            f"{len(mismatches)} 筆 run>5 與 checkLine[15] 不等價:\n{report}"
        )
