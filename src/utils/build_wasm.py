"""把 lib/ 下的 C 模組與 ai.c 以 Emscripten 編成 WebAssembly，給網頁版的 Worker 載入。

輸出 engine.mjs（ES module 載入器）、engine.wasm 與型別宣告 engine.d.mts 到 web/src/wasm/，由 Vite 打包。
emcc 從 PATH 找，使用前先載入 emsdk_env。

用法（任意目錄皆可）：
    python src/utils/build_wasm.py
"""
import shutil
import subprocess
import sys
from pathlib import Path

from build import MODULES

EXPORTED_FUNCTIONS = [
    "_getBoardMax", "_initZobristTable", "_initTranspositionTable",
    "_aiRound", "_checkWin", "_checkUnValid", "_malloc", "_free",
]

FLAGS = [
    "-O2",
    "-sMODULARIZE=1", "-sEXPORT_ES6=1", "-sENVIRONMENT=web,worker,node",
    "-sEXPORTED_FUNCTIONS=" + ",".join(EXPORTED_FUNCTIONS),
    "-sEXPORTED_RUNTIME_METHODS=HEAP32",
    "-sINITIAL_MEMORY=64MB", "-sALLOW_MEMORY_GROWTH=1",
    # 預設堆疊遠小於原生，miniMax 遞迴會溢位
    "-sSTACK_SIZE=8MB",
]

# 指標與 int 在 wasm32 都是 number；盤面為 BOARD_MAX x BOARD_MAX 個 int32，board[y][x]
TYPE_DECLARATION = """export interface EngineModule {
  HEAP32: Int32Array;
  _getBoardMax(): number;
  _initZobristTable(): void;
  _initTranspositionTable(): void;
  _aiRound(board: number, ai: number, roundCounter: number, bestx: number, besty: number): void;
  _checkWin(board: number, minX: number, maxX: number, minY: number, maxY: number, player: number): number;
  _checkUnValid(board: number, x: number, y: number, player: number): number;
  _malloc(size: number): number;
  _free(ptr: number): void;
}

export interface EngineModuleOptions {
  locateFile?(path: string, prefix: string): string;
}

export default function createEngine(options?: EngineModuleOptions): Promise<EngineModule>;
"""


def main():
    emcc = shutil.which("emcc")
    if emcc is None:
        sys.exit("build_wasm: PATH 上找不到 emcc，先載入 emsdk_env")

    src_dir = Path(__file__).resolve().parent.parent
    lib_dir = src_dir / "lib"
    out_dir = src_dir.parent / "web" / "src" / "wasm"
    out_dir.mkdir(parents=True, exist_ok=True)

    output = out_dir / "engine.mjs"
    sources = [str(lib_dir / m) for m in MODULES] + [str(src_dir / "ai.c")]
    cmd = [emcc, "-I", str(lib_dir), *FLAGS, *sources, "-o", str(output)]

    print(" ".join(cmd))
    subprocess.run(cmd, check=True)
    (out_dir / "engine.d.mts").write_text(TYPE_DECLARATION, encoding="utf-8")
    print(f"build_wasm: -> {out_dir}（engine.mjs、engine.wasm、engine.d.mts）")


if __name__ == "__main__":
    main()
