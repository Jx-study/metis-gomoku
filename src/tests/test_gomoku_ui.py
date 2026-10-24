"""gomoku_ui 渲染層測試（SDL dummy driver，不開真視窗）。

涵蓋像素與棋盤格的換算、按鈕判定、每種遊戲狀態都畫得出一幀，以及內附
字型涵蓋介面上所有中文字。找不到共享庫時整個模組 skip。
"""
import os
import sys

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

pygame = pytest.importorskip("pygame")


@pytest.fixture(scope="module")
def gomoku():
    try:
        import Gomoku
    except OSError as exc:
        pytest.skip(f"無法載入共享庫：{exc}")
    return Gomoku


@pytest.fixture(scope="module")
def ui():
    import gomoku_ui
    return gomoku_ui


@pytest.fixture(scope="module")
def layout(gomoku):
    return gomoku.const


class TestPixelToCell:
    def test_grid_point_maps_to_cell(self, ui, layout):
        pos = (layout.MARGIN + 3 * layout.GRID, layout.MARGIN + 5 * layout.GRID)
        assert ui.pixel_to_cell(layout, pos) == (3, 5)

    def test_rounds_to_nearest(self, ui, layout):
        pos = (layout.MARGIN + 3 * layout.GRID + layout.GRID // 2 - 1,
               layout.MARGIN + 5 * layout.GRID - layout.GRID // 2 + 1)
        assert ui.pixel_to_cell(layout, pos) == (3, 5)

    def test_outside_board_is_none(self, ui, layout):
        assert ui.pixel_to_cell(layout, (5, 5)) is None
        far = layout.MARGIN + layout.LEN + layout.GRID
        assert ui.pixel_to_cell(layout, (far, far)) is None

    def test_edge_within_half_grid(self, ui, layout):
        pos = (layout.MARGIN - layout.GRID // 2 + 1, layout.MARGIN)
        assert ui.pixel_to_cell(layout, pos) == (0, 0)


class TestHitTest:
    def test_buttons(self, ui, layout):
        rects = ui.button_rects(layout)
        assert set(rects) == {"restart", "undo", "rules"}
        for name, rect in rects.items():
            assert ui.button_at(layout, rect.center) == name
        assert ui.button_at(layout, (0, 0)) is None

    def test_role_buttons(self, ui, layout):
        rects = ui.role_rects(layout)
        assert ui.role_at(layout, rects[1].center) == 1
        assert ui.role_at(layout, rects[2].center) == 2
        assert ui.role_at(layout, (0, 0)) is None

    def test_buttons_do_not_overlap_board(self, ui, layout):
        board = pygame.Rect(layout.MARGIN, layout.MARGIN, layout.LEN, layout.LEN)
        assert not any(r.colliderect(board) for r in ui.button_rects(layout).values())


class FakeEngine:
    def reset(self):
        pass

    def is_not_forbidden(self, board, x, y, player):
        return True

    def forbidden_points(self, board):
        return {(0, 0), (1, 1)}

    def check_win(self, board, player):
        return False

    def ai_move(self, board, ai, rc):
        return (0, 0)


@pytest.fixture
def renderer(ui, gomoku, layout):
    return ui.Renderer(layout, gomoku._base_dir())


@pytest.fixture
def ctl(gomoku):
    return gomoku.GameController(FakeEngine(), post=lambda x, y: None, spawn=lambda f: None)


class TestDrawFrame:
    def test_role_select(self, renderer, ctl):
        renderer.draw_frame(ctl, (0, 0))

    def test_player_turn_with_hover_and_forbidden(self, renderer, ctl, layout):
        ctl.choose_role(1)
        mid = layout.MIDPOINT_X
        pos = (layout.MARGIN + mid * layout.GRID, layout.MARGIN + mid * layout.GRID)
        renderer.draw_frame(ctl, pos)

    def test_ai_thinking(self, renderer, ctl, layout):
        ctl.choose_role(1)
        ctl.click(layout.MIDPOINT_X, layout.MIDPOINT_Y)
        renderer.draw_frame(ctl, (0, 0))

    def test_game_over_with_win_line(self, gomoku, renderer, ctl):
        ctl.choose_role(1)
        ctl.win_line = [(i, 3) for i in range(5)]
        ctl.phase = gomoku.Phase.OVER
        renderer.draw_frame(ctl, (0, 0))

    def test_rules_overlay_scrolls_and_clamps(self, renderer, ctl):
        ctl.toggle_rules()
        renderer.scroll_rules(-10000)
        assert renderer.rules_offset == 0
        renderer.scroll_rules(10000)
        assert 0 <= renderer.rules_offset <= renderer.rules_max_offset
        renderer.draw_frame(ctl, (0, 0))


class TestHoverPreview:
    def test_shown_only_on_empty_cell_in_player_turn(self, ui, renderer, ctl, layout):
        mid = layout.MIDPOINT_X
        pos = (layout.MARGIN + mid * layout.GRID, layout.MARGIN + mid * layout.GRID)
        assert renderer.hover_cell(ctl, pos) is None          # 還在選角色
        ctl.choose_role(1)
        assert renderer.hover_cell(ctl, pos) == (mid, mid)
        ctl.click(mid, mid)
        assert renderer.hover_cell(ctl, pos) is None          # AI 思考中
        ctl.toggle_rules()
        assert renderer.hover_cell(ctl, (0, 0)) is None


class TestFont:
    def test_bundled_font_exists(self, ui, gomoku):
        assert os.path.isfile(os.path.join(gomoku._base_dir(), ui.FONT_FILE))

    def test_bundled_font_covers_ui_text(self, ui, gomoku):
        """改了介面文字卻沒重跑 utils/subset_font.py，缺的字會畫成方框。"""
        from fontTools.ttLib import TTFont
        cmap = TTFont(os.path.join(gomoku._base_dir(), ui.FONT_FILE)).getBestCmap()
        sys.path.insert(0, os.path.join(SRC_DIR, "utils"))
        import subset_font
        missing = sorted(c for c in subset_font.ui_characters() if ord(c) not in cmap)
        assert missing == []


class TestDispatch:
    """滑鼠點擊的路由：疊加層優先，其次角色選擇、按鈕、棋盤。"""

    def _cell_pos(self, layout, x, y):
        return (layout.MARGIN + x * layout.GRID, layout.MARGIN + y * layout.GRID)

    def test_role_click_chooses_role(self, ui, ctl, renderer, layout):
        ui.dispatch(ctl, renderer, layout, ui.role_rects(layout)[1].center)
        assert ctl.player == 1

    def test_board_click_places_stone(self, ui, ctl, renderer, layout):
        ctl.choose_role(1)
        mid = layout.MIDPOINT_X
        ui.dispatch(ctl, renderer, layout, self._cell_pos(layout, mid, mid))
        assert ctl.state.moves == [(mid, mid, 1)]

    def test_rules_overlay_swallows_board_click(self, ui, ctl, renderer, layout):
        ctl.choose_role(1)
        ctl.toggle_rules()
        mid = layout.MIDPOINT_X
        ui.dispatch(ctl, renderer, layout, self._cell_pos(layout, mid, mid))
        assert ctl.state.moves == []
        ui.dispatch(ctl, renderer, layout, ui.rules_close_rect(layout).center)
        assert ctl.show_rules is False

    def test_rules_button_opens_overlay(self, ui, ctl, renderer, layout):
        ui.dispatch(ctl, renderer, layout, ui.button_rects(layout)["rules"].center)
        assert ctl.show_rules is True

    def test_off_board_click_notice(self, ui, ctl, renderer, layout):
        ctl.choose_role(1)
        ui.dispatch(ctl, renderer, layout, (layout.WIN_W - 5, 5))
        assert ctl.notice == "請點擊棋盤內有效位置"


class TestRulesWrap:
    def test_no_line_starts_with_closing_punctuation(self, renderer):
        assert not [l for l in renderer._rules_lines if l and l[0] in "，。、）」：；！？"]

    def test_lines_fit_text_area(self, ui, renderer, layout):
        from theme import FONT_RULES
        width = ui.rules_panel_rect(layout).width - 40
        assert max(renderer.font(FONT_RULES).size(l)[0] for l in renderer._rules_lines) <= width


class TestRunLoop:
    """真的跑事件迴圈：點擊經 dispatch、AI 經背景執行緒與自訂事件回到主迴圈。"""

    def test_player_move_then_ai_reply(self, ui, gomoku, layout):
        mid = layout.MIDPOINT_X
        pygame.display.init()
        pygame.display.set_mode((layout.WIN_W, layout.WIN_H))
        for pos in (ui.role_rects(layout)[1].center, ui.cell_center(layout, mid, mid)):
            pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1))
        pygame.time.set_timer(pygame.QUIT, 3000, loops=1)
        ctl = ui.run(gomoku.GameController, gomoku.Engine(), layout, gomoku._base_dir())
        assert ctl.state.moves[0] == (mid, mid, 1)
        assert len(ctl.state.moves) == 2
        assert ctl.phase == gomoku.Phase.PLAYER


class TestHeader:
    def test_notice_centered_above_board(self, ui, renderer, ctl, layout):
        renderer.draw_frame(ctl, (0, 0))
        assert renderer.notice_rect.center == (layout.CENTER_X, ui.header_center_y(layout))
        assert not renderer.notice_rect.colliderect(ui.board_frame_rect(layout))


class TestIcon:
    def test_window_icon_set_before_window(self, ui, gomoku, layout, monkeypatch):
        """set_icon 要在 set_mode 之前呼叫，部分平台之後設定不會生效。"""
        calls = []
        real_set_icon, real_set_mode = pygame.display.set_icon, pygame.display.set_mode
        monkeypatch.setattr(pygame.display, "set_icon",
                            lambda s: calls.append(("icon", s.get_size())) or real_set_icon(s))
        monkeypatch.setattr(pygame.display, "set_mode",
                            lambda *a, **k: calls.append(("mode",)) or real_set_mode(*a, **k))
        ui.Renderer(layout, gomoku._base_dir())
        assert calls[0][0] == "icon"
        assert ("mode",) in calls

    def test_exe_icon_has_standard_sizes(self, gomoku):
        import struct
        path = os.path.join(gomoku._base_dir(), "assets", "icon.ico")
        with open(path, "rb") as f:
            data = f.read()
        _reserved, kind, count = struct.unpack_from("<HHH", data, 0)
        assert kind == 1
        widths = {data[6 + 16 * i] or 256 for i in range(count)}
        assert {16, 32, 48} <= widths
