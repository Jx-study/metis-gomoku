"""RIF 標準開局池：104 組合法開局座標，供 selfplay.py 使用。

為什麼用 RIF 開局:
    引擎是確定性的，獨立對局數 = 2 × 開局數，開局數決定勝率解析度。
    RIF（Renju International Federation）官方開局形共 104 組 = 208 局。

座標系: 以黑1為原點的 (dx, dy) 偏移，selfplay.openings() 再平移到棋盤中心。

RIF「26 種」與這裡「104 組」的關係:
    RIF 把旋轉/鏡像對稱的開局算作同一種，口徑是 13 直接 + 13 間接 = 26 種。
    這裡不做對稱去重，把每種的 4 個旋轉方向都展開，得到 26 × 4 = 104 組不重複座標。
    需要去重後的 26 種時用 CANONICAL_OPENINGS（見文末說明，兩者的取捨不同）。
"""

# --- 基準形 -----------------------------------------------------------------
# 人工核對 renju.net 官方開局規則圖（rul5.gif 間接、rul6.gif 直接）的像素座標而來。
# 每個基準形只列白2的一個方向，其餘 3 個方向由 90° 旋轉生成（棋盤有 4 折旋轉對稱）。
#
# 為什麼各只有 13 個黑3（而不是 5x5 扣掉黑1白2的 23 個）:
#     沿「黑1-白2」這條軸鏡射後重合的開局，RIF 視為同一種、只收錄一個代表。
#     23 個位置裡有 3 個落在軸上（自己鏡射到自己）、其餘 20 個兩兩成對 -> 3 + 10 = 13。
#     _verify_mirror_classes() 檢查這個性質。
#     它比合法性檢查強，因為合法性只能抓到「填了非法格」。
#     但它的偵錯範圍有邊界，實測（mutation testing）結果如下:
#       - 抄成別的鏡射類的合法格 -> 抓得到。
#         該類沒有代表，種類數會變成 != 26。
#       - 抄成同一類的鏡射搭檔（例如直接形的 (1,-1) <-> (-1,-1)）-> 抓不到。
#         因為「每類恰好一個代表」仍然成立。
#         但這不影響統計性質：換代表後 _canonical() 的正規形集合完全不變，
#         26 個 RIF 種類的覆蓋是一樣的。
#     換句話說，這組檢查保證的是「種類覆蓋正確」，
#     不是「與 RIF 圖逐格相同」。

INDIRECT_W2 = (1, -1)   # 間接開局：白2走對角
INDIRECT_B3 = [
    (2, -2), (2, -1), (1, 0), (2, 0), (-1, 1), (0, 1), (1, 1),
    (2, 1), (-2, 2), (-1, 2), (0, 2), (1, 2), (2, 2),
]

DIRECT_W2 = (0, -1)     # 直接開局：白2走直線
DIRECT_B3 = [
    (0, -2), (1, -2), (2, -2), (1, -1), (2, -1), (1, 0), (2, 0),
    (0, 1), (1, 1), (2, 1), (0, 2), (1, 2), (2, 2),
]

BLACK, WHITE = 1, 2


# --- 對稱操作 ---------------------------------------------------------------

def rotate90(p):
    """繞原點逆時針 90 度：(x, y) -> (-y, x)。"""
    x, y = p
    return (-y, x)


def reflect(p, axis):
    """把 p 沿「原點到 axis」這條直線鏡射。

    向量投影公式 v' = 2(v.u)u - v，u 是 axis 的單位向量。
    這裡 axis 的分量都是 0/±1，所以 2(v.axis)/|axis|^2 必為整數，不會有浮點誤差。
    """
    ax, ay = axis
    x, y = p
    k = 2 * (x * ax + y * ay)
    d = ax * ax + ay * ay
    assert k % d == 0, f"鏡射產生非整數座標: {p} 沿 {axis}"
    k //= d
    return (k * ax - x, k * ay - y)


def _canonical(opening):
    """回傳開局在 D4（4 旋轉 x 2 鏡射 = 8 個對稱操作）下的正規形。

    兩個開局的正規形相同 <=> 它們是同一個 RIF 開局種類。用來數種類數、做去重。
    """
    _, (wx, wy, _), (bx, by, _) = opening
    variants = []
    for mirrored in (False, True):
        w, b = (wx, wy), (bx, by)
        if mirrored:
            w, b = reflect(w, (1, 0)), reflect(b, (1, 0))
        for _ in range(4):
            variants.append((w, b))
            w, b = rotate90(w), rotate90(b)
    return min(variants)


# --- 生成 -------------------------------------------------------------------

def _build(w2, thirds):
    """把一個基準形旋轉成 4 個白2方向，每個方向配 13 個黑3 -> 52 組。"""
    out = []
    for _ in range(4):
        for b3 in thirds:
            out.append([(0, 0, BLACK), (w2[0], w2[1], WHITE), (b3[0], b3[1], BLACK)])
        w2 = rotate90(w2)
        thirds = [rotate90(b) for b in thirds]
    return out


INDIRECT_OPENINGS = _build(INDIRECT_W2, INDIRECT_B3)
DIRECT_OPENINGS = _build(DIRECT_W2, DIRECT_B3)
OPENINGS = INDIRECT_OPENINGS + DIRECT_OPENINGS

# 每個 RIF 種類只留一個代表（26 組）。
# 完整池的 104 組裡，每 4 組互為旋轉/鏡像，對稱的局面下出來的棋高度相關，
# 所以 104 組不等於 104 份獨立樣本。
# 需要「保證彼此獨立」時用這份；需要最大局數時用 OPENINGS。
CANONICAL_OPENINGS = list({_canonical(o): o for o in OPENINGS}.values())


# --- 自我驗證（import 時執行；集合只有 104 組，成本可忽略）---------------------

def _verify_legal():
    """開局規則: 黑1中心、白2在 3x3 內、黑3在 5x5 內，三點互不重疊。"""
    for o in OPENINGS:
        (b1x, b1y, b1p), (wx, wy, wp), (bx, by, bp) = o
        assert (b1x, b1y, b1p) == (0, 0, BLACK), f"黑1不在中心: {o}"
        assert (wp, bp) == (WHITE, BLACK), f"顏色錯誤: {o}"
        assert max(abs(wx), abs(wy)) == 1, f"白2不在 3x3 內: {o}"
        assert max(abs(bx), abs(by)) <= 2, f"黑3不在 5x5 內: {o}"
        assert len({(b1x, b1y), (wx, wy), (bx, by)}) == 3, f"座標重疊: {o}"


def _verify_counts():
    """組數與不重複性。"""
    assert len(INDIRECT_OPENINGS) == 52, f"間接開局 {len(INDIRECT_OPENINGS)} 組，應為 52"
    assert len(DIRECT_OPENINGS) == 52, f"直接開局 {len(DIRECT_OPENINGS)} 組，應為 52"
    assert len(OPENINGS) == 104, f"總數 {len(OPENINGS)} 組，應為 104"
    keys = {(tuple(o[1][:2]), tuple(o[2][:2])) for o in OPENINGS}
    assert len(keys) == 104, f"有重複開局：{len(keys)} 組不重複，應為 104"
    assert len(CANONICAL_OPENINGS) == 26, \
        f"RIF 種類數 {len(CANONICAL_OPENINGS)}，應為 26（13 直接 + 13 間接）"

    # 每個 RIF 種類必須剛好 4 個變體。
    # 104/26=4 只保證平均值，這裡檢查的是每一類都均勻：
    # 某類 3 個、某類 5 個會讓開局池對某些棋型過度取樣，
    # 是生成迴圈寫錯才會有的徵狀。
    sizes = {}
    for o in OPENINGS:
        k = _canonical(o)
        sizes[k] = sizes.get(k, 0) + 1
    assert set(sizes.values()) == {4}, f"各 RIF 種類的變體數不均勻: {sorted(set(sizes.values()))}"


def _verify_mirror_classes():
    """轉錄正確性: 13 個黑3必須是 23 個合法位置在「沿白2軸鏡射」下的完整代表元集合。

    抄錯成別類的座標會破壞這個性質（某類沒代表、某類有兩個），
    所以這比合法性檢查強，合法性只能抓到「填了非法格」。
    但抄成同一類的鏡射搭檔抓不到，因為那仍然是合法的代表選擇；
    那種情況也不影響種類覆蓋（見檔頭的實測說明）。
    """
    for name, w2, thirds in (("間接", INDIRECT_W2, INDIRECT_B3),
                             ("直接", DIRECT_W2, DIRECT_B3)):
        legal = {(x, y) for x in range(-2, 3) for y in range(-2, 3)} - {(0, 0), w2}
        assert len(legal) == 23, f"{name}: 合法黑3位置 {len(legal)} 個，應為 23"

        classes = {frozenset({p, reflect(p, w2)}) for p in legal}
        assert len(classes) == 13, f"{name}: 鏡射等價類 {len(classes)} 個，應為 13"

        covered = set()
        for p in thirds:
            assert p in legal, f"{name}: 黑3 {p} 不是合法位置"
            cls = frozenset({p, reflect(p, w2)})
            assert cls not in covered, f"{name}: 黑3 {p} 與清單中另一點互為鏡像（重複收錄）"
            covered.add(cls)
        assert covered == classes, \
            f"{name}: 有 {len(classes - covered)} 個等價類沒有代表（漏抄座標）"


_verify_legal()
_verify_counts()
_verify_mirror_classes()


if __name__ == "__main__":
    def render(opening):
        pieces = {(x, y): p for x, y, p in opening}
        rows = []
        for y in range(-2, 3):
            rows.append(''.join(
                {1: ' X', 2: ' O'}.get(pieces.get((x, y)), ' .') for x in range(-2, 3)))
        return rows

    print(f"間接開局 {len(INDIRECT_OPENINGS)} 組")
    print(f"直接開局 {len(DIRECT_OPENINGS)} 組")
    print(f"合計     {len(OPENINGS)} 組  (RIF 種類數 {len(CANONICAL_OPENINGS)}，"
          f"每種 {len(OPENINGS) // len(CANONICAL_OPENINGS)} 個旋轉/鏡像變體)")
    print("驗證: 合法性 / 組數不重複且各類均勻 / 鏡射等價類完整性  全部通過\n")
    print("抽查（X=黑 O=白，5x5 視窗，中心為黑1）:")
    for idx in (0, 12, 51, 52, 64, 103):
        o = OPENINGS[idx]
        print(f"\n  [{idx}] 白2={o[1][:2]}  黑3={o[2][:2]}")
        for row in render(o):
            print(f"      {row}")
