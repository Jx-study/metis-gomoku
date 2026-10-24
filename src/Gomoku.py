import time     # 記錄運行時間
import ctypes   # 調用C語言函式庫
import os, sys
import platform
import threading
import traceback

from game_state import GameState   # 盤面/輪次/開局規則/悔棋（有測試涵蓋）

# PyInstaller onefile 解壓到 sys._MEIPASS，與雙擊時的工作目錄不同
def _base_dir():
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.abspath(os.path.dirname(__file__))


# 副檔名須與 utils/build.py 的 EXT_BY_SYSTEM 一致
def _lib_filename():
    return {'Windows': 'ai.dll', 'Linux': 'ai.so', 'Darwin': 'ai.dylib'}[platform.system()]


# 加載共享庫
# 必須在 const 之前載入：棋盤大小由 types.h 決定，const 需要先取得該值。
ai_lib = ctypes.CDLL(os.path.join(_base_dir(), _lib_filename()))
ai_lib.getBoardMax.restype = ctypes.c_int

# 定義常量+全域變數
class const:
    MARGIN = 100              # 棋盤邊距
    GRID = 30                 # 每個網格的大小
    PIECE_RADIUS = 10         # 棋子的半徑
    # 棋盤邊長（格點數），座標範圍 0 ~ BOARD_MAX-1。
    # 唯一定義處是 ai.c；此處讀取 DLL 實際編譯值，故兩端不可能失去同步。
    BOARD_MAX = ai_lib.getBoardMax()
    NUM = BOARD_MAX           # 繪製線條數，與格點數相同
    LEN = (NUM - 1) * GRID    # 棋盤的總長度
    MIDPOINT_X = BOARD_MAX // 2
    MIDPOINT_Y = BOARD_MAX // 2

    # --- 以下版面尺寸由棋盤大小推導，改 BOARD_MAX 時自動貼合 ---
    BOARD_END = MARGIN + LEN          # 棋盤右／下緣座標
    BUTTON_W = 100                    # 按鈕寬
    BUTTON_H = 40                     # 按鈕高
    BUTTON_GAP = 40                   # 按鈕間距
    BUTTON_TOP = BOARD_END + 15       # 按鈕頂緣（棋盤下方）
    BUTTON_BOTTOM = BUTTON_TOP + BUTTON_H
    STATUS_H = 36                     # 底部狀態列高
    # 視窗需容納棋盤、其下方的按鈕列與狀態列（右側留與左側相同的邊距）
    WIN_W = max(BOARD_END + MARGIN, 3 * BUTTON_W + 2 * BUTTON_GAP + 2 * MARGIN)
    WIN_H = BUTTON_BOTTOM + 15 + STATUS_H
    CENTER_X = WIN_W // 2             # 視窗水平中心（提示文字、對話框用）

# 定義C函數的返回值和參數類型
ai_lib.initZobristTable.restype = None
ai_lib.initTranspositionTable.restype = None
ai_lib.aiRound.restype = None
ai_lib.aiRound.argtypes = [ctypes.POINTER(ctypes.c_int * const.BOARD_MAX * const.BOARD_MAX),
                           ctypes.c_int, ctypes.c_int,
                           ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
ai_lib.checkUnValid.restype = ctypes.c_int
ai_lib.checkUnValid.argtypes = [ctypes.POINTER(ctypes.c_int * const.BOARD_MAX * const.BOARD_MAX),
                                 ctypes.c_int, ctypes.c_int, ctypes.c_int]
ai_lib.checkWin.restype = ctypes.c_int
ai_lib.checkWin.argtypes = [
    ctypes.POINTER(ctypes.c_int * const.BOARD_MAX * const.BOARD_MAX),  # 棋盘二维数组
    ctypes.c_int,  # minX
    ctypes.c_int,  # maxX
    ctypes.c_int,  # minY
    ctypes.c_int,  # maxY
    ctypes.c_int   # currentPlayer
]
# 注意：Zobrist key 由 C 端 findBestMove 每次搜索前以實際盤面重算（絕對值），
# Python 端不需要、也不應該再逐手同步（原本的同步呼叫已移除）。

# 定义 ctypes 二维数组的类型
CBoardType = (ctypes.c_int * const.BOARD_MAX) * const.BOARD_MAX

#---------------------------（引擎）-------------------------
class Engine:
    """共享庫的包裝

    AI 執行緒在跑時，主執行緒不能呼叫這裡的任何方法：C 端的增量索引與
    置換表是全域變數，搜索中被讀寫會破壞搜索結果。
    """

    def reset(self):
        ai_lib.initZobristTable()
        ai_lib.initTranspositionTable()

    @staticmethod
    def _to_c(board):
        c_board = CBoardType()
        for i in range(const.BOARD_MAX):
            for j in range(const.BOARD_MAX):
                c_board[i][j] = board[i][j]
        return c_board

    # 範圍/空位/開局規則由 GameState 先行過濾，進到這裡的座標保證在盤內
    def is_not_forbidden(self, board, x, y, player):
        return ai_lib.checkUnValid(ctypes.byref(self._to_c(board)), x, y, player) == 1

    # 黑棋下了會判負的空點
    def forbidden_points(self, board):
        c_board = self._to_c(board)
        return {(x, y)
                for y in range(const.BOARD_MAX) for x in range(const.BOARD_MAX)
                if board[y][x] == 0 and ai_lib.checkUnValid(ctypes.byref(c_board), x, y, 1) != 1}

    def check_win(self, board, player):
        return ai_lib.checkWin(ctypes.byref(self._to_c(board)), 0, const.BOARD_MAX - 1,
                               0, const.BOARD_MAX - 1, player) != 0

    def ai_move(self, board, ai, round_counter):
        bestx, besty = ctypes.c_int(), ctypes.c_int()
        ai_lib.aiRound(ctypes.byref(self._to_c(board)), ai, round_counter,
                       ctypes.byref(bestx), ctypes.byref(besty))
        return bestx.value, besty.value


# 含 (x, y) 且同色連成五子以上的那條線；沒有則回傳空串列
def find_five(board, x, y):
    color = board[y][x]
    if color == 0:
        return []
    n = len(board)
    for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
        line = [(x, y)]
        for sign in (1, -1):
            cx, cy = x + sign * dx, y + sign * dy
            while 0 <= cx < n and 0 <= cy < n and board[cy][cx] == color:
                line.append((cx, cy))
                cx, cy = cx + sign * dx, cy + sign * dy
        if len(line) >= 5:
            return line
    return []


#----------------------------(遊戲流程)----------------------------
class Phase:
    ROLE_SELECT = "role"
    PLAYER = "player"
    AI = "ai"
    OVER = "over"


CHANCES = 3     # 玩家的開局規則/禁手犯規機會
AI_RETRY = 3    # AI 回傳非法走法的容忍次數


def _spawn_daemon(target):
    threading.Thread(target=target, daemon=True).start()


class GameController:
    """遊戲流程，不依賴 pygame。

    盤面、輪次、開局規則、悔棋一律交給 GameState，輪到誰下每次都由
    round_counter 推導。AI 在背景執行緒搜索，結果經 post 送回主執行緒，
    由 apply_ai_move 套用；背景執行緒不碰任何狀態。
    """

    def __init__(self, engine, post, clock=time.perf_counter, spawn=_spawn_daemon):
        self.engine = engine
        self.post = post
        self.clock = clock
        self.spawn = spawn
        self.state = GameState(const.BOARD_MAX)
        self.state.set_forbidden_checker(engine.is_not_forbidden)
        self.show_rules = False
        self._reset_game()

    def _reset_game(self):
        self.state.reset()
        self.engine.reset()
        self.phase = Phase.ROLE_SELECT
        self.player = self.ai = None
        self.chances = CHANCES
        self.ai_retry = AI_RETRY
        self.forbidden = set()
        self.win_line = []
        self.move_times = []        # 與 state.moves 等長，每手耗時
        self.last_ai_time = None
        self.turn_start = self.clock()
        self.notice = "請選擇執黑或執白"

    # 手數只有一份真實來源（GameState），避免與盤面脫鉤
    @property
    def roundCounter(self):
        return self.state.round_counter

    # 搜索無法中途喊停，AI 思考中不能動盤面或引擎
    # 盤上沒有玩家的棋時悔棋只會撤掉 AI 的棋，AI 隨即重下同一手
    @property
    def can_undo(self):
        return (self.phase in (Phase.PLAYER, Phase.OVER)
                and any(mover == self.player for _x, _y, mover in self.state.moves))

    @property
    def can_restart(self):
        return self.phase != Phase.AI

    def choose_role(self, player):
        if self.phase != Phase.ROLE_SELECT:
            return
        self.player, self.ai = player, 3 - player
        self.next_turn()

    def next_turn(self):
        self.turn_start = self.clock()
        self.forbidden = set()
        # 盤面下滿、無人連五：和局；已無空格時 aiRound 找不到走法會被誤判成犯規
        if len(self.state.moves) == const.BOARD_MAX * const.BOARD_MAX:
            self._finish("棋盤下滿，和局!")
        elif self.state.current_player == self.ai:
            self._start_ai()
        else:
            self.phase = Phase.PLAYER
            self.notice = "第一手請落子在正中心位置" if self.roundCounter == 1 else "玩家正在下棋..."
            if self.chances < CHANCES:
                self.notice += f"，你還有{self.chances}次機會"
            if self.player == 1:
                self.forbidden = self.engine.forbidden_points(self.state.board)

    def _start_ai(self):
        self.phase = Phase.AI
        self.notice = "AI正在下棋..."
        board = self.state.snapshot()
        ai, rc = self.ai, self.roundCounter

        # 例外也要 post，否則控制器永遠停在 AI 回合
        def work():
            try:
                x, y = self.engine.ai_move(board, ai, rc)
            except Exception:
                traceback.print_exc()
                x = y = None
            self.post(x, y)

        self.spawn(work)

    def _finish(self, notice):
        self.phase = Phase.OVER
        self.notice = notice
        self.forbidden = set()

    # 落子已通過檢查：記錄耗時、判勝負、換手
    def _commit(self, x, y, mover):
        self.move_times.append(self.clock() - self.turn_start)
        if self.engine.check_win(self.state.board, mover):
            self.win_line = find_five(self.state.board, x, y)
            if mover == self.ai:
                self._finish(f"AI花了{self.roundCounter // 2}手才勝利!")
            else:
                self._finish("恭喜玩家!")
                self.record_player_win(self.ai)
            return
        self.next_turn()

    def click(self, x, y):
        if self.phase != Phase.PLAYER or self.show_rules:
            return
        if self.state.play(x, y, self.player):
            print(f"Player Move: ({x}, {y})")
            self._commit(x, y, self.player)
            return
        self.chances -= 1
        if self.chances == 0:
            self._finish("AI勝利!")
        else:
            self.notice = f"犯規，你還有{self.chances}次機會"

    def click_off_board(self):
        if self.phase == Phase.PLAYER and not self.show_rules:
            self.notice = "請點擊棋盤內有效位置"

    def apply_ai_move(self, x, y):
        if self.phase != Phase.AI:
            return
        self.last_ai_time = self.clock() - self.turn_start
        print(f"Python AI Move: ({x}, {y})")
        if x is None:
            self._finish("AI 無法下棋，遊戲中止")
            return
        # 哨兵值：無合法走法（例如僅存空格對黑棋是禁手），判和不判犯規
        if (x, y) == (-1, -1):
            self._finish("AI 無合法走法，和局!")
            return
        if self.state.play(x, y, self.ai):
            self._commit(x, y, self.ai)
            return
        # AI 回傳非法座標不是玩家犯規，不能扣玩家的機會
        self.ai_retry -= 1
        print(f"[BUG] AI returned invalid move ({x}, {y}) at round {self.roundCounter}")
        if self.ai_retry == 0:
            self._finish("AI 無法產生合法走法，遊戲中止")
        else:
            self._start_ai()

    def undo(self):
        if self.phase not in (Phase.PLAYER, Phase.OVER):
            return
        if not self.can_undo:
            self.notice = "沒有可以悔棋的步數"
            return
        # roundCounter 由 GameState.undo() 依實際撤銷手數回捲，這裡不能自行調整
        undone = self.state.undo(2)
        del self.move_times[-undone:]
        self.win_line = []
        # 從終局悔回來時計數可能已歸零，不還原的話 == 0 的判定永遠不再成立
        self.chances = max(self.chances, 1)
        self.ai_retry = AI_RETRY
        self.next_turn()

    def restart(self):
        if not self.can_restart:
            return
        self._reset_game()
        self.notice = "重新開始遊戲"

    def toggle_rules(self):
        self.show_rules = not self.show_rules

    def colour_total(self, colour):
        return sum(t for (_x, _y, mover), t in zip(self.state.moves, self.move_times)
                   if mover == colour)

    def turn_elapsed(self):
        if self.phase in (Phase.PLAYER, Phase.AI):
            return self.clock() - self.turn_start
        return 0.0

    # 玩家勝利時記錄棋譜，供之後覆盤或當測資用；AI 勝利不記（只在乎 AI 輸的局）
    # 只在開發環境（GOMOKU_DEV=1）寫入，一般使用者跑起來不留檔
    # 寫檔失敗（例如唯讀目錄）直接略過，不影響對局
    def record_player_win(self, ai):
        if os.environ.get("GOMOKU_DEV") != "1":
            return
        moves = self.state.moves
        try:
            with open("player_wins.log", "a", encoding="utf-8") as f:
                f.write(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} 玩家勝, {len(moves)}手, AI執{'黑' if ai == 1 else '白'} ===\n")
                for x, y, mover in moves:
                    who = "AI" if mover == ai else "player"
                    f.write(f"{who} ({x}, {y})\n")
                f.write("\n")
        except OSError:
            pass


def main():
    import gomoku_ui
    gomoku_ui.run(GameController, Engine(), const, _base_dir())


if __name__ == "__main__":
    main()
