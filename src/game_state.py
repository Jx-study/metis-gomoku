"""五子棋核心狀態層

`Gomoku.py` 只負責繪圖與事件處理，狀態一律經由這個模組管理。

設計上的兩個關鍵不變量（測試會逐一驗證）：

1. ``round_counter == len(moves) + 1``
   悔棋若沒有等量回捲計數器，開局規則（第 1-3 手的落點限制）就會失效。

2. ``current_player`` 由 ``round_counter`` 推導，不另存變數
   黑棋恆在奇數手、白棋恆在偶數手。曾經因為另存一份 ``current_player``
   而在悔棋撤銷奇數手後奇偶對不上，導致白棋先手、或玩家連下兩顆同色子。
"""

BLACK = 1
WHITE = 2
EMPTY = 0


class GameState:
    """盤面與輪次狀態。不持有任何 GUI 物件。"""

    def __init__(self, board_max, forbidden_checker=None):
        """
        board_max: 棋盤邊長（格點數），座標範圍 0 ~ board_max-1
        forbidden_checker: 選填，簽名為 (board, x, y, player) -> bool，
            用來判斷禁手。傳 None 時不做禁手檢查（純規則測試用）。
        """
        self.board_max = board_max
        self.midpoint = board_max // 2
        self._forbidden_checker = forbidden_checker
        self.reset()

    def set_forbidden_checker(self, checker):
        """設定禁手判斷函式，簽名為 (board, x, y, player) -> bool。

        供 GUI 端在建構後接上 C 引擎的 checkUnValid()；測試則多半不需要。
        """
        self._forbidden_checker = checker

    # ---------- 基本狀態 ----------

    def reset(self):
        self.board = [[EMPTY] * self.board_max for _ in range(self.board_max)]
        self.moves = []          # [(x, y, player)]，依落子順序
        self.round_counter = 1   # 第幾手（從 1 起算）

    @property
    def current_player(self):
        """輪到誰下。由 round_counter 推導，黑棋在奇數手、白棋在偶數手"""
        return BLACK if self.round_counter % 2 == 1 else WHITE

    def stone_count(self):
        return len(self.moves)

    def in_bounds(self, x, y):
        return 0 <= x < self.board_max and 0 <= y < self.board_max

    def is_empty(self, x, y):
        return self.board[y][x] == EMPTY

    # ---------- 開局規則 ----------

    def opening_box_radius(self):
        """本手受開局規則限制的方框半徑；None 表示不受限

        連珠指定開局：第 1 手天元、第 2 手中心 3x3、第 3 手中心 5x5。
        """
        return {1: 0, 2: 1, 3: 2}.get(self.round_counter)

    def violates_opening_rule(self, x, y):
        radius = self.opening_box_radius()
        if radius is None:
            return False
        return abs(x - self.midpoint) > radius or abs(y - self.midpoint) > radius

    # ---------- 落子合法性 ----------

    def is_valid_move(self, x, y, player=None):
        """是否可在 (x, y) 落子

        檢查順序刻意如此：範圍 → 空位 → 開局規則 → 禁手。範圍必須排在最
        前面，因為禁手檢查會把座標交給 C 端存取 board[y][x]，越界會造成
        越界讀取（UB）。
        """
        if player is None:
            player = self.current_player
        if not self.in_bounds(x, y):
            return False
        if not self.is_empty(x, y):
            return False
        if self.violates_opening_rule(x, y):
            return False
        if self._forbidden_checker is not None:
            return self._forbidden_checker(self.board, x, y, player)
        return True

    # ---------- 落子與悔棋 ----------

    def play(self, x, y, player=None):
        """落子並推進輪次。回傳是否成功（非法則不改變任何狀態）"""
        if player is None:
            player = self.current_player
        if not self.is_valid_move(x, y, player):
            return False
        self.board[y][x] = player
        self.moves.append((x, y, player))
        self.round_counter += 1
        return True

    def undo(self, count=2):
        """悔棋，回傳實際撤銷的手數（0 表示無棋可悔）

        預設撤銷 2 手（雙方各一手）。盤面不足時只撤銷現有手數，避免對空的
        列表 pop。計數器一律依實際撤銷量回捲，以維持不變量 1。
        """
        undone = min(count, len(self.moves))
        for _ in range(undone):
            x, y, _player = self.moves.pop()
            self.board[y][x] = EMPTY
        self.round_counter = max(1, self.round_counter - undone)
        return undone

    def last_move(self):
        return self.moves[-1] if self.moves else None

    def snapshot(self):
        """回傳目前盤面的複本（供 ctypes 轉換或測試比對用）"""
        return [row[:] for row in self.board]
