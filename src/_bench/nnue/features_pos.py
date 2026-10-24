"""位置感知棋型特徵抽取。

用法: python features_pos.py <dll> <games.txt> <out.npz> [--mode cell-dir-code|cell-code] [--sym]

特徵索引規則與 C 端 nnue.h 的 NNUE_FEAT 巨集必須一致。
棋型碼一律由 C 端 encodeWindow + patternTable 產生，不在 Python 重寫棋型分類，
否則抽出的特徵會與引擎實際用的不一致。

輸出是 ragged 格式（flat + offsets），不是定長 padding：每個局面的 active 特徵數
等於該色子數乘 4，局面之間差很多，padding 到最大值會多存好幾倍的空值。
"""
import argparse
import ctypes
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'texel'))
import engine  # noqa: E402
from features import parse  # noqa: E402

DX = (1, 1, 0, -1)
DY = (0, 1, 1, 1)
N_CODES = 15
PATTERN_TABLE_SIZE = 59049


def bind(lib):
    """綁定抽特徵需要的 export，回傳 patternTable 的 ctypes view。"""
    B = engine.selfplay.CBoard
    lib.ensurePatternTable.argtypes = []
    lib.ensurePatternTable.restype = None
    lib.encodeWindow.argtypes = [ctypes.POINTER(B)] + [ctypes.c_int] * 5
    lib.encodeWindow.restype = ctypes.c_int
    lib.ensurePatternTable()
    return (ctypes.c_ubyte * PATTERN_TABLE_SIZE).in_dll(lib, 'patternTable')


def feat_index(n, y, x, d, code, mode):
    if mode == 'cell-code':
        return (y * n + x) * N_CODES + code - 1
    return ((y * n + x) * 4 + d) * N_CODES + code - 1


def extract(lib, table, board, n, mode):
    """回傳 (黑的特徵 index list, 白的特徵 index list)。

    cell-code 模式下同一格的四個方向可能給出同一個 index，重複是對的：
    EmbeddingBag 的 sum 把重複累加成計數，語意與 checkNow 的計數一致。
    """
    cb = engine.to_cboard(board)
    out = ([], [])
    for y in range(n):
        for x in range(n):
            c = board[y][x]
            if not c:
                continue
            for d in range(4):
                code = table[lib.encodeWindow(cb, x, y, DX[d], DY[d], c)]
                if code:
                    out[c - 1].append(feat_index(n, y, x, d, code, mode))
    return out


def symmetries(board, n):
    """回傳 8 個對稱變換後的盤面（含原盤）。

    直接變換盤面再重抽特徵，不做 index 重映射（方向在旋轉下會互換）。
    """
    a = np.array(board, dtype=np.int8)
    out = []
    for k in range(4):
        r = np.rot90(a, k)
        out.append(r.tolist())
        out.append(np.fliplr(r).tolist())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dll')
    ap.add_argument('games')
    ap.add_argument('out')
    ap.add_argument('--mode', default='cell-dir-code', choices=['cell-dir-code', 'cell-code'])
    ap.add_argument('--sym', action='store_true', help='每個局面再產生 7 個對稱變換樣本')
    a = ap.parse_args()

    lib = engine.load(a.dll, 'featpos')
    table = bind(lib)
    n = engine.selfplay.BOARD_MAX
    bf, wf, boff, woff = [], [], [0], [0]
    gid, ply, res = [], [], []

    for g, (moves, nopen, result) in enumerate(parse(a.games)):
        board = [[0] * n for _ in range(n)]
        for i, (x, y, p) in enumerate(moves):
            # 只取黑方待下的局面：最終迭代深度下黑白兩方的葉節點都落在黑方待下，
            # evaluate 在實戰中幾乎只看到這種局面
            if i >= nopen and i % 2 == 0:
                for b in (symmetries(board, n) if a.sym else [board]):
                    fb, fw = extract(lib, table, b, n, a.mode)
                    bf.extend(fb)
                    boff.append(len(bf))
                    wf.extend(fw)
                    woff.append(len(wf))
                    gid.append(g)
                    ply.append(i)
                    res.append(result)
            board[y][x] = p

    n_feats = n * n * (1 if a.mode == 'cell-code' else 4) * N_CODES
    np.savez_compressed(
        a.out,
        bf=np.array(bf, dtype=np.int32), boff=np.array(boff, dtype=np.int64),
        wf=np.array(wf, dtype=np.int32), woff=np.array(woff, dtype=np.int64),
        gid=np.array(gid), ply=np.array(ply), result=np.array(res),
        mode=np.array(a.mode), n_feats=np.array(n_feats))
    print(f"{len(gid)} positions -> {a.out}  (mode={a.mode} sym={a.sym} n_feats={n_feats})")


if __name__ == '__main__':
    main()
