"""Gomoku.py 與狀態層的接線測試（不開視窗）。

`test_game_state.py` 測的是規則本身；本檔測的是控制器有沒有正確接上——
`roundCounter` property、禁手 callback、悔棋後重新推導輪次、AI 背景執行緒
的收尾。這一層曾經出過「規則正確但接線錯」的 bug（悔棋後 current_player
沒重新推導、玩家連下兩顆同色棋），所以規則測試不能取代它。

`GameController` 不依賴 pygame；AI 用假引擎控制何時回傳。找不到共享庫時
整個模組 skip（`Gomoku` 在 import 時就會載入共享庫）。
"""
import os
import sys

import pytest

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def gomoku():
    """import Gomoku，但不開視窗。需要共享庫已編譯。"""
    if SRC_DIR not in sys.path:
        sys.path.insert(0, SRC_DIR)
    try:
        import Gomoku
    except OSError as exc:     # 找不到共享庫
        pytest.skip(f"無法載入共享庫：{exc}")
    return Gomoku


@pytest.fixture
def mid(gomoku):
    return gomoku.const.MIDPOINT_X


class FakeEngine:
    """假引擎：AI 走法照 script 依序回傳，勝負用 Python 端的五連掃描判定。"""

    def __init__(self, gomoku, script=()):
        self.gomoku = gomoku
        self.script = list(script)
        self.ai_calls = []
        self.forbidden_calls = 0
        self.forbidden = set()
        self.resets = 0

    def reset(self):
        self.resets += 1

    def is_not_forbidden(self, board, x, y, player):
        return True

    def forbidden_points(self, board):
        self.forbidden_calls += 1
        return set(self.forbidden)

    def check_win(self, board, player):
        return any(self.gomoku.find_five(board, x, y)
                   for y, row in enumerate(board) for x, c in enumerate(row) if c == player)

    def ai_move(self, board, ai, round_counter):
        self.ai_calls.append((ai, round_counter))
        return self.script.pop(0)


class Harness:
    """把控制器、假引擎、AI 事件佇列綁在一起。

    spawn 預設不執行 AI（模擬思考中）；run_ai() 才真的跑並套用結果。
    """

    def __init__(self, gomoku, script=(), engine=None):
        self.engine = engine or FakeEngine(gomoku, script)
        self.posted = []
        self.pending = []
        self.now = 0.0
        self.ctl = gomoku.GameController(
            self.engine,
            post=lambda x, y: self.posted.append((x, y)),
            clock=lambda: self.now,
            spawn=self.pending.append,
        )

    def run_ai(self):
        target = self.pending.pop(0)
        target()
        x, y = self.posted.pop(0)
        self.ctl.apply_ai_move(x, y)


@pytest.fixture
def make(gomoku):
    return lambda script=(), engine=None: Harness(gomoku, script, engine)


class TestRoundCounterProperty:
    def test_reads_from_state(self, make, mid):
        h = make()
        h.ctl.choose_role(1)
        assert h.ctl.roundCounter == 1
        h.ctl.click(mid, mid)
        assert h.ctl.roundCounter == 2

    def test_is_read_only(self, make):
        """唯讀是刻意的：手數只能有一份真實來源，避免與盤面脫鉤。"""
        ctl = make().ctl
        with pytest.raises(AttributeError):
            ctl.roundCounter = 99


class TestTurnFlow:
    def test_player_black_move_hands_turn_to_ai(self, gomoku, make, mid):
        h = make(script=[(mid, mid - 1)])
        h.ctl.choose_role(1)
        assert h.ctl.phase == gomoku.Phase.PLAYER
        h.ctl.click(mid, mid)
        assert h.ctl.phase == gomoku.Phase.AI
        assert len(h.pending) == 1
        h.run_ai()
        assert h.engine.ai_calls == [(2, 2)]
        assert h.ctl.state.moves == [(mid, mid, 1), (mid, mid - 1, 2)]
        assert h.ctl.phase == gomoku.Phase.PLAYER

    def test_player_white_ai_moves_first(self, gomoku, make, mid):
        h = make(script=[(mid, mid)])
        h.ctl.choose_role(2)
        assert h.ctl.phase == gomoku.Phase.AI
        h.run_ai()
        assert h.ctl.state.moves == [(mid, mid, 1)]
        assert h.ctl.phase == gomoku.Phase.PLAYER

    def test_ai_receives_board_copy(self, make, mid):
        """背景執行緒拿的是啟動當下的盤面複本，主執行緒之後的變動不影響它。"""
        seen = []
        h = make()
        h.engine.ai_move = lambda board, ai, rc: seen.append(board) or (mid, mid - 1)
        h.ctl.choose_role(1)
        h.ctl.click(mid, mid)
        h.ctl.state.board[0][0] = 9
        h.run_ai()
        assert seen[0][0][0] == 0

    def test_click_ignored_while_ai_thinking(self, make, mid):
        h = make(script=[(mid, mid - 1)])
        h.ctl.choose_role(1)
        h.ctl.click(mid, mid)
        h.ctl.click(mid + 1, mid + 1)
        assert len(h.ctl.state.moves) == 1


class TestAiThinkingLocks:
    """搜索無法中途喊停，思考中只能停用會動到盤面或引擎的操作。"""

    def _thinking(self, make, mid):
        h = make(script=[(mid, mid - 1)])
        h.ctl.choose_role(1)
        h.ctl.click(mid, mid)
        return h

    def test_undo_rejected(self, make, mid):
        h = self._thinking(make, mid)
        assert h.ctl.can_undo is False
        h.ctl.undo()
        assert len(h.ctl.state.moves) == 1

    def test_restart_rejected(self, make, mid):
        h = self._thinking(make, mid)
        assert h.ctl.can_restart is False
        h.ctl.restart()
        assert len(h.ctl.state.moves) == 1
        assert h.engine.resets == 1        # 只有建構時那一次

    def test_rules_overlay_allowed(self, make, mid):
        h = self._thinking(make, mid)
        h.ctl.toggle_rules()
        assert h.ctl.show_rules is True

    def test_no_dll_call_for_forbidden_marks_while_thinking(self, make, mid):
        """AI 執行緒在跑時主執行緒不能進 DLL，否則會破壞搜索中的增量索引。"""
        h = self._thinking(make, mid)
        before = h.engine.forbidden_calls
        h.ctl.toggle_rules()
        h.ctl.toggle_rules()
        assert h.engine.forbidden_calls == before


class TestUndoRederivesTurn:
    def test_undo_back_to_player_turn(self, gomoku, make, mid):
        h = make(script=[(mid, mid - 1)])
        h.ctl.choose_role(1)
        h.ctl.click(mid, mid)
        h.run_ai()
        h.ctl.undo()
        assert h.ctl.state.moves == []
        assert h.ctl.roundCounter == 1
        assert h.ctl.phase == gomoku.Phase.PLAYER

    def test_undo_rejected_without_player_stone(self, gomoku, make, mid):
        """玩家執白、盤上只有 AI 第一手：悔掉只會讓 AI 重下同一手，所以不給悔。"""
        h = make(script=[(mid, mid)])
        h.ctl.choose_role(2)
        h.run_ai()
        assert h.ctl.can_undo is False
        h.ctl.undo()
        assert h.ctl.state.moves == [(mid, mid, 1)]
        assert h.ctl.phase == gomoku.Phase.PLAYER
        assert h.pending == []
        assert h.ctl.notice == "沒有可以悔棋的步數"

    def test_undo_empty_board_notice(self, make):
        h = make()
        h.ctl.choose_role(1)
        h.ctl.undo()
        assert h.ctl.notice == "沒有可以悔棋的步數"


class TestRestart:
    def test_resets_state_and_engine(self, gomoku, make, mid):
        h = make(script=[(mid, mid - 1)])
        h.ctl.choose_role(1)
        h.ctl.click(mid, mid)
        h.run_ai()
        h.ctl.restart()
        assert h.ctl.state.moves == []
        assert h.ctl.phase == gomoku.Phase.ROLE_SELECT
        assert h.engine.resets == 2


class TestFouls:
    def test_player_three_fouls_loses(self, gomoku, make, mid):
        h = make()
        h.ctl.choose_role(1)
        h.ctl.click(0, 0)                   # 第一手不在天元
        assert h.ctl.notice == "犯規，你還有2次機會"
        h.ctl.click(0, 0)
        h.ctl.click(0, 0)
        assert h.ctl.phase == gomoku.Phase.OVER
        assert h.ctl.notice == "AI勝利!"

    def test_ai_invalid_move_does_not_cost_player_chance(self, gomoku, make, mid):
        """AI 自己回傳非法座標不能扣玩家機會，否則會變成「AI 犯規卻判 AI 勝」。"""
        h = make(script=[(mid, mid), (mid, mid - 1)])
        h.ctl.choose_role(1)
        h.ctl.click(mid, mid)
        h.run_ai()                          # 撞到已有棋子
        assert h.ctl.chances == 3
        assert h.ctl.phase == gomoku.Phase.AI
        h.run_ai()
        assert h.ctl.state.moves[-1] == (mid, mid - 1, 2)

    def test_ai_invalid_three_times_aborts(self, gomoku, make, mid):
        h = make(script=[(mid, mid)] * 3)
        h.ctl.choose_role(1)
        h.ctl.click(mid, mid)
        for _ in range(3):
            h.run_ai()
        assert h.ctl.phase == gomoku.Phase.OVER
        assert h.ctl.notice == "AI 無法產生合法走法，遊戲中止"

    def test_undo_after_foul_loss_restores_a_chance(self, gomoku, make, mid):
        """犯規判負後悔棋，機會若停在 0，之後再犯規會變成負數且永不判負。"""
        h = make(script=[(mid, mid - 1), (mid + 1, mid - 1)])
        h.ctl.choose_role(1)
        h.ctl.click(mid, mid)
        h.run_ai()
        for _ in range(3):
            h.ctl.click(mid, mid)               # 已有棋子
        assert h.ctl.phase == gomoku.Phase.OVER
        h.ctl.undo()
        assert h.ctl.chances == 1
        assert h.ctl.notice == "第一手請落子在正中心位置，你還有1次機會"
        h.ctl.click(0, 0)                       # 第一手不在天元
        assert h.ctl.phase == gomoku.Phase.OVER

    def test_undo_after_ai_abort_resets_retry(self, gomoku, make, mid):
        """AI 連續非法判中止後悔棋，重試次數若停在 0 會無限重開搜索。"""
        h = make(script=[(mid, mid - 1)] + [(mid, mid)] * 6)
        h.ctl.choose_role(1)
        h.ctl.click(mid, mid)
        h.run_ai()
        h.ctl.click(mid + 1, mid)
        for _ in range(3):
            h.run_ai()
        assert h.ctl.phase == gomoku.Phase.OVER
        h.ctl.undo()
        assert h.ctl.ai_retry == gomoku.AI_RETRY
        h.ctl.click(mid + 1, mid)
        for _ in range(3):
            h.run_ai()
        assert h.ctl.phase == gomoku.Phase.OVER
        assert h.pending == []

    def test_ai_exception_ends_game(self, gomoku, make, mid):
        """背景執行緒拋例外仍要送回結果，否則畫面永遠停在 AI 思考中。"""
        h = make()
        h.engine.ai_move = lambda board, ai, rc: 1 / 0
        h.ctl.choose_role(1)
        h.ctl.click(mid, mid)
        h.run_ai()
        assert h.ctl.phase == gomoku.Phase.OVER
        assert h.ctl.notice == "AI 無法下棋，遊戲中止"

    def test_ai_sentinel_is_draw(self, gomoku, make, mid):
        h = make(script=[(-1, -1)])
        h.ctl.choose_role(1)
        h.ctl.click(mid, mid)
        h.run_ai()
        assert h.ctl.phase == gomoku.Phase.OVER
        assert h.ctl.notice == "AI 無合法走法，和局!"


class TestGameEnd:
    def _black_five(self, make, mid):
        # 玩家執黑，AI 白子下在上方一排（第 2 手須在中心 3x3 內），黑子橫向連五
        script = [(mid + i, mid - 1) for i in range(4)]
        h = make(script=script)
        h.ctl.choose_role(1)
        for i, x in enumerate([mid, mid + 1, mid + 2, mid + 3, mid - 1]):
            h.ctl.click(x, mid)
            if i < 4:
                h.run_ai()
        return h

    def test_player_win(self, gomoku, make, mid):
        h = self._black_five(make, mid)
        assert h.ctl.phase == gomoku.Phase.OVER
        assert h.ctl.notice == "恭喜玩家!"
        assert sorted(h.ctl.win_line) == [(mid + i, mid) for i in range(-1, 4)]

    def test_undo_after_game_over_resumes(self, gomoku, make, mid):
        """悔 2 手撤掉黑棋勝著與白棋上一手，輪回 AI 重下。"""
        h = self._black_five(make, mid)
        h.ctl.undo()
        assert h.ctl.roundCounter == 8
        assert h.ctl.phase == gomoku.Phase.AI
        assert h.ctl.win_line == []

    def test_board_full_is_draw_before_ai(self, gomoku, make):
        n = gomoku.const.BOARD_MAX
        h = make()
        h.ctl.choose_role(2)
        h.pending.clear()
        # 直接填滿盤面，只測「下滿就判和、不再叫 AI」這條分支
        for y in range(n):
            for x in range(n):
                h.ctl.state.board[y][x] = 1 + (x + y) % 2
                h.ctl.state.moves.append((x, y, 1 + (x + y) % 2))
        h.ctl.state.round_counter = n * n + 1
        h.ctl.next_turn()
        assert h.ctl.phase == gomoku.Phase.OVER
        assert h.ctl.notice == "棋盤下滿，和局!"
        assert h.pending == []


class TestFindFive:
    def test_horizontal(self, gomoku):
        board = [[0] * 15 for _ in range(15)]
        for x in range(3, 8):
            board[5][x] = 1
        assert sorted(gomoku.find_five(board, 5, 5)) == [(x, 5) for x in range(3, 8)]

    def test_diagonal_overline_returns_whole_run(self, gomoku):
        board = [[0] * 15 for _ in range(15)]
        for i in range(6):
            board[2 + i][2 + i] = 2
        assert len(gomoku.find_five(board, 4, 4)) == 6

    def test_four_is_not_five(self, gomoku):
        board = [[0] * 15 for _ in range(15)]
        for x in range(3, 7):
            board[5][x] = 1
        assert gomoku.find_five(board, 4, 5) == []


class TestTiming:
    def test_colour_totals_follow_undo(self, make, mid):
        h = make(script=[(mid, mid - 1)])
        h.ctl.choose_role(1)
        h.now = 2.0
        h.ctl.click(mid, mid)               # 黑花 2 秒
        h.now = 5.0
        h.run_ai()                          # 白花 3 秒
        assert h.ctl.colour_total(1) == 2.0
        assert h.ctl.colour_total(2) == 3.0
        assert h.ctl.last_ai_time == 3.0
        h.ctl.undo()
        assert h.ctl.colour_total(1) == 0.0
        assert h.ctl.colour_total(2) == 0.0

    def test_turn_timer_resets_on_undo(self, make, mid):
        h = make(script=[(mid, mid - 1)])
        h.ctl.choose_role(1)
        h.ctl.click(mid, mid)
        h.run_ai()
        h.now = 10.0
        h.ctl.undo()
        assert h.ctl.turn_elapsed() == 0.0


class TestForbiddenMarks:
    def test_computed_on_black_player_turn(self, make, mid):
        h = make()
        h.engine.forbidden = {(1, 1)}
        h.ctl.choose_role(1)
        assert h.ctl.forbidden == {(1, 1)}

    def test_not_computed_for_white_player(self, make, mid):
        h = make(script=[(mid, mid)])
        h.ctl.choose_role(2)
        h.run_ai()
        assert h.engine.forbidden_calls == 0
        assert h.ctl.forbidden == set()


class TestRealEngineWiring:
    """真的經過 C 端：禁手 callback 與禁手點集合。"""

    @pytest.fixture
    def engine(self, gomoku):
        return gomoku.Engine()

    def test_checker_is_consulted(self, gomoku, engine, mid):
        calls = []
        ctl = gomoku.GameController(engine, post=lambda x, y: None, spawn=lambda f: None)
        original = ctl.state._forbidden_checker

        def spy(board, x, y, player):
            calls.append((x, y, player))
            return original(board, x, y, player)

        ctl.state.set_forbidden_checker(spy)
        assert ctl.state.is_valid_move(mid, mid, 1) is True
        assert calls == [(mid, mid, 1)]

    @pytest.mark.parametrize("x,y", [(-1, -1), (999, 999), (-1, 0)])
    def test_out_of_bounds_never_reaches_c(self, gomoku, engine, x, y):
        """越界座標若進到 C 端會直接 board[y][x] 造成越界讀取（UB）。"""
        calls = []
        ctl = gomoku.GameController(engine, post=lambda x, y: None, spawn=lambda f: None)
        ctl.state.set_forbidden_checker(lambda board, px, py, p: calls.append((px, py)) or True)
        assert ctl.state.is_valid_move(x, y, 1) is False
        assert calls == []

    def test_forbidden_points_finds_double_three(self, gomoku, engine, mid):
        n = gomoku.const.BOARD_MAX
        board = [[0] * n for _ in range(n)]
        # (mid, mid) 橫向與縱向各形成活三：三三禁手
        for x, y in [(mid - 2, mid), (mid - 1, mid), (mid, mid - 2), (mid, mid - 1)]:
            board[y][x] = 1
        assert (mid, mid) in engine.forbidden_points(board)
        assert (0, 0) not in engine.forbidden_points(board)


class TestRecordPlayerWin:
    def test_writes_log(self, make, mid, tmp_path, monkeypatch):
        h = make()
        h.ctl.choose_role(1)
        for (x, y, player) in [(mid, mid, 1), (mid, mid + 1, 2), (mid + 1, mid + 1, 1)]:
            h.ctl.state.play(x, y, player)

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("GOMOKU_DEV", "1")
        h.ctl.record_player_win(2)          # AI 執白

        log = (tmp_path / "player_wins.log").read_text(encoding="utf-8")
        assert "玩家勝, 3手, AI執白" in log
        assert f"AI ({mid}, {mid + 1})" in log
        assert f"player ({mid}, {mid})" in log

    def test_no_log_without_dev_flag(self, make, tmp_path, monkeypatch):
        h = make()
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("GOMOKU_DEV", raising=False)
        h.ctl.record_player_win(2)
        assert not (tmp_path / "player_wins.log").exists()


class TestRealThread:
    """真的開背景執行緒跑 aiRound，結果經 post 回到主執行緒套用。"""

    def test_ai_first_move_via_thread(self, gomoku, mid):
        import queue
        results = queue.Queue()
        ctl = gomoku.GameController(gomoku.Engine(), post=lambda x, y: results.put((x, y)))
        ctl.choose_role(2)
        assert ctl.phase == gomoku.Phase.AI
        x, y = results.get(timeout=30)
        ctl.apply_ai_move(x, y)
        assert ctl.state.moves == [(mid, mid, 1)]
        assert ctl.phase == gomoku.Phase.PLAYER
