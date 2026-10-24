<div align="center">

<img src="src/200w.gif" alt="Gomoku AI" width="120">

# Gomoku AI

連珠規則五子棋對弈程式：Python 圖形介面搭配 C 語言搜索引擎

[![CI](https://github.com/Jx-study/metis-gomoku/actions/workflows/ci.yml/badge.svg)](https://github.com/Jx-study/metis-gomoku/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/Jx-study/metis-gomoku)](https://github.com/Jx-study/metis-gomoku/releases/latest)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

**繁體中文** · [English](README.en.md)

[下載](#下載執行檔) · [從原始碼執行](#從原始碼執行) · [遊戲規則](#遊戲規則) · [AI 引擎](#ai-引擎) · [開發](#開發)

</div>

## 特色

- **完整連珠規則**：開局限制區域、黑方三三／四四／長連禁手，黑棋回合以灰色 × 預先標出禁手點
- **C 語言搜索引擎**：迭代加深 Alpha-Beta、VCF 算殺、Zobrist 置換表，透過 ctypes 由 Python 呼叫
- **流暢的對弈介面**：pygame-ce 繪製，落子預覽、雙方計時、AI 思考時間顯示
- **背景搜索**：AI 在獨立執行緒思考，畫面不凍結
- **跨平台發行**：Windows、macOS、Linux 單一執行檔，免安裝 Python

## 下載執行檔

到 [Releases](https://github.com/Jx-study/metis-gomoku/releases/latest) 下載對應平台的檔案，下載後直接執行。

| 平台 | 檔案 | 首次執行 |
|---|---|---|
| Windows | `Gomoku-windows.exe` | SmartScreen 攔下時點「其他資訊」→「仍要執行」 |
| macOS | `Gomoku-macos` | `xattr -cr Gomoku-macos && chmod +x Gomoku-macos` |
| Linux | `Gomoku-linux` | `chmod +x Gomoku-linux` |

執行檔未簽章。macOS 與 Linux 版本未經實機測試。

## 從原始碼執行

需要 Python 3.11 與 GCC（Windows 可用 MinGW-w64）。

```bash
pip install -r requirements.txt
cd src/
python utils/build.py   # 編譯 C 引擎：Windows 產生 ai.dll，Linux 為 ai.so，macOS 為 ai.dylib
python Gomoku.py
```

<details>
<summary>手動編譯指令</summary>

```bash
cd src/
gcc -O2 -I lib -shared -fPIC -o ai.dll lib/zobrist.c lib/pattern.c lib/boardstate.c lib/lines.c lib/eval.c lib/movegen.c lib/vcf.c lib/search.c ai.c
```

不要用 `lib/*.c` 展開，`lib/ai_unity.c` 會造成重複定義。

</details>

### 操作方式

- 開局選擇執黑（先手）或執白（後手）
- 滑鼠左鍵點擊交叉點落子
- 棋盤下方按鈕：**重玩**、**悔棋**、**規則**
- AI 思考中停用重玩與悔棋

## 遊戲規則

### 基本規則

- 15×15 棋盤，黑棋先手，雙方輪流落子
- 橫、豎、斜任一方向連成五子獲勝

### 開局規則

1. 黑方第 1 手落在棋盤中心
2. 白方第 2 手落在中心 3×3 範圍內
3. 黑方第 3 手落在中心 5×5 範圍內

### 禁手規則（僅限黑方）

| 禁手 | 說明 |
|---|---|
| 三三 | 一子同時形成兩個活三 |
| 四四 | 一子同時形成兩個四（含四三三、三三四） |
| 長連 | 連成六子以上 |

- 黑方下出禁手即判負
- 五連與禁手同時形成時不算禁手，黑方獲勝
- 其中一個三無法成為活四時，該禁手不成立（以禁解禁）
- 白方沒有禁手，長連也算獲勝

詳細規則見 [台灣連珠協會說明](https://587.renju.org.tw/teach/teach018.htm)。

## AI 引擎

### 搜索流程

```
sortMoves() + quickEvaluate()   產生並排序候選走法
        │
        ▼
vcfFindWin()                    連續衝四算殺，找到強制勝直接回傳
        │
        ▼
miniMax()                       迭代加深 Alpha-Beta
        │
        ▼
evaluate()                      靜態評估，結果存入 Zobrist 置換表
```

### 技術要點

| 項目 | 實作 |
|---|---|
| 搜索 | MiniMax + Alpha-Beta 剪枝，迭代加深；白棋深度 9、黑棋 10，開局前八手各減 2 |
| 算殺 | `vcfFindWin()` 連續衝四搜索 |
| 置換表 | Zobrist 雜湊，2^20 個 entry，always-replace |
| 走法排序 | `sortMoves()` + `quickEvaluate()` 啟發式評分 |
| 棋型識別 | 預建 3^10 棋型查表，`checkLine()` 查表分類成 14 種棋型 |
| 增量狀態 | `windowIdx`、`stoneList`、`neighborCount` 隨落子與撤銷增量維護 |
| 評估權重 | Texel 自我對弈調校 |
| 禁手判定 | `checkUnValid()` 偵測三三、四四、長連 |

## 開發

### 專案結構

```
metis-gomoku/
├── src/                       現行程式碼
│   ├── Gomoku.py              遊戲協調者：載入引擎、遊戲流程控制
│   ├── gomoku_ui.py           pygame-ce 渲染與事件迴圈
│   ├── game_state.py          盤面、輪次、開局規則、悔棋
│   ├── theme.py               色票與字級
│   ├── competition_chess.py   競賽格式入口（OpenCV + 檔案 IPC）
│   ├── ai.c                   C 引擎對外接口
│   ├── lib/                   C 引擎模組
│   │   ├── types.h            共用型別與常數
│   │   ├── zobrist.c/.h       Zobrist 雜湊與置換表
│   │   ├── pattern.c/.h       棋型查表建表
│   │   ├── boardstate.c/.h    增量盤面狀態、落子與撤銷
│   │   ├── lines.c/.h         棋型判定、禁手
│   │   ├── eval.c/.h          靜態評估
│   │   ├── movegen.c/.h       候選走法生成與排序
│   │   ├── vcf.c/.h           連續衝四算殺
│   │   └── search.c/.h        迭代加深 Alpha-Beta 搜索
│   ├── tests/                 pytest 測試
│   ├── _bench/                引擎效能與棋力驗證工具
│   ├── utils/                 編譯、打包驗證、字型裁切腳本
│   └── Gomoku.spec            PyInstaller 打包設定
├── project/                   競賽版本歷史（v1–v3）
└── Player_Vs_Ai/              人機對戰版本歷史
```

### 測試

```bash
pytest   # 從 repo 根目錄執行
```

- 需要 C 引擎的測試在找不到共享庫時整個模組 skip
- GUI 測試使用 SDL dummy driver，不需要實體視窗

### 效能與棋力驗證

C 引擎的效能與棋力改動用 [`src/_bench/`](src/_bench/README.md) 比對兩個版本的引擎，用法與判讀標準見該目錄的 README。

### 打包

```bash
cd src/
pyinstaller Gomoku.spec                           # 資源檔、字型、排除模組都設定在 spec
python utils/verify_bundle.py dist/Gomoku-*.exe   # 確認執行檔帶齊共享庫與資源
```

### 發版

版號由 [release-please](https://github.com/googleapis/release-please) 依 [Conventional Commits](https://www.conventionalcommits.org/) 前綴決定。
合併進 `main` 後自動開 Release PR，合併該 PR 才打 tag 並觸發三平台打包。
各版變更見 [Releases](https://github.com/Jx-study/metis-gomoku/releases)。

## 版本沿革

| 版本 | 時間 | 主要更新 |
|---|---|---|
| v1.0 | 2024/06 | 基礎評分法、禁手規則 |
| v2.0 | 2024/06 | 防守與進攻策略 |
| v3.0 | 2024/06 | MiniMax + Alpha-Beta 剪枝 |
| v4.0 | 2025/01 | 圖形介面、Zobrist 雜湊、打包執行檔 |
| 1.x | 2026 | C 引擎模組化、VCF 算殺、Texel 調參、pygame-ce 介面、三平台自動發行 |

v1.0–v3.0 為國立臺北科技大學「計算機程式設計（二）」五子棋專題競賽版本，保存在 [`project/`](project/readme.md)。
