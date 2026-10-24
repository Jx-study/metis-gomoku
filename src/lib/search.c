#include <limits.h>
#include <string.h>
#include <stdbool.h>

#include "search.h"
#include "movegen.h"
#include "eval.h"
#include "zobrist.h"
#include "boardstate.h"
#include "vcf.h"

// Alpha Beta --> minimax函數
static int miniMax(int board[BOARD_MAX][BOARD_MAX], int depth, bool isMaximizing, int currentPlayer, int ai, int alpha, int beta, int minX, int maxX, int minY, int maxY) {
    // 檢查是否達到搜索深度或遊戲結束
    int result = checkWin(board, minX, maxX, minY, maxY, currentPlayer);

    // 如果遊戲結束，添加深度獎勵（越早勝利分數越高）
    if (result != 0) {
        if (result == ai) {
            // AI 勝利：基礎分 + 深度獎勵（depth 越大表示越早勝利）
            return 10000000 + depth * 10000;
        } else {
            // AI 失敗：基礎懲罰 - 深度懲罰（depth 越大表示越晚失敗，懲罰較小）
            return -10000000 - depth * 10000;
        }
    }

    // 到達搜索深度限制，返回靜態評估分數
    if (depth == 0) {
        return evaluate(board, minX, maxX, minY, maxY, ai);
    }

    // 在置換表中查找當前棋盤狀態
    HashEntry* entry = lookupHashEntry(currentZobristKey);

    // 先複製 bestMove 到區域變數：遞迴的 always-replace 寫入
    // 可能覆蓋同一個 bucket，迴圈中不能再讀 entry 指標本身
    // (0,0) 是合法座標，判定用 >= 0 而非 > 0
    int ttMoveX = -1, ttMoveY = -1;
    if (entry != NULL && entry->bestX >= 0) {
        ttMoveX = entry->bestX;
        ttMoveY = entry->bestY;
    }

    // 如果在置換表中找到了當前狀態，並且存儲的深度大於等於當前深度
    if (entry != NULL && entry->depth >= depth) {
        if (entry->flag == 'E') {
            return entry->score;
        } else if (entry->flag == 'L' && entry->score > alpha) {
            // 如果是下界，更新 alpha 值
            alpha = entry->score;
        } else if (entry->flag == 'U' && entry->score < beta) {
            // 如果是上界，更新 beta 值
            beta = entry->score;
        }

        // Alpha-Beta 剪枝
        if (alpha >= beta) {
            return entry->score;
        }
    }

    // flag 必須對照實際搜索用的視窗：TT 命中會收窄 alpha/beta
    // 用收窄前的邊界會把上界誤存成 'E'，覆蓋更深的正確 entry
    int alphaOrig = alpha, betaOrig = beta;

    int bestScore = isMaximizing ? INT_MIN : INT_MAX;
    int moveCount = 0;
    Move moves[BOARD_MAX * BOARD_MAX];
    sortMoves(board, moves, &moveCount, minX, maxX, minY, maxY, currentPlayer);
    if (moveCount == 0) return isMaximizing ? INT_MIN : INT_MAX;

    // PV-Move ordering：bestMove 不受 depth 限制，在截斷前的列表
    // 找到後 memmove 到首位，同時把它從硬截斷中救回來
    if (ttMoveX >= 0) {
        for (int i = 0; i < moveCount; i++) {
            if (moves[i].x == ttMoveX && moves[i].y == ttMoveY) {
                if (i > 0) {
                    Move ttMove = moves[i];
                    memmove(&moves[1], &moves[0], i * sizeof(Move));
                    moves[0] = ttMove;
                }
                break;
            }
        }
    }

    // 截斷保險：候選是降冪排序的，所以「保留所有 >= 門檻的著法」等於把截斷點
    // 延到第一個低於門檻的位置；必須在 PV-Move 搬移之後
    // moves[0] 換成 TT move 後不再有序，但 moves[1..] 仍降冪
    int count = moveCount > 10 ? 10 : moveCount;
    while (count < moveCount && moves[count].score >= FORCING_SCORE) count++;
    int bestMx = moves[0].x, bestMy = moves[0].y;
    for (int i = 0; i <count; i++) {
        int x = moves[i].x, y = moves[i].y;
        placeStone(board, x, y, currentPlayer);
        updateZobristKey(x, y, currentPlayer);// 更新雜湊值
        // 遞迴呼叫 miniMax，切換到對手回合
        if (isMaximizing) {
            int score = miniMax(board, depth - 1, false, 3 - currentPlayer, ai, alpha, beta, minX, maxX, minY, maxY);
            if (score > bestScore) { bestScore = score; bestMx = x; bestMy = y; }
            // 更新 Alpha 值
            alpha = (bestScore > alpha) ? bestScore : alpha;
        }else {
            int score = miniMax(board, depth - 1, true, 3 - currentPlayer, ai, alpha, beta, minX, maxX, minY, maxY);
            if (score < bestScore) { bestScore = score; bestMx = x; bestMy = y; }
            // 更新 Beta 值
            beta = (bestScore < beta) ? bestScore : beta;
        }
        // 撤銷移動
        removeStone(board, x, y);
        updateZobristKey(x, y, currentPlayer); // 還原雜湊值

        // Alpha-Beta 剪枝
        if (alpha >= beta) break;
    }

    // 在返回分數之前，將結果存儲到置換表中
    char flag;
    if (bestScore <= alphaOrig) {
        flag = 'U';  // 上界 (fail-low)
    } else if (bestScore >= betaOrig) {
        flag = 'L';  // 下界 (fail-high)
    } else {
        flag = 'E';  // 精確值
    }
    storeHashEntry(currentZobristKey, depth, bestScore, flag, bestMx, bestMy);

    return bestScore;
}

// 找最佳落子（迭代加深：從深度 1 逐層加深，每層用上一層的最佳走法改善排序）
static void findBestMoveImpl(int board[BOARD_MAX][BOARD_MAX], int *bestX, int *bestY, int ai, int minX, int maxX, int minY, int maxY, int roundCounter) {
    static bool ttInitialized = false;
    if (!ttInitialized) {
        initTranspositionTable();
        ttInitialized = true;
    }
    // 每次搜索前以實際盤面重算，key 為絕對值，不依賴外部呼叫方逐手同步
    currentZobristKey = computeZobristKey(board);
    rebuildWindowIndex(board);
    rebuildNeighborCount(board);
    rebuildStoneList(board);
    int moveCount = 0;

    int maxDepth = MAX_DEPTH + (ai == 1 ? 1 : 0);
    if (roundCounter <=8 && maxDepth>6) maxDepth -=2;
    Move moves[BOARD_MAX * BOARD_MAX];
    sortMoves(board, moves, &moveCount, minX, maxX, minY, maxY, ai);
    // 截斷保險：同 miniMax，強制著法（成四/擋四等級）不受 top-N 截斷
    int count = moveCount > 12 ? 12 : moveCount;
    while (count < moveCount && moves[count].score >= FORCING_SCORE) count++;
    if (count == 0) return;
    *bestX = moves[0].x;
    *bestY = moves[0].y;

    // 算殺：找到強制勝就直接走，不必進主搜索
    // 擺在 sortMoves 之後，成五/擋五已由 endGame 快速路徑處理
    int vx, vy;
    if (vcfFindWin(board, ai, minX, maxX, minY, maxY, &vx, &vy)) {
        *bestX = vx;
        *bestY = vy;
        return;
    }

    for (int d = 1; d <= maxDepth; d++) {
        int bestScore = INT_MIN;
        int bestIdx = 0;
        int alpha = INT_MIN;
        for (int i = 0; i < count; i++) {
            int x = moves[i].x, y = moves[i].y;
            placeStone(board, x, y, ai);
            updateZobristKey(x,y,ai);
            int score = miniMax(board, d-1, false, 3 - ai, ai, alpha, INT_MAX, minX, maxX, minY, maxY);
            updateZobristKey(x,y,ai);
            removeStone(board, x, y);

            //printf("d=%d %d(x:%d,y:%d)--->%d\n",d,score,x,y,moves[i].score);
            if (score > bestScore) {
                bestScore = score;
                bestIdx = i;
            }
            if (bestScore > alpha) alpha = bestScore;
        }
        // 把本層最佳走法移到候選首位（其餘保持相對順序），供下一層優先搜索
        Move best = moves[bestIdx];
        memmove(&moves[1], &moves[0], bestIdx * sizeof(Move));
        moves[0] = best;
        *bestX = best.x;
        *bestY = best.y;
        // 已找到必勝走法，不需要再加深
        if (bestScore >= 10000000) break;
    }
}

// 對外入口：只在這裡開關 idxValid，保證有效期不跨越回 Python 的邊界
// 用包裝函式而非在 Impl 每個 return 前設偽，改動內部提前返回時不會漏設
void findBestMove(int board[BOARD_MAX][BOARD_MAX], int *bestX, int *bestY, int ai, int minX, int maxX, int minY, int maxY, int roundCounter) {
    // 先寫哨兵，Impl 的提前返回路徑就不必各自負責寫回
    *bestX = -1;
    *bestY = -1;
    idxValid = true;
    findBestMoveImpl(board, bestX, bestY, ai, minX, maxX, minY, maxY, roundCounter);
    idxValid = false;
}
