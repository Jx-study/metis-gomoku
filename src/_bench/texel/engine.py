"""Texel 調參共用：載入 dll、設定評估參數、對局（含隨機開局）。

每個 process 各自複製 dll 成獨立檔名再載入：同一 process 內黑白兩方必須是不同模組，
否則共用同一張置換表（TT 分數以 ai 視角存，黑白混用會互相污染）。
"""
import ctypes
import os
import random
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'lib'))
import selfplay  # noqa: E402

N_PARAMS = 74  # 2 色 × 37


def load(path, tag):
    """把 path 複製成 <tag>.dll 後載入，回傳 lib。"""
    tmp = os.path.join(HERE, '_tmp')
    os.makedirs(tmp, exist_ok=True)
    dst = os.path.join(tmp, f"{tag}.dll")
    shutil.copyfile(path, dst)
    lib = selfplay.load(dst)
    B = selfplay.CBoard
    lib.setEvalParams.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int]
    lib.setEvalParams.restype = ctypes.c_int
    lib.getEvalParams.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int]
    lib.getEvalParams.restype = ctypes.c_int
    lib.checkNow.argtypes = [ctypes.POINTER(B)] + [ctypes.c_int] * 5 + [ctypes.POINTER(ctypes.c_int)]
    lib.checkNow.restype = None
    lib.evaluate.argtypes = [ctypes.POINTER(B)] + [ctypes.c_int] * 5
    lib.evaluate.restype = ctypes.c_int
    lib.getBounds.argtypes = [ctypes.POINTER(B)] + [ctypes.POINTER(ctypes.c_int)] * 4
    lib.checkUnValid.argtypes = [ctypes.POINTER(B), ctypes.c_int, ctypes.c_int, ctypes.c_int]
    lib.checkUnValid.restype = ctypes.c_int
    return lib


def get_params(lib):
    arr = (ctypes.c_int * N_PARAMS)()
    ok = lib.getEvalParams(arr, N_PARAMS)
    assert ok, "getEvalParams: 長度與 DLL 內部參數陣列不符"
    return list(arr)


def set_params(lib, params):
    assert len(params) == N_PARAMS
    ok = lib.setEvalParams((ctypes.c_int * N_PARAMS)(*[int(v) for v in params]), N_PARAMS)
    assert ok, "setEvalParams: 長度與 DLL 內部參數陣列不符"


def to_cboard(board):
    cb = selfplay.CBoard()
    n = selfplay.BOARD_MAX
    for i in range(n):
        for j in range(n):
            cb[i][j] = board[i][j]
    return cb


def random_opening(rng, lib, base, extra):
    """RIF 三手開局 base 之後再隨機加 extra 手。

    隨機手取距現有棋子 Chebyshev 距離 1 的空點；黑棋避開禁手、雙方避開直接成五。
    """
    n = selfplay.BOARD_MAX
    board = [[0] * n for _ in range(n)]
    moves = list(base)
    for x, y, p in moves:
        board[y][x] = p
    for _ in range(extra):
        p = 1 if len(moves) % 2 == 0 else 2
        cands = []
        for y in range(n):
            for x in range(n):
                if board[y][x]:
                    continue
                if not any(0 <= x + dx < n and 0 <= y + dy < n and board[y + dy][x + dx]
                           for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
                    continue
                cands.append((x, y))
        rng.shuffle(cands)
        placed = False
        for x, y in cands:
            if p == 1 and lib.checkUnValid(to_cboard(board), x, y, 1) != 1:
                continue
            board[y][x] = p
            if selfplay.judge(board, x, y, p) is not None:
                board[y][x] = 0
                continue
            moves.append((x, y, p))
            placed = True
            break
        if not placed:
            break
    return moves


def play(black, white, opening):
    """回傳 (winner, moves, reason)，沿用 selfplay 的裁判。"""
    return selfplay.play_game(black, white, opening, verbose=False)
