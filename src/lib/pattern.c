#include <stdbool.h>

#include "pattern.h"

unsigned char patternTable[PATTERN_TABLE_SIZE];

// 3 的次方表，POW3[e] = 3^e，e 對應 weightExp 算出的位權指數
const int POW3[10] = {1, 3, 9, 27, 81, 243, 729, 2187, 6561, 19683};

// 把窗口編成 patternTable 索引：off 從 -5 到 +5 跳過中心，依序 idx = idx * 3 + cell
// 編解碼順序必須一致，對應的解碼在 initPatternTable
int encodeWindow(int board[BOARD_MAX][BOARD_MAX], int x, int y, int dx, int dy, int player) {
    int idx = 0;
    for (int off = -5; off <= 5; off++) {
        if (off == 0) continue;   // 中心不入索引
        int nx = x + off * dx;
        int ny = y + off * dy;
        int cell;
        if (nx < 0 || nx >= BOARD_MAX || ny < 0 || ny >= BOARD_MAX) {
            cell = CELL_OPP;
        } else if (board[ny][nx] == player) {
            cell = CELL_SELF;
        } else if (board[ny][nx] == 0) {
            cell = CELL_EMPTY;
        } else {
            cell = CELL_OPP;   // 對方棋子（含第三方）
        }
        idx = idx * 3 + cell;
    }
    return idx;
}

// 含中心的不間斷 SELF 長度
static int solidRun(int cells[11]) {
    int leftRun = 0, rightRun = 0;
    for (int j = 1; j < 6 && cells[5 - j] == CELL_SELF; j++) leftRun++;
    for (int j = 1; j < 6 && cells[5 + j] == CELL_SELF; j++) rightRun++;
    return leftRun + 1 + rightRun;
}

// 是否存在一個含中心、恰好五連的區間：區間內全為 SELF，且左右外側各一格
// 不得也是 SELF，否則屬於長連而非五連，依 RIF 不算成五
static bool makesFive(int cells[11]) {
    for (int start = 1; start <= 5; start++) {
        bool all = true;
        for (int k = 0; k < 5; k++) {
            if (cells[start + k] != CELL_SELF) { all = false; break; }
        }
        if (!all) continue;
        if (start - 1 >= 0 && cells[start - 1] == CELL_SELF) continue;
        if (start + 5 < 11 && cells[start + 5] == CELL_SELF) continue;
        return true;
    }
    return false;
}

// 四：能再加一子成五。回傳成五點的個數，兩個以上即活四
// 非 static：lines.c 的 threeSpotsInDirection 借用來找活四點座標
int fivePoints(int cells[11]) {
    int n = 0;
    for (int i = 0; i < 11; i++) {
        if (cells[i] != CELL_EMPTY) continue;
        cells[i] = CELL_SELF;
        if (makesFive(cells)) n++;
        cells[i] = CELL_EMPTY;
    }
    return n;
}

// 三：能再加一子成活四且不同時成五。回傳成活四的填法數，兩種以上即活三
static int threePoints(int cells[11]) {
    int n = 0;
    for (int i = 0; i < 11; i++) {
        if (cells[i] != CELL_EMPTY) continue;
        cells[i] = CELL_SELF;
        if (!makesFive(cells) && fivePoints(cells) >= 2) n++;
        cells[i] = CELL_EMPTY;
    }
    return n;
}

// 眠三/跳三專用：能再加一子成衝四（不同時成五、也不同時成活四）的格數
// 與 threePoints 互斥（同一格只會落在成五點=2 或=1 其中一類），量的是
// 「這個三連唯一能推進的方向只剩衝四」，即延伸方向已被鎖死的訊號
static int rushPoints(int cells[11]) {
    int n = 0;
    for (int i = 0; i < 11; i++) {
        if (cells[i] != CELL_EMPTY) continue;
        cells[i] = CELL_SELF;
        if (!makesFive(cells) && fivePoints(cells) == 1) n++;
        cells[i] = CELL_EMPTY;
    }
    return n;
}

// 二：RIF 未定義的殘留棋型，靠兩端是否被封區分活二與眠二
// 只認實心二連，且兩端外側不得再有隔空的己方子（那屬於更強的棋型，已被前面分支處理）
static int classifyMinor(int cells[11]) {
    if (solidRun(cells) != 2) return 0;

    int leftRun = 0;
    for (int j = 1; j < 6 && cells[5 - j] == CELL_SELF; j++) leftRun++;
    int left = 5 - leftRun - 1;              // 實連左端外一格
    int right = left + 3;                    // 實連右端外一格

    bool leftOpen = left >= 0 && cells[left] == CELL_EMPTY;
    bool rightOpen = right < 11 && cells[right] == CELL_EMPTY;

    // 端點外再一格若是己方子，掃描時算 gap，舊版不歸類為二
    if (leftOpen && left - 1 >= 0 && cells[left - 1] == CELL_SELF) return 0;
    if (rightOpen && right + 1 < 11 && cells[right + 1] == CELL_SELF) return 0;

    if (leftOpen && rightOpen) return 2;     // 活二
    if (leftOpen || rightOpen) return 6;     // 眠二
    return 0;
}

// [0:0, 1:0, 2:活二，3:活三，4:活四，5:五連，6:眠二，7:純衝四眠三，8:衝四，9:跳活三，10:跳活四，11:偏活跳三，12:跳四，13:偏活三，14:純衝四跳三，15:長連]
/* 回傳中心（cells[5] 為 SELF）在此 11 格窗口形成的最強棋型 index，無棋型回傳 0 */
int classifyWindow(int cells[11]) {
    if (cells[5] != CELL_SELF) return 0;   // 建表恆為 SELF，這道防護給外部直接呼叫用

    int run = solidRun(cells);
    if (run >= 6) return 15;               // 長連
    if (makesFive(cells)) return 5;        // 五連

    // 四級與三級依 RIF 定義推導，牆與敵子都不是 EMPTY，成五點自然數不到
    int fp = fivePoints(cells);
    if (fp > 0) {
        if (run == 4) return fp >= 2 ? 4 : 8;      // 活四、衝四
        return fp >= 2 ? 10 : 12;                  // 跳活四、跳四
    }

    // tp>=1 代表還有方向能成活四，緊急程度與活四同級，不受延伸方向鎖死與否影響
    int tp = threePoints(cells);
    if (tp > 0) {
        if (run == 3) return tp >= 2 ? 3 : 13;     // 活三、偏活三
        return tp >= 2 ? 9 : 11;                   // 跳活三、偏活跳三
    }

    // tp==0：不能成活四，但仍能成衝四代表延伸方向已被鎖死一端，
    // 只是個預先可防守的單點威脅
    if (rushPoints(cells) > 0) return run == 3 ? 7 : 14;   // 眠三、跳三

    return classifyMinor(cells);
}

// 全枚舉所有窗口編碼，逐一分類填進 patternTable
void initPatternTable() {
    for (int idx = 0; idx < PATTERN_TABLE_SIZE; idx++) {
        int cells[11];
        cells[5] = CELL_SELF;
        int rem = idx;
        // 解碼：off +5 是最低位，與 encodeWindow 反向
        for (int off = 5; off >= -5; off--) {
            if (off == 0) continue;
            cells[5 + off] = rem % 3;
            rem /= 3;
        }
        patternTable[idx] = (unsigned char)classifyWindow(cells);
    }
}

// 首次呼叫時建表：checkUnValid 這條路徑不經過 aiRound，不能靠它初始化
// 與 findBestMove 初始化置換表同一個模式；checkLine、winsAt 共用
void ensurePatternTable(void) {
    static bool patternTableReady = false;
    if (!patternTableReady) {
        initPatternTable();
        patternTableReady = true;
    }
}
