#include <stdlib.h>

#include "vcf.h"
#include "boardstate.h"
#include "lines.h"
#include "movegen.h"

// VCF：連續衝四的強制勝搜索
// 守方應手唯一（擋成五點），樹極窄，故能搜得比主搜索 7 層深很多。
// 只算衝四／活四，不含應手不唯一的活三（那是 VCT）；守方擋出反四則放棄該線；
// 守方已有成五點則衝四救不了，寧可漏殺，不可誤判必勝

// 直接數成五點而非用 checkLine 分類：恰 1 個是衝四，2 個以上是活四
// 與 judgeMove 共用同一套判定，避免規則漂移

#define VCF_MAX_PLY 16        // 攻方著手數上限（= 最多算 8 連沖）
#define VCF_MAX_NODES 200000  // 節點預算：算殺樹窄是常態不是保證，仍需防爆炸
#define VCF_MAX_FIVE_PTS 8

static long long vcfNodes = 0;

// 列出 player 落子即成五的空點，回傳總數（可能多於寫入 pts 的數量）
static int listFivePoints(int board[BOARD_MAX][BOARD_MAX], int player,
                          int minX, int maxX, int minY, int maxY,
                          int pts[][2], int maxPts) {
    int n = 0;
    for (int y = minY; y <= maxY; y++) {
        for (int x = minX; x <= maxX; x++) {
            if (board[y][x] != 0 || !hasAdjacentPiece(board, x, y)) continue;
            if (!winsAt(board, x, y, player)) continue;
            if (n < maxPts) { pts[n][0] = x; pts[n][1] = y; }
            n++;
        }
    }
    return n;
}

// 列舉 player 的成四著法（含直接成五），依威脅程度降冪排序
static int listFourMoves(int board[BOARD_MAX][BOARD_MAX], int player, Move *moves,
                         int minX, int maxX, int minY, int maxY) {
    int n = 0;
    for (int y = minY; y <= maxY; y++) {
        for (int x = minX; x <= maxX; x++) {
            if (board[y][x] != 0 || !hasAdjacentPiece(board, x, y)) continue;
            int verdict = judgeMove(board, x, y, player);
            if (verdict < 1) continue;   // 已有子，或黑棋禁手點不能當攻擊手段
            if (verdict == 2) {          // 直接成五
                moves[n++] = (Move){x, y, 1000000};
                continue;
            }
            int line[16] = {0};
            checkLine(board, x, y, player, line);
            if (line[4] || line[10])      moves[n++] = (Move){x, y, 100000};  // 活四
            else if (line[8] || line[12]) moves[n++] = (Move){x, y, 10000};   // 衝四
        }
    }
    qsort(moves, n, sizeof(Move), Big_Small);
    return n;
}

// attacker 是否有連續衝四強制勝；是則回傳 1 並寫入首手 *wx,*wy
static int vcfSearch(int board[BOARD_MAX][BOARD_MAX], int attacker, int ply,
                     int minX, int maxX, int minY, int maxY, int *wx, int *wy) {
    if (ply > VCF_MAX_PLY) return 0;
    if (++vcfNodes > VCF_MAX_NODES) return 0;

    int defender = 3 - attacker;
    Move moves[BOARD_MAX * BOARD_MAX];
    int n = listFourMoves(board, attacker, moves, minX, maxX, minY, maxY);

    for (int i = 0; i < n; i++) {
        int x = moves[i].x, y = moves[i].y;
        if (judgeMove(board, x, y, attacker) == 2) {   // 直接成五，不必再算
            *wx = x; *wy = y;
            return 1;
        }

        placeStone(board, x, y, attacker);
        int pts[VCF_MAX_FIVE_PTS][2];
        int atkN = listFivePoints(board, attacker, minX, maxX, minY, maxY, pts, VCF_MAX_FIVE_PTS);
        if (atkN == 0) { removeStone(board, x, y); continue; }  // 沒造成成五威脅 -> 不具強制性

        // 守方當下已能成五：他搶先落子就贏了，攻方的衝四救不回來
        int defPts[VCF_MAX_FIVE_PTS][2];
        if (listFivePoints(board, defender, minX, maxX, minY, maxY, defPts, VCF_MAX_FIVE_PTS) > 0) {
            removeStone(board, x, y);
            continue;
        }

        if (atkN >= 2) {   // 活四：守方擋一點，攻方下另一點即成五
            removeStone(board, x, y);
            *wx = x; *wy = y;
            return 1;
        }

        int bx = pts[0][0], by = pts[0][1];   // 衝四：守方唯一擋點
        if (judgeMove(board, bx, by, defender) < 0) {   // 守方是黑棋且該點是禁手 -> 擋不了
            removeStone(board, x, y);
            *wx = x; *wy = y;
            return 1;
        }

        placeStone(board, bx, by, defender);
        // 反四：守方的擋子同時做出自己的四，攻方必須回應，保守放棄此線
        int counterFour = listFivePoints(board, defender, minX, maxX, minY, maxY, defPts, VCF_MAX_FIVE_PTS);
        int win = 0;
        if (counterFour == 0) {
            int nx, ny;
            win = vcfSearch(board, attacker, ply + 2, minX, maxX, minY, maxY, &nx, &ny);
        }
        removeStone(board, bx, by);
        removeStone(board, x, y);

        if (win) { *wx = x; *wy = y; return 1; }
    }
    return 0;
}

// 根節點入口：重置節點預算後開跑
int vcfFindWin(int board[BOARD_MAX][BOARD_MAX], int attacker,
               int minX, int maxX, int minY, int maxY, int *wx, int *wy) {
    vcfNodes = 0;
    return vcfSearch(board, attacker, 1, minX, maxX, minY, maxY, wx, wy);
}

long long getVcfNodes(void) { return vcfNodes; }
