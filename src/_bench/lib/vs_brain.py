"""ai.dll 對 Piskvork 協定引擎（Rapfi 等 pbrain）對打，量測與外部引擎的棋力差距。

用法:
    python vs_brain.py <ai.dll> <brain.exe> [games=20] [選項]

選項:
    --ms N | --ms auto   對方每手時間（毫秒）；auto 取我方目前的平均每手耗時，預設 auto
    --info KEY=VAL       額外送給對方的 INFO，可重複，例如 --info max_depth=6 --info max_node=20000
    --threads N          對方執行緒數，預設 1
    --pgn FILE           每局走法存檔，格式同 selfplay.py
    --log                印出對方的 MESSAGE / DEBUG 輸出
    --quiet              不印逐局結果

規則固定 Renju（INFO rule 4）。開局沿用 selfplay 的 RIF 開局池，同一開局打兩局、黑白互換。
勝負與黑棋禁手由本檔的 Python 裁判判定，不呼叫 ai.dll 的 checkUnValid，避免引擎自己當裁判。
"""
import ctypes
import math
import os
import queue
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import selfplay  # noqa: E402

MAX_ROUNDS = 250
REPLY_TIMEOUT_SLACK = 30.0  # 對方超過時限這麼多秒仍無回應就判負
DIRS = ((1, 0), (0, 1), (1, 1), (1, -1))
N = None


# Renju 裁判
def inb(x, y):
    return 0 <= x < N and 0 <= y < N


def line_len(board, x, y, dx, dy, p):
    n = 1
    for s in (1, -1):
        i = 1
        while inb(x + dx * i * s, y + dy * i * s) and board[y + dy * i * s][x + dx * i * s] == p:
            n += 1
            i += 1
    return n


def five_points(board, x, y, dx, dy):
    """(x,y) 所在直線上，補一子即成恰好五連且包含 (x,y) 的空點。"""
    pts = set()
    for k in range(-4, 1):
        cells = [(x + dx * (k + i), y + dy * (k + i)) for i in range(5)]
        if not all(inb(cx, cy) for cx, cy in cells):
            continue
        vals = [board[cy][cx] for cx, cy in cells]
        if vals.count(1) == 4 and vals.count(0) == 1:
            ex, ey = cells[vals.index(0)]
            board[ey][ex] = 1
            if line_len(board, ex, ey, dx, dy, 1) == 5:
                pts.add((ex, ey))
            board[ey][ex] = 0
    return pts


def _gap(a, b, dx, dy):
    return abs(a[0] - b[0]) if dx else abs(a[1] - b[1])


def fours_in_dir(board, x, y, dx, dy):
    pts = list(five_points(board, x, y, dx, dy))
    if len(pts) == 2 and _gap(pts[0], pts[1], dx, dy) == 5:
        return 1  # 活四只算一個四
    return len(pts)


def is_straight_four(board, x, y, dx, dy):
    pts = list(five_points(board, x, y, dx, dy))
    return len(pts) == 2 and _gap(pts[0], pts[1], dx, dy) == 5


def three_in_dir(board, x, y, dx, dy, depth):
    # 活三：存在一個非禁手的空點，補上後成活四；該點若在任一方向成五，落下去是五連而非活四
    for k in range(-4, 5):
        ex, ey = x + dx * k, y + dy * k
        if k == 0 or not inb(ex, ey) or board[ey][ex] != 0:
            continue
        board[ey][ex] = 1
        ok = (all(line_len(board, ex, ey, ddx, ddy, 1) != 5 for ddx, ddy in DIRS)
              and is_straight_four(board, x, y, dx, dy)
              and not is_foul(board, ex, ey, depth + 1))
        board[ey][ex] = 0
        if ok:
            return True
    return False


def is_foul(board, x, y, depth=0):
    """黑子已落在 (x,y)：是否為禁手。成五優先於禁手。"""
    lens = [line_len(board, x, y, dx, dy, 1) for dx, dy in DIRS]
    if 5 in lens:
        return False
    if max(lens) > 5:
        return True
    fours = [fours_in_dir(board, x, y, dx, dy) for dx, dy in DIRS]
    if sum(fours) >= 2:
        return True
    if depth >= 4:
        return False
    threes = sum(1 for (dx, dy), f in zip(DIRS, fours)
                 if f == 0 and three_in_dir(board, x, y, dx, dy, depth))
    return threes >= 2


def judge(board, x, y, p):
    """回傳 'win' / 'foul' / None。白棋長連算勝。"""
    lens = [line_len(board, x, y, dx, dy, p) for dx, dy in DIRS]
    if p == 2:
        return 'win' if max(lens) >= 5 else None
    if 5 in lens:
        return 'win'
    return 'foul' if is_foul(board, x, y) else None


# Piskvork 對方
class Brain:
    def __init__(self, path, log=False):
        self.log = log
        self.proc = subprocess.Popen(
            [os.path.abspath(path)], cwd=os.path.dirname(os.path.abspath(path)),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1)
        self.q = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for line in self.proc.stdout:
            self.q.put(line.strip())
        self.q.put(None)

    def send(self, cmd):
        self.proc.stdin.write(cmd + '\n')
        self.proc.stdin.flush()

    def read(self, want, timeout):
        """讀到符合 want 的行為止；中途的 MESSAGE / DEBUG 視 --log 印出。"""
        deadline = time.time() + timeout
        while True:
            try:
                line = self.q.get(timeout=max(0.0, deadline - time.time()))
            except queue.Empty:
                return None
            if line is None:
                sys.exit("error: 對方程式已結束，檢查設定檔與權重是否與執行檔放在同一目錄")
            if want(line):
                return line
            up = line.upper()
            if up.startswith(('ERROR', 'UNKNOWN')):
                print(f"    [brain] {line}")
            elif self.log and line:
                print(f"    [brain] {line}")

    def info(self, key, val):
        self.send(f"INFO {key} {val}")

    def start(self, size):
        self.send(f"START {size}")
        if self.read(lambda s: s.upper() == 'OK', 60) is None:
            sys.exit("error: 對方沒有回應 START")

    def move(self, moves, me, timeout):
        self.send("BOARD")
        for x, y, p in moves:
            self.send(f"{x},{y},{1 if p == me else 2}")
        self.send("DONE")
        line = self.read(lambda s: _parse_xy(s) is not None, timeout)
        return _parse_xy(line) if line else None

    def close(self):
        try:
            self.send("END")
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def _parse_xy(s):
    parts = s.split(',')
    if len(parts) == 2 and all(t.strip().isdigit() for t in parts):
        return int(parts[0]), int(parts[1])
    return None


def play_game(eng, brain, eng_color, opening, stats, ms_arg, verbose):
    """回傳 (winner, moves, reason)。winner: 1=黑 2=白 0=和局。"""
    board = [[0] * N for _ in range(N)]
    moves = list(opening)
    for x, y, p in opening:
        board[y][x] = p
    eng.initTranspositionTable()
    brain.send("RESTART")
    brain.read(lambda s: s.upper() == 'OK', 30)

    rc = len(opening) + 1
    while rc <= MAX_ROUNDS:
        if len(moves) == N * N:
            return 0, moves, 'boardfull'
        p = 1 if rc % 2 == 1 else 2
        if p == eng_color:
            cb = selfplay.CBoard()
            for i in range(N):
                for j in range(N):
                    cb[i][j] = board[i][j]
            bx, by = ctypes.c_int(-1), ctypes.c_int(-1)
            t0 = time.perf_counter()
            eng.aiRound(ctypes.byref(cb), p, rc, ctypes.byref(bx), ctypes.byref(by))
            stats['eng_t'].append(time.perf_counter() - t0)
            x, y = bx.value, by.value
            if x == -1 and y == -1:
                return 0, moves, 'nomove'
        else:
            ms = ms_arg if ms_arg != 'auto' else _auto_ms(stats)
            brain.info('timeout_turn', ms)
            t0 = time.perf_counter()
            xy = brain.move(moves, p, ms / 1000 + REPLY_TIMEOUT_SLACK)
            stats['brain_t'].append(time.perf_counter() - t0)
            if xy is None:
                if verbose:
                    print(f"    brain timeout at round {rc}")
                return 3 - p, moves, 'timeout'
            x, y = xy

        if not inb(x, y) or board[y][x] != 0:
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
                print(f"    black FOUL at ({x},{y}) round {rc}")
            return 2, moves, 'foul'
        rc += 1
    return 0, moves, 'maxrounds'


def _auto_ms(stats):
    t = stats['eng_t']
    return max(100, int(sum(t) / len(t) * 1000)) if t else 1000


def elo(p):
    return 400 * math.log10(p / (1 - p))


def main():
    global N
    args = sys.argv[1:]
    if len(args) < 2:
        sys.exit(__doc__)

    def opt(name, default=None):
        if name in args:
            i = args.index(name)
            v = args[i + 1]
            del args[i:i + 2]
            return v
        return default

    infos = []
    while '--info' in args:
        k, _, v = opt('--info').partition('=')
        infos.append((k, v))
    ms_raw = opt('--ms', 'auto')
    ms_arg = ms_raw if ms_raw == 'auto' else int(ms_raw)
    threads = int(opt('--threads', '1'))
    pgn = opt('--pgn')
    log = '--log' in args
    quiet = '--quiet' in args
    args = [a for a in args if not a.startswith('--')]
    dll, exe = args[0], args[1]
    games = int(args[2]) if len(args) > 2 else 20

    eng = selfplay.load(dll)
    N = selfplay.BOARD_MAX
    brain = Brain(exe, log)
    brain.info('rule', 4)
    brain.info('thread_num', threads)
    brain.info('timeout_match', 2147483647)
    brain.info('time_left', 2147483647)
    for k, v in infos:
        brain.info(k, v)
    brain.start(N)

    all_openings = selfplay.openings()
    stats = {'eng_t': [], 'brain_t': []}
    score = 0.0
    reasons = {}
    records = []
    try:
        for g in range(games):
            opening = all_openings[(g // 2) % len(all_openings)]
            eng_color = 1 if g % 2 == 0 else 2
            w, moves, reason = play_game(eng, brain, eng_color, opening, stats, ms_arg, not quiet)
            reasons[reason] = reasons.get(reason, 0) + 1
            if w == 0:
                score += 0.5
                res = "draw"
            else:
                res = "ai.dll wins" if w == eng_color else "brain wins"
                score += w == eng_color
            records.append((moves, w))
            if not quiet:
                side = "black" if eng_color == 1 else "white"
                print(f"  game {g+1}/{games}: ai.dll as {side}: {res}  ({reason}, {len(moves)} moves)")
    finally:
        brain.close()

    et, bt = stats['eng_t'], stats['brain_t']
    print(f"\n=== {games} games vs {os.path.basename(exe)} ===")
    print(f"  ai.dll score  {score:.1f}/{games}  ({score/games*100:.1f}%)")
    if 0 < score < games:
        print(f"  Elo diff      {elo(score/games):+.0f}")
    elif score == 0:
        # rule of three：0 勝時勝率 95% 上界約 3/n
        print(f"  Elo diff      < {elo(min(3 / games, 0.5)):+.0f}（0 分，只得到上界）")
    else:
        print(f"  Elo diff      > {elo(max(1 - 3 / games, 0.5)):+.0f}（全勝，只得到下界）")
    if et:
        print(f"  ai.dll  avg {sum(et)/len(et):.2f}s  max {max(et):.2f}s per move")
    if bt:
        print(f"  brain   avg {sum(bt)/len(bt):.2f}s  max {max(bt):.2f}s per move")
    print(f"  endings: {reasons}")
    if reasons.get('foul'):
        print("  NOTE: 有禁手判負，建議抽查該局確認裁判判定")

    if pgn:
        with open(pgn, 'w', encoding='utf-8') as f:
            for moves, w in records:
                f.write(' '.join(f"{x},{y},{p}" for x, y, p in moves) + f" result={w}\n")
        print(f"  wrote {len(records)} games to {pgn}")


if __name__ == "__main__":
    main()
