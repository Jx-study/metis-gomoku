<div align="center">

<img src="src/200w.gif" alt="Gomoku AI" width="120">

# Gomoku AI

A Renju-rules Gomoku game with a Python GUI and a C search engine

[![CI](https://github.com/Jx-study/metis-gomoku/actions/workflows/ci.yml/badge.svg)](https://github.com/Jx-study/metis-gomoku/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/Jx-study/metis-gomoku)](https://github.com/Jx-study/metis-gomoku/releases/latest)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

[繁體中文](README.md) · **English**

[Download](#download) · [Run from source](#run-from-source) · [Rules](#rules) · [AI engine](#ai-engine) · [Development](#development)

</div>

## Features

- **Full Renju rules**: restricted opening zones and Black's double-three, double-four and overline fouls; forbidden points are marked with a grey × on Black's turn
- **C search engine**: iterative-deepening Alpha-Beta, VCF threat search and a Zobrist transposition table, called from Python via ctypes
- **Smooth game UI**: drawn with pygame-ce, with move preview, per-player clocks and AI thinking time
- **Background search**: the AI thinks on a separate thread so the window never freezes
- **Cross-platform builds**: single-file executables for Windows, macOS and Linux, no Python required

## Download

Get the file for your platform from [Releases](https://github.com/Jx-study/metis-gomoku/releases/latest) and run it directly.

| Platform | File | First launch |
|---|---|---|
| Windows | `Gomoku-windows.exe` | If SmartScreen blocks it, click "More info" → "Run anyway" |
| macOS | `Gomoku-macos` | `xattr -cr Gomoku-macos && chmod +x Gomoku-macos` |
| Linux | `Gomoku-linux` | `chmod +x Gomoku-linux` |

The executables are unsigned. The macOS and Linux builds have not been tested on real hardware.

## Run from source

Requires Python 3.11 and GCC (MinGW-w64 on Windows).

```bash
pip install -r requirements.txt
cd src/
python utils/build.py   # builds the C engine: ai.dll on Windows, ai.so on Linux, ai.dylib on macOS
python Gomoku.py
```

<details>
<summary>Manual build command</summary>

```bash
cd src/
gcc -O2 -I lib -shared -fPIC -o ai.dll lib/zobrist.c lib/pattern.c lib/boardstate.c lib/lines.c lib/eval.c lib/movegen.c lib/vcf.c lib/search.c ai.c
```

Do not use a `lib/*.c` glob: `lib/ai_unity.c` would cause duplicate definitions.

</details>

### Controls

- Choose Black (first move) or White (second move) at the start
- Left-click an intersection to place a stone
- Buttons below the board: **Restart**, **Undo**, **Rules**
- Restart and Undo are disabled while the AI is thinking

The in-game UI is in Traditional Chinese.

## Rules

### Basics

- 15×15 board, Black moves first, players alternate
- Five in a row horizontally, vertically or diagonally wins

### Opening

1. Black's 1st move goes on the center point
2. White's 2nd move goes within the central 3×3 area
3. Black's 3rd move goes within the central 5×5 area

### Fouls (Black only)

| Foul | Description |
|---|---|
| Double-three | One move creates two open threes |
| Double-four | One move creates two fours (including 4-3-3 and 3-3-4) |
| Overline | Six or more in a row |

- Black loses immediately on a foul
- If a move makes five and a foul at the same time, it is not a foul and Black wins
- A three that cannot become an open four does not count toward a double-three
- White has no fouls, and an overline also wins for White

See the [Taiwan Renju Association guide](https://587.renju.org.tw/teach/teach018.htm) (Chinese) for details.

## AI engine

### Search pipeline

```
sortMoves() + quickEvaluate()   generate and order candidate moves
        │
        ▼
vcfFindWin()                    VCF threat search, return a forced win immediately
        │
        ▼
miniMax()                       iterative-deepening Alpha-Beta
        │
        ▼
evaluate()                      static evaluation, cached in the Zobrist table
```

### Techniques

| Area | Implementation |
|---|---|
| Search | MiniMax + Alpha-Beta pruning with iterative deepening; depth 9 for White, 10 for Black, minus 2 during the first eight moves |
| Threat search | `vcfFindWin()` continuous-four (VCF) search |
| Transposition table | Zobrist hashing, 2^20 entries, always-replace |
| Move ordering | `sortMoves()` + `quickEvaluate()` heuristic scoring |
| Pattern recognition | Precomputed 3^10 pattern table; `checkLine()` classifies 14 pattern types by lookup |
| Incremental state | `windowIdx`, `stoneList` and `neighborCount` updated on every place and undo |
| Evaluation weights | Tuned with Texel self-play |
| Foul detection | `checkUnValid()` detects double-three, double-four and overline |

## Development

### Project layout

```
metis-gomoku/
├── src/                       current code
│   ├── Gomoku.py              game coordinator: engine loading, game flow
│   ├── gomoku_ui.py           pygame-ce rendering and event loop
│   ├── game_state.py          board, turns, opening rules, undo
│   ├── theme.py               colors and font sizes
│   ├── competition_chess.py   competition entry point (OpenCV + file IPC)
│   ├── ai.c                   C engine public API
│   ├── lib/                   C engine modules
│   │   ├── types.h            shared types and constants
│   │   ├── zobrist.c/.h       Zobrist hashing and transposition table
│   │   ├── pattern.c/.h       pattern table construction
│   │   ├── boardstate.c/.h    incremental board state, place and undo
│   │   ├── lines.c/.h         pattern classification, fouls
│   │   ├── eval.c/.h          static evaluation
│   │   ├── movegen.c/.h       candidate generation and ordering
│   │   ├── vcf.c/.h           VCF threat search
│   │   └── search.c/.h        iterative-deepening Alpha-Beta search
│   ├── tests/                 pytest suite
│   ├── _bench/                engine performance and strength tools
│   ├── utils/                 build, bundle verification, font subsetting scripts
│   └── Gomoku.spec            PyInstaller config
├── project/                   competition version history (v1–v3)
└── Player_Vs_Ai/              player-vs-AI version history
```

### Tests

```bash
pytest   # run from the repo root
```

- Tests that need the C engine skip the whole module when the shared library is missing
- GUI tests use the SDL dummy driver and need no real window

### Performance and strength

Changes to the C engine's speed or playing strength are measured with [`src/_bench/`](src/_bench/README.md), which compares two engine builds. See its README (Chinese) for usage.

### Packaging

```bash
cd src/
pyinstaller Gomoku.spec                           # assets, fonts and excludes are all set in the spec
python utils/verify_bundle.py dist/Gomoku-*.exe   # check the executable bundles the library and assets
```

### Releases

Versions are set by [release-please](https://github.com/googleapis/release-please) from [Conventional Commits](https://www.conventionalcommits.org/) prefixes.
Merging into `main` opens a Release PR; merging that PR creates the tag and triggers the three-platform build.
See [Releases](https://github.com/Jx-study/metis-gomoku/releases) for per-version changes.

## History

| Version | Date | Highlights |
|---|---|---|
| v1.0 | 2024/06 | Basic scoring, foul rules |
| v2.0 | 2024/06 | Attack and defense strategies |
| v3.0 | 2024/06 | MiniMax + Alpha-Beta pruning |
| v4.0 | 2025/01 | GUI, Zobrist hashing, packaged executable |
| 1.x | 2026 | Modular C engine, VCF search, Texel tuning, pygame-ce UI, automated three-platform releases |

v1.0–v3.0 were built for the Gomoku project competition in Computer Programming (II) at National Taipei University of Technology and are kept in [`project/`](project/readme.md).
