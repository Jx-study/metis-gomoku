#include "boardstate.h"
#include "pattern.h"

int windowIdx[2][BOARD_MAX][BOARD_MAX][4];
bool idxValid = false;
short stoneList[2][BOARD_MAX * BOARD_MAX];
int stoneCount[2];
unsigned char neighborCount[BOARD_MAX][BOARD_MAX];

// off 對應 encodeWindow 索引裡的位權指數：off<0 -> 4-off，off>0 -> 5-off
static int weightExp(int off) {
    return (off < 0) ? (4 - off) : (5 - off);
}

// 全盤重算 windowIdx，掛在搜索入口，不依賴逐手同步
void rebuildWindowIndex(int board[BOARD_MAX][BOARD_MAX]) {
    int dx[] = {1, 1, 0, -1};
    int dy[] = {0, 1, 1, 1};
    for (int p = 0; p < 2; p++) {
        for (int y = 0; y < BOARD_MAX; y++) {
            for (int x = 0; x < BOARD_MAX; x++) {
                for (int d = 0; d < 4; d++) {
                    windowIdx[p][y][x][d] = encodeWindow(board, x, y, dx[d], dy[d], p + 1);
                }
            }
        }
    }
}

// 落子/撤銷在鄰格窗口造成的增量修正，delta 為 +1/-1（落子/撤銷）
// 一次修正雙視角：該子對自己是 SELF、對對手是 OPP，權重分別是 delta 與 2*delta
static void adjustWindowIndex(int x, int y, int player, int delta) {
    int dx[] = {1, 1, 0, -1};
    int dy[] = {0, 1, 1, 1};
    int selfPlane = player - 1;
    int oppPlane = 2 - player;
    for (int d = 0; d < 4; d++) {
        for (int off = -5; off <= 5; off++) {
            if (off == 0) continue;
            int nx = x + off * dx[d];
            int ny = y + off * dy[d];
            if (nx < 0 || nx >= BOARD_MAX || ny < 0 || ny >= BOARD_MAX) continue;   // 牆不參與增量
            int w = POW3[weightExp(-off)];
            windowIdx[selfPlane][ny][nx][d] += delta * w;        // 己方視角：EMPTY -> SELF
            windowIdx[oppPlane][ny][nx][d]  += 2 * delta * w;    // 敵方視角：EMPTY -> OPP
        }
    }
}

// 全盤重算 stoneList，掛在搜索入口，不依賴逐手同步
void rebuildStoneList(int board[BOARD_MAX][BOARD_MAX]) {
    stoneCount[0] = 0;
    stoneCount[1] = 0;
    for (int y = 0; y < BOARD_MAX; y++) {
        for (int x = 0; x < BOARD_MAX; x++) {
            int p = board[y][x] - 1;
            if (p == 0 || p == 1) stoneList[p][stoneCount[p]++] = (short)(y * BOARD_MAX + x);
        }
    }
}

// 落子在 stoneList 造成的增量修正：附加一筆
static void addStone(int x, int y, int player) {
    int p = player - 1;
    stoneList[p][stoneCount[p]++] = (short)(y * BOARD_MAX + x);
}

// 撤銷在 stoneList 造成的增量修正：線性搜尋該筆、與最後一筆對調再縮短
// 不依賴 pop-back 順序，LIFO 只是搜索的隱性不變量；每次只掃一色的十來筆
static void dropStone(int x, int y, int player) {
    int p = player - 1;
    short target = (short)(y * BOARD_MAX + x);
    for (int i = 0; i < stoneCount[p]; i++) {
        if (stoneList[p][i] == target) {
            stoneList[p][i] = stoneList[p][--stoneCount[p]];
            return;
        }
    }
}

#ifdef WINDOW_IDX_CHECK
#include <assert.h>
// debug build 專用：增量結果必須等於當場重算，掛在 placeStone/removeStone 之後
static void checkWindowIndex(int board[BOARD_MAX][BOARD_MAX]) {
    int dx[] = {1, 1, 0, -1};
    int dy[] = {0, 1, 1, 1};
    for (int p = 0; p < 2; p++) {
        for (int y = 0; y < BOARD_MAX; y++) {
            for (int x = 0; x < BOARD_MAX; x++) {
                for (int d = 0; d < 4; d++) {
                    assert(windowIdx[p][y][x][d] == encodeWindow(board, x, y, dx[d], dy[d], p + 1));
                }
            }
        }
    }
}
#endif

// 全盤重算 neighborCount，掛在搜索入口，不依賴逐手同步
void rebuildNeighborCount(int board[BOARD_MAX][BOARD_MAX]) {
    for (int y = 0; y < BOARD_MAX; y++) {
        for (int x = 0; x < BOARD_MAX; x++) {
            int count = 0;
            for (int dy = -ADJ_RANGE; dy <= ADJ_RANGE; dy++) {
                for (int dx = -ADJ_RANGE; dx <= ADJ_RANGE; dx++) {
                    if (dx == 0 && dy == 0) continue;
                    int nx = x + dx, ny = y + dy;
                    if (nx >= 0 && nx < BOARD_MAX && ny >= 0 && ny < BOARD_MAX && board[ny][nx] != 0) count++;
                }
            }
            neighborCount[y][x] = (unsigned char)count;
        }
    }
}

// 落子/撤銷在 5×5 鄰域造成的增量修正，delta 為 +1/-1（落子/撤銷）
static void adjustNeighborCount(int x, int y, int delta) {
    for (int dy = -ADJ_RANGE; dy <= ADJ_RANGE; dy++) {
        for (int dx = -ADJ_RANGE; dx <= ADJ_RANGE; dx++) {
            if (dx == 0 && dy == 0) continue;
            int nx = x + dx, ny = y + dy;
            if (nx < 0 || nx >= BOARD_MAX || ny < 0 || ny >= BOARD_MAX) continue;
            neighborCount[ny][nx] += delta;
        }
    }
}

#ifdef WINDOW_IDX_CHECK
// debug build 專用：增量結果必須等於當場重算，掛在 placeStone/removeStone 之後
static void checkNeighborCount(int board[BOARD_MAX][BOARD_MAX]) {
    for (int y = 0; y < BOARD_MAX; y++) {
        for (int x = 0; x < BOARD_MAX; x++) {
            int count = 0;
            for (int dy = -ADJ_RANGE; dy <= ADJ_RANGE; dy++) {
                for (int dx = -ADJ_RANGE; dx <= ADJ_RANGE; dx++) {
                    if (dx == 0 && dy == 0) continue;
                    int nx = x + dx, ny = y + dy;
                    if (nx >= 0 && nx < BOARD_MAX && ny >= 0 && ny < BOARD_MAX && board[ny][nx] != 0) count++;
                }
            }
            assert(neighborCount[y][x] == (unsigned char)count);
        }
    }
}

// debug build 專用：stoneList 當場重掃棋盤，比對兩邊的集合（不計順序）
static void checkStoneList(int board[BOARD_MAX][BOARD_MAX]) {
    for (int p = 0; p < 2; p++) {
        int count = 0;
        for (int y = 0; y < BOARD_MAX; y++) {
            for (int x = 0; x < BOARD_MAX; x++) {
                if (board[y][x] != p + 1) continue;
                count++;
                short cell = (short)(y * BOARD_MAX + x);
                bool found = false;
                for (int i = 0; i < stoneCount[p]; i++) {
                    if (stoneList[p][i] == cell) { found = true; break; }
                }
                assert(found);
            }
        }
        assert(count == stoneCount[p]);
    }
}
#endif

// 落子單一入口，賦值後同步增量修正 windowIdx 與 neighborCount，不動 Zobrist key
void placeStone(int board[BOARD_MAX][BOARD_MAX], int x, int y, int player) {
    board[y][x] = player;
    adjustWindowIndex(x, y, player, 1);
    adjustNeighborCount(x, y, 1);
    addStone(x, y, player);
#ifdef WINDOW_IDX_CHECK
    checkWindowIndex(board);
    checkNeighborCount(board);
    checkStoneList(board);
#endif
}

// 撤銷單一入口，對稱於 placeStone；落子色從盤面現值讀出，呼叫端不必多帶參數
void removeStone(int board[BOARD_MAX][BOARD_MAX], int x, int y) {
    int player = board[y][x];
    adjustWindowIndex(x, y, player, -1);
    adjustNeighborCount(x, y, -1);
    dropStone(x, y, player);
    board[y][x] = 0;
#ifdef WINDOW_IDX_CHECK
    checkWindowIndex(board);
    checkNeighborCount(board);
    checkStoneList(board);
#endif
}
