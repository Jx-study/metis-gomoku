# gomoku_AI

## 專案結構

```
gomoku_AI/
├── src/                    # 主力開發目錄
│   ├── Gomoku.py          # 主程式（圖形界面人機對戰）
│   ├── ai.c               # 對外接口（aiRound、vcfProbe、getBoardMax、getBounds）
│   ├── ai.dll             # 編譯後產生的動態庫（需自行編譯）
│   ├── competition_chess.py  # 競賽格式入口（OpenCV + 檔案 IPC）
│   ├── utils/
│   │   └── build.py       # 跨平台編譯腳本（Windows: .dll，Linux: .so，macOS: .dylib）
│   └── lib/                # C 引擎模組
│       ├── types.h        # 共用型別與常數
│       ├── zobrist.c/.h   # Zobrist 雜湊與置換表
│       ├── pattern.c/.h   # 棋型查表（建表用的純函數）
│       ├── boardstate.c/.h # 增量盤面狀態與落子/撤銷入口
│       ├── lines.c/.h     # 棋型查表的消費端（判定、禁手）
│       ├── eval.c/.h      # 靜態評估
│       ├── movegen.c/.h   # 候選走法生成與排序
│       ├── vcf.c/.h       # 連續衝四算殺
│       ├── search.c/.h    # 迭代加深 alpha-beta 搜索
│       └── ai_unity.c     # unity build，僅供 _bench/ 插樁工具使用
├── project/                # 競賽版本歷史（v1–v3，已由 src/ 取代）
│   ├── readme.md          # 競賽版本演進說明
│   └── version 3/         # 競賽最終版（與 GUI 版邏輯不同，檔案 IPC）
└── Player_Vs_Ai/           # 人機對戰版本歷史（已由 src/ 取代）
    └── version_4/         # 最終打包版（含 Gomuko.exe，可直接執行）
```

## 快速開始

### 方式一：下載執行檔（推薦）
1. 到 [Releases](../../releases/latest) 下載 `Gomoku-windows.exe`
2. 雙擊執行，不需安裝 Python

首次執行可能被 Windows SmartScreen 攔下（未簽章執行檔），點「其他資訊」→「仍要執行」即可。

### 方式二：從源碼運行
```bash
cd src/

# 編譯 C 語言 AI 引擎（跨平台，Windows 產生 ai.dll，Linux/macOS 產生 ai.so/.dylib）
python utils/build.py

# 運行遊戲
python Gomoku.py
```

也可以手動指定編譯指令（不要用 `*.c` 展開，`lib/ai_unity.c` 會造成重複定義）：
```bash
cd src/
gcc -I lib -shared -o ai.dll -fPIC lib/zobrist.c lib/pattern.c lib/boardstate.c lib/lines.c lib/eval.c lib/movegen.c lib/vcf.c lib/search.c ai.c
```

### 打包成可執行檔
```bash
cd src/
pyinstaller Gomoku.spec   # 資源檔、字型、排除模組都設定在 spec 裡
```

## 專案介紹

### 人機對戰版本 (`src/`)
- 圖形化遊戲界面（使用 pygame-ce）
- 滑鼠點擊落子、悔棋、重新開始、查看規則
- 落子預覽、黑棋禁手點預先標記、雙方計時與 AI 思考時間
- AI 在背景執行緒搜索，思考時畫面不凍結
- C 語言 AI 引擎（ctypes 呼叫）、Zobrist 哈希 + 置換表優化

### 競賽版本 (`project/version 3/`)
- **目標**：國立臺北科技大學·計算機程式設計（二）·五子棋專題競賽
- 使用檔案 IPC（a.txt / b.txt）在兩個 process 間傳遞棋步
- 符合 RIF 五子棋禁手規則（黑方三三、四四、長連禁手）

## 版本演進歷史

| 版本 | 時間 | 主要更新 |
|------|------|----------|
| **v1.0** | 2024/06 | 基礎評分法 + 禁手規則 |
| **v2.0** | 2024/06 | 新增防守/進攻策略 |
| **v3.0** | 2024/06 | MiniMax + Alpha-Beta 剪枝 |
| **v4.0** | 2025/01 | 圖形界面 + Zobrist 哈希優化 + 打包執行檔 |

## 五子棋規則

### 基本規則
- 21×21 棋盤
- 黑棋先手，雙方輪流落子
- 橫、豎、斜任意方向連成五子獲勝
- 超過五子不算贏

### 開局規則
1. 黑方必須在棋盤中心落第 1 手
2. 白方在中心 3×3 範圍內落第 2 手
3. 黑方在中心 5×5 範圍內落第 3 手

### 禁手規則（僅限黑方）
- 禁止：雙活三
- 禁止：雙活四（包含四三三、三三四等）
- 禁止：長連（超過五子）
- 特例：五連與禁手同時形成，黑方獲勝

詳細規則：https://587.renju.org.tw/teach/teach018.htm

## AI 技術細節

- **搜索策略**：MiniMax 演算法 + Alpha-Beta 剪枝（迭代加深，最大深度 7）
- **狀態快取**：Zobrist 哈希 + 置換表（2^20 桶，always-replace）
- **算殺**：`vcfFindWin()` 連續衝四搜索，找到強制勝就跳過主搜索
- **移動排序**：`sortMoves()` + `quickEvaluate()` 提升剪枝效率
- **模式識別**：`classifyWindow()` 預先建 3^10 棋型查表，`checkLine()` 查表分類
- **增量索引**：`windowIdx`、`stoneList`、`neighborCount` 三張表隨落子/撤銷增量維護
- **禁手檢測**：`checkUnValid()` 偵測黑方雙三/雙四/長連
