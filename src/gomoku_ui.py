"""Pygame 渲染與事件迴圈。

遊戲流程在 `Gomoku.GameController`，本模組只負責把狀態畫出來、把輸入轉給
控制器。像素與棋盤格的換算只有 `pixel_to_cell` 一份，hover 與點擊共用。
"""
import math
import os

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
# 從其他視窗切回來的第一下點擊照常送出，否則 SDL 只拿它取得焦點
os.environ.setdefault("SDL_MOUSE_FOCUS_CLICKTHROUGH", "1")
import pygame

import theme

FONT_FILE = os.path.join("assets", "fonts", "NotoSansTC-Subset.ttf")
FPS = 30

RULES_TEXT = [
    "勝利條件：五子連線",
    "",
    "1. 黑方在棋盤中心落下第 1 手棋。",
    "2. 白方在棋盤中心的 3x3 方格內落下第 2 手棋。",
    "3. 黑方在棋盤中心的 5x5 方格內落下第 3 手棋，確立 26 種連珠開局之一。",
    "4. 白方選擇自己與對方的棋子顏色（稱為「三手交換」）。",
    "5. 白方在棋盤的空點處落下第 4 手。",
    "6. 黑方有三三、四四及長連禁手（包含四三三、三三四...），在連成五子前，無論主動或被動下出禁著點，立即判定為負。換言之，黑方唯一獲勝的可能為下出四三。",
    "7. 白方無任何禁點，長連亦為勝。",
    "8. 五連與禁手同時形成則不算禁手，黑方可算獲勝。",
    "",
    "禁點規則說明：",
    "1. 雙活三禁點",
    "2. 雙活四禁點",
    "3. 長連禁點",
    "注意：若其中一個三無法形成連四，僅能成為死四，則禁點不成立。此即為「以禁解禁」原則。",
    "",
    "黑棋回合會以灰色 × 標出禁手點。",
    "詳細資訊請到 https://587.renju.org.tw/teach/teach018.htm",
]

_NO_LINE_START = "，。、）」：；！？"

BUTTON_LABELS = {"restart": "重玩", "undo": "悔棋", "rules": "規則"}
# 兩行標籤：全形括號在字身內偏一側擺放，放進單行會讓文字看起來不置中
ROLE_LABELS = {1: ("執黑", "先手"), 2: ("執白", "後手")}


# ---------- 版面與命中判定（只依賴 layout，可單獨測試）----------

# 像素座標換成最近的棋盤格；落在棋盤外緣半格以外回傳 None
def pixel_to_cell(layout, pos):
    x = math.floor((pos[0] - layout.MARGIN) / layout.GRID + 0.5)
    y = math.floor((pos[1] - layout.MARGIN) / layout.GRID + 0.5)
    if 0 <= x < layout.BOARD_MAX and 0 <= y < layout.BOARD_MAX:
        return x, y
    return None


# 棋盤木框：格線外擴半格多一點，邊緣的棋子才不會超出木框
def board_frame_rect(layout):
    pad = layout.GRID // 2 + 4
    return pygame.Rect(layout.MARGIN - pad, layout.MARGIN - pad, layout.LEN + 2 * pad, layout.LEN + 2 * pad)


# 棋盤上方標題列的中線
def header_center_y(layout):
    return board_frame_rect(layout).top // 2


def cell_center(layout, x, y):
    return layout.MARGIN + x * layout.GRID, layout.MARGIN + y * layout.GRID


# 三顆等寬按鈕以視窗中心對齊，置於棋盤下方
def button_rects(layout):
    row_w = 3 * layout.BUTTON_W + 2 * layout.BUTTON_GAP
    left = layout.CENTER_X - row_w // 2
    step = layout.BUTTON_W + layout.BUTTON_GAP
    return {name: pygame.Rect(left + i * step, layout.BUTTON_TOP, layout.BUTTON_W, layout.BUTTON_H)
            for i, name in enumerate(("restart", "undo", "rules"))}


def button_at(layout, pos):
    for name, rect in button_rects(layout).items():
        if rect.collidepoint(pos):
            return name
    return None


def _dialog_center(layout):
    return layout.CENTER_X, layout.MARGIN + layout.LEN // 2


def role_rects(layout):
    cx, cy = _dialog_center(layout)
    return {1: pygame.Rect(cx - 130, cy, 120, 50), 2: pygame.Rect(cx + 10, cy, 120, 50)}


def role_at(layout, pos):
    for player, rect in role_rects(layout).items():
        if rect.collidepoint(pos):
            return player
    return None


def rules_panel_rect(layout):
    return pygame.Rect(30, 30, layout.WIN_W - 60, layout.WIN_H - 60)


def rules_close_rect(layout):
    panel = rules_panel_rect(layout)
    return pygame.Rect(panel.centerx - 50, panel.bottom - 55, 100, 40)


# 滑鼠左鍵的路由：規則疊加層優先，其次角色選擇、按鈕、棋盤
def dispatch(ctl, renderer, layout, pos):
    if ctl.show_rules:
        if rules_close_rect(layout).collidepoint(pos):
            ctl.toggle_rules()
        return
    button = button_at(layout, pos)
    if button == "rules":
        ctl.toggle_rules()
        renderer.rules_offset = 0
        return
    if button == "restart":
        ctl.restart()
        return
    if button == "undo":
        ctl.undo()
        return
    if ctl.phase == "role":
        player = role_at(layout, pos)
        if player is not None:
            ctl.choose_role(player)
        return
    cell = pixel_to_cell(layout, pos)
    if cell is None:
        ctl.click_off_board()
    else:
        ctl.click(*cell)


# ---------- 繪圖 ----------

def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _fmt_clock(seconds):
    seconds = int(seconds)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class Renderer:
    def __init__(self, layout, base_dir):
        # 只用到畫面與字型，不初始化音效（CI 與部分 Linux 環境沒有音效裝置）
        pygame.display.init()
        pygame.font.init()
        self.layout = layout
        # 8-bit 調色盤 GIF 不能 smoothscale；視窗建立前也不能 convert_alpha，改畫進 32-bit Surface
        gif = pygame.image.load(os.path.join(base_dir, "200w.gif"))
        icon = pygame.Surface(gif.get_size(), pygame.SRCALPHA, 32)
        icon.blit(gif, (0, 0))
        # 部分平台在建立視窗之後才設 icon 不會生效
        pygame.display.set_icon(pygame.transform.smoothscale(icon, (64, 64)))
        self.screen = pygame.display.set_mode((layout.WIN_W, layout.WIN_H))
        pygame.display.set_caption("Gomoku")
        self._font_path = os.path.join(base_dir, FONT_FILE)
        self._fonts = {}
        self.notice_rect = None
        self.piece_r = layout.GRID // 2 - 1
        self._pieces = {1: self._make_piece(1), 2: self._make_piece(2)}
        self.rules_offset = 0
        self._rules_lines = self._wrap_rules()
        visible = rules_close_rect(layout).top - 10 - self._rules_text_top()
        line_h = self.font(theme.FONT_RULES).get_linesize()
        self.rules_max_offset = max(0, len(self._rules_lines) * line_h - visible)

    def font(self, size):
        if size not in self._fonts:
            self._fonts[size] = pygame.font.Font(self._font_path, size)
        return self._fonts[size]

    # 棋子預先畫成帶漸層與高光的 Surface，每幀直接 blit
    def _make_piece(self, color):
        r = self.piece_r
        top, bottom = ((theme.BLACK_PIECE_TOP, theme.BLACK_PIECE_BOTTOM) if color == 1
                       else (theme.WHITE_PIECE_TOP, theme.WHITE_PIECE_BOTTOM))
        surf = pygame.Surface((2 * r + 2, 2 * r + 2), pygame.SRCALPHA)
        c = r + 1
        steps = r
        for i in range(steps):
            t = i / steps
            rr = r - i * r / steps
            off = i * r / (steps * 3)          # 亮部往左上偏
            pygame.draw.circle(surf, _lerp(bottom, top, t), (c - off, c - off), rr)
        pygame.draw.circle(surf, theme.PIECE_OUTLINE, (c, c), r, 1)
        return surf

    def _rules_text_top(self):
        return rules_panel_rect(self.layout).top + 60

    # 逐字換行；句讀不放行首，改掛在上一行尾，因此換行寬度預留一個字
    def _wrap_rules(self):
        font = self.font(theme.FONT_RULES)
        width = rules_panel_rect(self.layout).width - 40 - theme.FONT_RULES
        lines = []
        for para in RULES_TEXT:
            line = ""
            for ch in para:
                if font.size(line + ch)[0] > width and ch not in _NO_LINE_START:
                    lines.append(line)
                    line = ch
                else:
                    line += ch
            lines.append(line)
        return lines

    def scroll_rules(self, dy):
        self.rules_offset = min(max(0, self.rules_offset + dy), self.rules_max_offset)

    def hover_cell(self, ctl, pos):
        if ctl.phase != "player" or ctl.show_rules:
            return None
        cell = pixel_to_cell(self.layout, pos)
        if cell is None or not ctl.state.is_empty(*cell):
            return None
        return cell

    def _text(self, text, size, color, center=None, topleft=None, midleft=None, midright=None):
        surf = self.font(size).render(text, True, color)
        rect = surf.get_rect()
        if center:
            rect.center = center
        elif topleft:
            rect.topleft = topleft
        elif midleft:
            rect.midleft = midleft
        elif midright:
            rect.midright = midright
        self.screen.blit(surf, rect)
        return rect

    def draw_frame(self, ctl, mouse_pos):
        L = self.layout
        self.screen.fill(theme.WINDOW_BG)
        self._draw_board()
        self._draw_stones(ctl)
        self._draw_marks(ctl, mouse_pos)
        self.notice_rect = self._text(ctl.notice, theme.FONT_NOTICE, theme.TEXT_PRIMARY,
                                      center=(L.CENTER_X, header_center_y(L)))
        self._draw_buttons(ctl, mouse_pos)
        self._draw_status(ctl)
        if ctl.phase == "role" and not ctl.show_rules:
            self._draw_role_select(mouse_pos)
        if ctl.show_rules:
            self._draw_rules(mouse_pos)

    def _draw_board(self):
        L = self.layout
        pygame.draw.rect(self.screen, theme.BOARD_BG, board_frame_rect(L), border_radius=6)
        for i in range(L.NUM):
            p = L.MARGIN + i * L.GRID
            pygame.draw.line(self.screen, theme.GRID_LINE, (L.MARGIN, p), (L.MARGIN + L.LEN, p))
            pygame.draw.line(self.screen, theme.GRID_LINE, (p, L.MARGIN), (p, L.MARGIN + L.LEN))
        pygame.draw.circle(self.screen, theme.STAR_POINT, cell_center(L, L.MIDPOINT_X, L.MIDPOINT_Y), 4)

    def _draw_stones(self, ctl):
        font = self.font(theme.FONT_MOVE_NUM)
        for n, (x, y, color) in enumerate(ctl.state.moves, start=1):
            cx, cy = cell_center(self.layout, x, y)
            piece = self._pieces[color]
            self.screen.blit(piece, piece.get_rect(center=(cx, cy)))
            num = font.render(str(n), True, theme.TEXT_MOVE_NUM)
            self.screen.blit(num, num.get_rect(center=(cx, cy)))

    def _draw_marks(self, ctl, mouse_pos):
        L = self.layout
        for x, y in ctl.forbidden:
            cx, cy = cell_center(L, x, y)
            d = L.GRID // 5
            pygame.draw.line(self.screen, theme.FORBIDDEN_MARK, (cx - d, cy - d), (cx + d, cy + d), 2)
            pygame.draw.line(self.screen, theme.FORBIDDEN_MARK, (cx - d, cy + d), (cx + d, cy - d), 2)
        if ctl.state.moves:
            x, y, _ = ctl.state.moves[-1]
            cx, cy = cell_center(L, x, y)
            pygame.draw.rect(self.screen, theme.LAST_MOVE_MARK,
                             (cx - self.piece_r - 1, cy - self.piece_r - 1, 2 * self.piece_r + 3, 2 * self.piece_r + 3), 1)
        cell = self.hover_cell(ctl, mouse_pos)
        if cell is not None and cell not in ctl.forbidden:
            ghost = self._pieces[ctl.player].copy()
            ghost.set_alpha(theme.GHOST_ALPHA)
            self.screen.blit(ghost, ghost.get_rect(center=cell_center(L, *cell)))
        if ctl.win_line:
            ends = sorted(ctl.win_line)
            pygame.draw.line(self.screen, theme.WIN_LINE_HIGHLIGHT,
                             cell_center(L, *ends[0]), cell_center(L, *ends[-1]), 5)

    def _draw_button(self, rect, label, enabled, hovered):
        bg = theme.BUTTON_BG_HOVER if (enabled and hovered) else theme.BUTTON_BG
        pygame.draw.rect(self.screen, bg, rect, border_radius=8)
        pygame.draw.rect(self.screen, theme.BUTTON_BORDER, rect, 1, border_radius=8)
        color = theme.TEXT_PRIMARY if enabled else theme.BUTTON_DISABLED_TEXT
        self._text(label, theme.FONT_BUTTON, color, center=rect.center)

    def _draw_buttons(self, ctl, mouse_pos):
        enabled = {"restart": ctl.can_restart, "undo": ctl.can_undo, "rules": True}
        for name, rect in button_rects(self.layout).items():
            self._draw_button(rect, BUTTON_LABELS[name], enabled[name], rect.collidepoint(mouse_pos))

    def _draw_status(self, ctl):
        L = self.layout
        bar = pygame.Rect(0, L.WIN_H - L.STATUS_H, L.WIN_W, L.STATUS_H)
        pygame.draw.rect(self.screen, theme.STATUS_BG, bar)
        size, color = theme.FONT_STATUS, theme.TEXT_PRIMARY
        self._text(f"第 {ctl.roundCounter} 手", size, color, midleft=(12, bar.centery))
        totals = f"黑 {_fmt_clock(ctl.colour_total(1))}　白 {_fmt_clock(ctl.colour_total(2))}"
        self._text(totals, size, color, center=(L.CENTER_X, bar.centery))
        if ctl.phase == "ai":
            right = f"AI 思考中 {ctl.turn_elapsed():.1f}s"
        elif ctl.phase == "player":
            right = f"本手 {ctl.turn_elapsed():.0f}s"
        elif ctl.last_ai_time is not None:
            right = f"AI 耗時 {ctl.last_ai_time:.2f}s"
        else:
            right = ""
        self._text(right, size, color, midright=(L.WIN_W - 12, bar.centery))

    def _dim(self):
        dim = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
        dim.fill(theme.OVERLAY_DIM)
        self.screen.blit(dim, (0, 0))

    def _draw_role_select(self, mouse_pos):
        self._dim()
        cx, cy = _dialog_center(self.layout)
        panel = pygame.Rect(cx - 160, cy - 80, 320, 160)
        pygame.draw.rect(self.screen, theme.PANEL_BG, panel, border_radius=10)
        pygame.draw.rect(self.screen, theme.BUTTON_BORDER, panel, 1, border_radius=10)
        self._text("選擇執子", theme.FONT_NOTICE, theme.TEXT_PRIMARY, center=(cx, cy - 40))
        for player, rect in role_rects(self.layout).items():
            hovered = rect.collidepoint(mouse_pos)
            if player == 1:
                bg = theme.BLACK_PIECE_TOP if hovered else theme.BLACK_PIECE_BOTTOM
                fg = theme.TEXT_ON_DARK
            else:
                bg = theme.BUTTON_BG_HOVER if hovered else theme.WHITE_PIECE_TOP
                fg = theme.TEXT_PRIMARY
            pygame.draw.rect(self.screen, bg, rect, border_radius=8)
            pygame.draw.rect(self.screen, theme.BUTTON_BORDER, rect, 1, border_radius=8)
            main, sub = ROLE_LABELS[player]
            self._text(main, theme.FONT_BUTTON, fg, center=(rect.centerx, rect.centery - 8))
            self._text(sub, theme.FONT_MOVE_NUM, fg, center=(rect.centerx, rect.centery + 12))

    def _draw_rules(self, mouse_pos):
        self._dim()
        panel = rules_panel_rect(self.layout)
        pygame.draw.rect(self.screen, theme.PANEL_BG, panel, border_radius=10)
        self._text("遊戲規則", theme.FONT_NOTICE, theme.TEXT_PRIMARY, center=(panel.centerx, panel.top + 30))
        close = rules_close_rect(self.layout)
        top = self._rules_text_top()
        area = pygame.Rect(panel.left + 20, top, panel.width - 40, close.top - 10 - top)
        font = self.font(theme.FONT_RULES)
        line_h = font.get_linesize()
        self.screen.set_clip(area)
        for i, line in enumerate(self._rules_lines):
            y = top + i * line_h - self.rules_offset
            if area.top - line_h < y < area.bottom:
                self.screen.blit(font.render(line, True, theme.TEXT_PRIMARY), (area.left, y))
        self.screen.set_clip(None)
        self._draw_button(close, "關閉", True, close.collidepoint(mouse_pos))


# ---------- 事件迴圈 ----------

def run(controller_cls, engine, layout, base_dir):
    renderer = Renderer(layout, base_dir)
    ai_done = pygame.event.custom_type()
    # 背景執行緒只 post 事件，狀態由主執行緒在收到事件時套用
    ctl = controller_cls(engine, post=lambda x, y: pygame.event.post(pygame.event.Event(ai_done, x=x, y=y)))
    clock = pygame.time.Clock()
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                dispatch(ctl, renderer, layout, event.pos)
            elif event.type == pygame.MOUSEWHEEL and ctl.show_rules:
                renderer.scroll_rules(-event.y * 30)
            elif event.type == ai_done:
                ctl.apply_ai_move(event.x, event.y)
        renderer.draw_frame(ctl, pygame.mouse.get_pos())
        pygame.display.flip()
        clock.tick(FPS)
    pygame.quit()
    return ctl
