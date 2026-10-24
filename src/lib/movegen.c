#include <stdlib.h>
#include <string.h>
#include <stdio.h>

#include "movegen.h"
#include "lines.h"
#include "eval.h"
#include "boardstate.h"

// 檢查5*5周圍是否有棋子；索引可信時查表，否則退回掃描
bool hasAdjacentPiece(int board[BOARD_MAX][BOARD_MAX], int x, int y) {
    if (idxValid) return neighborCount[y][x] > 0;
    int range = 2;
    for (int dx = -range; dx <= range; dx++) {
        for (int dy = -range; dy <= range; dy++) {
            if (dx == 0 && dy == 0) continue;
            int nx = x + dx, ny = y + dy;
            if (nx >= 0 && nx < BOARD_MAX && ny >= 0 && ny < BOARD_MAX && board[ny][nx] != 0) {
                return true;
            }
        }
    }
    return false;
}

// 通用走法的合法性判斷：非空位、有鄰子、黑棋不犯禁手
// sortMoves 的一般迴圈與零候選 fallback 共用，避免兩處各自維護同一條規則
static inline bool isCandidateLegal(int board[BOARD_MAX][BOARD_MAX], int x, int y, int player) {
    if (board[y][x] != 0 || !hasAdjacentPiece(board, x, y)) return false;
    if (player == 1 && checkUnValid(board, x, y, player) != 1) return false;
    return true;
}

// 分數大到小排序
// 同分依座標排序：qsort 不穩定，交給 libc 決定的話各平台走法不同
int Big_Small(const void* a, const void* b) {
    Move *moveA = (Move *)a;
    Move *moveB = (Move *)b;
    if (moveB->score != moveA->score) return moveB->score - moveA->score;
    if (moveA->y != moveB->y) return moveA->y - moveB->y;
    return moveA->x - moveB->x;
}

// 快速處理勝局/敗局
// selfCanFive / oppCanFive 由呼叫端從棋型計數導出，見 sortMoves
int endGame(int board[BOARD_MAX][BOARD_MAX], int *bestX, int *bestY, int minX, int maxX, int minY, int maxY, int currentPlayer, bool selfCanFive, bool oppCanFive){
    int counter =0;
    // counter 併進 for 的遞增段：迴圈體現在有 continue，留在體末會漏遞增
    for (int player = currentPlayer; counter <2; player = 3 - player, counter++){
        // 該方沒有成五點，這一趟全框掃描整個跳過
        if (!(counter == 0 ? selfCanFive : oppCanFive)) continue;
        for (int x = minX; x <= maxX; x++) {
            for (int y = minY; y <= maxY; y++) {
                if (board[y][x] == 0 && hasAdjacentPiece(board, x, y)) {
                    // 實際落子的是 currentPlayer，黑棋禁手點不能下
                    if (currentPlayer == 1 && judgeMove(board, x, y, 1) < 1) continue;
                    // ai勝利（直接落子）/ 對手勝利（防守）：單點判定，免落子、免全盤掃描
                    // winsAt 直接查 patternTable，不經 judgeMove／checkLine 的完整分類
                    if (winsAt(board, x, y, player)) {
                        *bestX = x;
                        *bestY = y;
                        return 1;  // 立即返回獲勝移動
                    }
                }
            }
        }
    }
    return 0;
}

// 啓發式函數Heuristic Function：快速評估落點后排序
void sortMoves(int board[BOARD_MAX][BOARD_MAX], Move* moves, int *count, int minX, int maxX, int minY, int maxY, int player) {
    *count = 0;

    // 統計當前AI和玩家的棋形數
    int my_now[16] = {0}, op_now[16] = {0};
    checkNow(board, minX, maxX, minY, maxY, player, my_now);
    checkNow(board, minX, maxX, minY, maxY, 3 - player, op_now);

    // 成五點存在的充要條件：該方有四。任何成五點的窗口裡都有四顆同色，
    // 那四顆各自為中心必被分類成活四/沖四/跳活四/跳四之一
    // 併入五連與長連：根節點不經 checkWin，盤上已成五時 endGame 仍須掃
    bool selfCanFive = (my_now[4] + my_now[5] + my_now[8] + my_now[10] + my_now[12] + my_now[15]) > 0;
    bool oppCanFive  = (op_now[4] + op_now[5] + op_now[8] + op_now[10] + op_now[12] + op_now[15]) > 0;

    // 最高優先級：檢查是否有立即獲勝的棋路
    int bestX = -1, bestY = -1;
    if (endGame(board, &bestX, &bestY, minX, maxX, minY, maxY, player, selfCanFive, oppCanFive)) {
        moves[(*count)++] = (Move){bestX, bestY, 9999999};
        return;
    }

    // 策略：條件+分數+檢查對象
    // [0:0, 1:0, 2:活二，3:活三，4:活四，5:五連，6:眠二，7:純衝四眠三，8:衝四，
    //  9:跳活三，10:跳活四，11:偏活跳三，12:跳四，13:偏活三，14:純衝四跳三，15:長連]
    // 優先級：五連>活四>跳活四>衝四=活三>跳四>....
    // 3/9/11/13 都能成活四（RIF 的 Three），威脅同級，防守/進攻觸發條件必須一併涵蓋
    // 曾經漏掉 11：只認 3/9 讓兩端仍開放的跳三（見 loss-analysis-jump-three-gap.md）
    // 從未進入候選列表，AI 因此漏防、輸掉一局
    struct {
        bool condition;
        int score;
        int check_player;
    } strategy_moves[] = {
        // 次優先級：對手已有兩個三連綫/23連綫，且自己沒有活三以上的連綫（防守)
        {
            op_now[2] > 0 && (op_now[3]+op_now[7]+op_now[9]+op_now[11]+op_now[13]+op_now[14])/3 >= 1,
            99999,
            3 - player  // 檢查對手
        },

        // 第三優先級：若自己已經有活三/跳活三/偏活三/偏活跳三必勝了,且對手沒有活三以上的連綫（進攻）
        {
            (my_now[3] > 0 || my_now[9] > 0 || my_now[13] > 0 || my_now[11] > 0) &&
            op_now[4] == 0 && op_now[8] == 0 && op_now[10] == 0,
            100000,
            player  // 檢查自己
        },

        // 第四優先級：對手已有活三/跳活三/偏活三/偏活跳三，且自己沒有活三以上的連綫（防守）
        {
            (op_now[3] > 0 || op_now[9] > 0 || op_now[13] > 0 || op_now[11] > 0) &&
            my_now[3] == 0 && my_now[4] == 0 && my_now[8] == 0 && my_now[10] == 0,
            88888,
            3 - player  // 檢查對手
        },
        // 第五優先級：無腦衝四（純衝四眠三/跳三只能推進到衝四，主動推進不虧）
        {
            my_now[7]>0 || my_now[14]>0,
            66666,
            player      // 檢查自己
        }
    };

    // 遍历每种策略
    for (int strategy = 0; strategy < 4; strategy++) {
        // 跳过不符合条件的策略
        if (!strategy_moves[strategy].condition) continue;

        // 遍历棋盘寻找符合策略的走法
        for (int x = minX; x <= maxX; x++) {
            for (int y = minY; y <= maxY; y++) {
                // 跳过无效位置；便宜的條件先過濾，禁手判定要掃線
                if (board[y][x] != 0 || !hasAdjacentPiece(board, x, y)) continue;
                if (player == 1 && checkUnValid(board, x, y, player) != 1) continue;

                // 检查位置的棋型
                int line[16] = {0};
                checkLine(board, x, y, strategy_moves[strategy].check_player, line);

                bool valid_move = false;
                switch (strategy) {
                    // 防御多重威胁线
                    case 0:
                        valid_move = (line[3] + line[7] + line[9] + line[11] + line[13] + line[14]) >= 1 &&
                                   (line[4] + line[8] + line[10] + line[12]) >= 1;
                        break;
                    // 主动创建活四
                    case 1:
                        valid_move = line[4] >= 1;
                        break;
                    // 防御对手活四
                    case 2:
                        valid_move = line[4] >= 1 || line[10] >= 1;
                        break;
                    // 主动创建衝四
                    case 3:
                        valid_move = line[8] >= 1 || line[10] >= 1 || line[12] >= 1;
                        break;
                }

                // 找到有效走法，添加到列表
                if (valid_move) {
                    moves[(*count)++] = (Move){x, y, strategy_moves[strategy].score};
                }
                memset(line, 0, sizeof(line));  // 重置line数组
            }
        }
    }
    // 已知限制：策略走法超過 4 個時跳過通用評估，一般著法根本沒生成
    // 截斷延伸只救得回已生成的強制手
    if (*count > 4) {
        // 這條出口也必須排序：呼叫端的截斷延伸靠降冪才能在第一個低於門檻處停下
        // 策略哨兵分數本身不遞減
        qsort(moves, *count, sizeof(Move), Big_Small);
        return;
    }
    // 若無適用策略：通用走法评估
    for (int x = minX; x <= maxX; x++) {
        for (int y = minY; y <= maxY; y++) {
            // 跳过无效位置；便宜的條件先過濾，禁手判定要掃線
            if (!isCandidateLegal(board, x, y, player)) continue;

            // 快速评估位置价值
            int score = quickEvaluate(board, x, y, minX, maxX, minY, maxY, player);
            if (score != 0) {  // 0 分點無攻防價值，不佔候選名額
                moves[(*count)++] = (Move){x, y, score};
            }
        }
    }

    // 錯誤檢查和排序
    // 保底：0 分孤立點會被上面的 if 濾光，仍需回傳合法點
    if (*count == 0) {
        for (int x = minX; x <= maxX && *count == 0; x++) {
            for (int y = minY; y <= maxY; y++) {
                if (!isCandidateLegal(board, x, y, player)) continue;
                moves[(*count)++] = (Move){x, y, 0};
                break;
            }
        }
    }
    if (*count == 0) return;  // 搜索框內真的無合法點，findBestMove 會留下 -1 哨兵

    qsort(moves, *count, sizeof(Move), Big_Small);
}
