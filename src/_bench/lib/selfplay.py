"""自動對弈：兩個 ai.dll 互戰 N 局，統計勝負。棋力改動的迴歸驗證工具。

用法:
    python selfplay.py <dllA> <dllB> [games=20] [--quiet]

注意: dllA/dllB 必須是不同檔案路徑。ctypes 對同一路徑回傳同一個已載入
模組，兩個「引擎」會共用同一份 transpositionTable / currentZobristKey。
比較同一份 dll 的兩個複本時，先各自 copy 成不同檔名。

為什麼需要這個工具（而不是用 ab_fresh.py）:
    ab_fresh.py 比對「兩版是否回傳相同走法」，只適用於行為保持型的改動。
    A5b 這類**刻意改變棋力**的改動，走法本來就會不同，只能靠對打統計勝率。

用途二: 同一套 harness 也是產生訓練棋譜的基礎；
    加 --pgn <file> 可把每局走法序列與結果存檔供後續分析/調參使用。
"""
import ctypes
import os
import sys

# 腳本化開局池（黑1中心、白2在3x3內、黑3在5x5內），以中心點的偏移表示。
#
# 為什麼開局池要夠大：引擎是**確定性**的（Zobrist 種子固定、每局開始清空置換表，
# 白棋第2手的 srand(time(NULL)) 分支又被腳本化開局繞過），所以同一個開局永遠打出
# 同一盤棋。games 開超過 2 × 開局數只是把同樣的對局重播一次，勝率不會變得更可信；
# 要提高統計解析度只能加開局，不能加局數。
#
# 座標來自 RIF 官方開局形（openings_rif.py，含轉錄正確性驗證），104 組 = 208 局滿配對。
from openings_rif import OPENINGS as OPENING_OFFSETS

MAX_ROUNDS = 250

# 棋盤大小由 dll 的 getBoardMax() 決定（ai.c 是唯一定義處），首次 load() 時填入
BOARD_MAX = None
CBoard = None


def openings():
    c = BOARD_MAX // 2
    return [[(c + dx, c + dy, p) for dx, dy, p in o] for o in OPENING_OFFSETS]


def load(path):
    global BOARD_MAX, CBoard
    if not os.path.exists(path):
        sys.exit(f"error: dll not found: {path}")
    lib = ctypes.CDLL(path)
    try:
        lib.getBoardMax.restype = ctypes.c_int
        size = lib.getBoardMax()
    except AttributeError:
        sys.exit(f"error: {path} 沒有 export getBoardMax()，無法得知它編譯時用的棋盤大小。\n"
                 f"       不確定兩顆 dll 在同樣大小的棋盤上比較時，數據沒有意義。\n"
                 f"       請改用有 getBoardMax() 的版本當基準。")
    if BOARD_MAX is None:
        BOARD_MAX = size
        CBoard = (ctypes.c_int * BOARD_MAX) * BOARD_MAX
    elif size != BOARD_MAX:
        sys.exit(f"error: 兩顆 dll 的棋盤大小不同（{BOARD_MAX} vs {size}），無法對比")
    lib.initZobristTable.restype = None
    lib.initTranspositionTable.restype = None
    lib.aiRound.restype = None
    lib.aiRound.argtypes = [ctypes.POINTER(CBoard), ctypes.c_int, ctypes.c_int,
                            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
    lib.initZobristTable()
    return lib


def line_len(board, x, y, dx, dy, p):
    n = 1
    for s in (1, -1):
        i = 1
        while True:
            nx, ny = x + dx * i * s, y + dy * i * s
            if not (0 <= nx < BOARD_MAX and 0 <= ny < BOARD_MAX) or board[ny][nx] != p:
                break
            n += 1
            i += 1
    return n


def judge(board, x, y, p):
    """回傳 'win' / 'foul'（黑棋長連違規）/ None。

    注意：這是 Python 端的獨立判定，與 C 端 checkUnValid 是兩份實作。
    禁手判負的局會被記錄下來（見 main 的 fouls 統計），建議抽樣人工複核
    兩邊判定是否一致。不一致會產生假性敗局，污染勝率。
    """
    for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
        n = line_len(board, x, y, dx, dy, p)
        if n == 5 or (n > 5 and p == 2):
            return 'win'
        if n > 5 and p == 1:
            return 'foul'
    return None


def play_game(black, white, opening, verbose=True):
    """回傳 (winner, moves, reason)。winner: 1=黑 2=白 0=和局。"""
    board = [[0] * BOARD_MAX for _ in range(BOARD_MAX)]
    moves = []
    for (x, y, p) in opening:
        board[y][x] = p
        moves.append((x, y, p))

    # 每局開始清空置換表，避免上一局的 entry 殘留污染本局（TT 是跨回合保留的）
    for eng in (black, white):
        eng.initTranspositionTable()

    rc = len(opening) + 1
    engines = {1: black, 2: white}
    while rc <= MAX_ROUNDS:
        if len(moves) == BOARD_MAX * BOARD_MAX:  # 盤面下滿、無人連五：和局，不算非法
            return 0, moves, 'boardfull'
        p = 1 if rc % 2 == 1 else 2
        cb = CBoard()
        for i in range(BOARD_MAX):
            for j in range(BOARD_MAX):
                cb[i][j] = board[i][j]
        bx, by = ctypes.c_int(-1), ctypes.c_int(-1)
        engines[p].aiRound(ctypes.byref(cb), p, rc, ctypes.byref(bx), ctypes.byref(by))
        x, y = bx.value, by.value

        # 哨兵值：引擎找不到合法走法，不是犯規，當和局處理
        if x == -1 and y == -1:
            return 0, moves, 'nomove'

        if not (0 <= x < BOARD_MAX and 0 <= y < BOARD_MAX) or board[y][x] != 0:
            if verbose:
                print(f"    ILLEGAL move ({x},{y}) by player {p} at round {rc}")
            return 3 - p, moves, 'illegal'

        board[y][x] = p
        moves.append((x, y, p))
        r = judge(board, x, y, p)
        if r == 'win':
            return p, moves, 'five'
        if r == 'foul':
            if verbose:
                print(f"    black FOUL (overline) at round {rc}")
            return 2, moves, 'foul'
        rc += 1
    return 0, moves, 'maxrounds'


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    a_path, b_path = sys.argv[1], sys.argv[2]
    rest = [a for a in sys.argv[3:] if not a.startswith('--')]
    games = int(rest[0]) if rest else 20
    quiet = '--quiet' in sys.argv
    pgn = None
    if '--pgn' in sys.argv:
        pgn = sys.argv[sys.argv.index('--pgn') + 1]

    if os.path.abspath(a_path) == os.path.abspath(b_path):
        sys.exit("error: both paths point to the same file; ctypes would share one "
                 "module (and one transposition table). Copy the dll to a second name.")

    A, B = load(a_path), load(b_path)
    score = {a_path: 0.0, b_path: 0.0}
    reasons = {}
    records = []
    all_openings = openings()

    # 配對開局：同一個開局打兩局、雙方各執一次黑，成績成對相消開局本身的偏差。
    for g in range(games):
        opening = all_openings[(g // 2) % len(all_openings)]
        a_is_black = (g % 2 == 0)
        black_path, white_path = (a_path, b_path) if a_is_black else (b_path, a_path)
        black, white = (A, B) if a_is_black else (B, A)

        w, moves, reason = play_game(black, white, opening, verbose=not quiet)
        reasons[reason] = reasons.get(reason, 0) + 1
        if w == 1:
            score[black_path] += 1
            res = f"black wins  [{os.path.basename(black_path)}]"
        elif w == 2:
            score[white_path] += 1
            res = f"white wins  [{os.path.basename(white_path)}]"
        else:
            score[a_path] += 0.5
            score[b_path] += 0.5
            res = "draw"
        records.append((moves, w))
        if not quiet:
            print(f"  game {g+1}/{games}: {res}  ({reason}, {len(moves)} moves)")

    print(f"\n=== {games} games ===")
    for p, s in score.items():
        print(f"  {os.path.basename(p):24} {s:5.1f}  ({s/games*100:.1f}%)")
    print(f"  endings: {reasons}")
    if games > 2 * len(all_openings):
        print(f"  WARNING: 開局池只有 {len(all_openings)} 個，超過 {2 * len(all_openings)} 局之後"
              f"只是重播同樣的對局（引擎是確定性的），勝率不會更可信")
    if reasons.get('illegal'):
        print("  WARNING: illegal moves occurred -- engine or harness bug, results unreliable")
    if reasons.get('foul'):
        print("  NOTE: black foul losses occurred -- spot-check C vs Python forbidden-move "
              "agreement before trusting the win rate")

    if pgn:
        with open(pgn, 'w', encoding='utf-8') as f:
            for moves, w in records:
                f.write(' '.join(f"{x},{y},{p}" for x, y, p in moves) + f" result={w}\n")
        print(f"  wrote {len(records)} games to {pgn}")


if __name__ == "__main__":
    main()
