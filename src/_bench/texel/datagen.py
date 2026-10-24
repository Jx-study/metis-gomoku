"""平行自對弈產生訓練棋譜。

用法: python datagen.py <dll> <games> <out.txt> [--params p.json] [--extra 2-6] [--seed 1] [--jobs 14]

開局 = RIF 三手 + 隨機 extra 手（引擎確定性，不隨機就只有 104 盤不同的棋）。
輸出每行: 走法序列 x,y,p ... | nopen=N result=W

以下結尾不寫入，跟 dup 一樣只計入 reasons，最終行數可能略少於 games：

- illegal：引擎回傳越界或已有棋子的座標
- boardfull：棋盤下滿仍無人連五的和局，不是引擎異常，但這種僵局對訓練沒有價值
- foul：黑棋長連違規判負，勝負由規則裁定而非棋力
- nomove：引擎回報無合法走法的和局

斷點續跑：out 檔旁的 <out>.attempted 記錄已嘗試的 seed 數，續跑從該處接著跑到 games（task 的 seed 依全域 index 算，index 不重複用）。
中途中斷、games 沒跑滿，直接用原指令重跑即可接著跑，不必砍掉重來。

out 檔旁的 <out>.dllhash 記錄生成當下 ai.dll 的 sha256。
續跑時若目前傳入的 dll 雜湊對不上，代表 dll 已經換過版本（棋型分類/評分/搜索都可能不同），直接報錯要求手動處理，不會把新舊 dll 生成的棋局悄悄混進同一份檔案。
"""
import argparse
import hashlib
import json
import multiprocessing as mp
import os
import random
import sys
import time

import engine
from openings_rif import OPENINGS


def _dll_hash(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


_black = _white = None


def _init(dll, params):
    global _black, _white
    pid = os.getpid()
    _black = engine.load(dll, f"dg{pid}_b")
    _white = engine.load(dll, f"dg{pid}_w")
    if params:
        engine.set_params(_black, params)
        engine.set_params(_white, params)


def _task(args):
    seed, lo, hi = args
    rng = random.Random(seed)
    c = engine.selfplay.BOARD_MAX // 2
    base = [(c + dx, c + dy, p) for dx, dy, p in rng.choice(OPENINGS)]
    opening = engine.random_opening(rng, _black, base, rng.randint(lo, hi))
    w, moves, reason = engine.play(_black, _white, opening)
    return moves, len(opening), w, reason


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dll')
    ap.add_argument('games', type=int)
    ap.add_argument('out')
    ap.add_argument('--params')
    ap.add_argument('--extra', default='2-6')
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--jobs', type=int, default=14)
    a = ap.parse_args()
    lo, hi = map(int, a.extra.split('-'))
    params = json.load(open(a.params)) if a.params else None

    dll_hash = _dll_hash(a.dll)
    hash_path = a.out + '.dllhash'
    state_path = a.out + '.attempted'
    done = 0
    if os.path.exists(a.out):
        # 被過濾的局有 seed 卻沒有行，進度不能用行數代替
        if os.path.exists(state_path):
            done = int(open(state_path).read().strip() or 0)
        else:
            # 舊版檔案沒有 state，退回行數
            done = sum(1 for _ in open(a.out))
            print(f"{state_path} 不存在（舊版產生的檔案），暫以行數 {done} 當已嘗試數；"
                  "本次續跑可能重放部分已完成的局，之後就會準確")
        if os.path.exists(hash_path) and open(hash_path).read().strip() != dll_hash:
            sys.exit(f"{a.out} 是用別的 ai.dll 生成的（雜湊對不上 {hash_path}），先手動處理再重跑")
    if done >= a.games:
        print(f"{a.out} 已有 {done} 局 >= 目標 {a.games}，不需要再跑")
        return
    if done:
        print(f"{a.out} 已有 {done} 局，續跑剩下 {a.games - done} 局")
    with open(hash_path, 'w') as f:
        f.write(dll_hash + '\n')

    t0 = time.time()
    tasks = [(a.seed * 1_000_003 + i, lo, hi) for i in range(done, a.games)]
    res_count, reasons = {}, {}
    # 既有棋譜讀進 seen，讓 dedup 跨續跑有效
    seen = set()
    if os.path.exists(a.out):
        for line in open(a.out):
            seq = line.split('|')[0].split()
            seen.add(tuple(tuple(int(v) for v in t.split(',')) for t in seq))

    attempted = done
    with mp.Pool(a.jobs, _init, (os.path.abspath(a.dll), params)) as pool, open(a.out, 'a') as f:
        # 依序取結果，attempted 才等於已完成的 seed 前綴
        for moves, nopen, w, reason in pool.imap(_task, tasks, chunksize=4):
            reasons[reason] = reasons.get(reason, 0) + 1
            attempted += 1
            # 被過濾的局也算嘗試過，進度先落盤
            with open(state_path, 'w') as sf:
                sf.write(f"{attempted}\n")
            if reason in ('illegal', 'boardfull', 'foul', 'nomove'):
                continue
            key = tuple(moves)
            if key in seen:  # 重複的對局不寫，避免同一盤棋重複計權
                reasons['dup'] = reasons.get('dup', 0) + 1
                continue
            seen.add(key)
            res_count[w] = res_count.get(w, 0) + 1
            f.write(' '.join(f"{x},{y},{p}" for x, y, p in moves) + f" | nopen={nopen} result={w}\n")
            f.flush()  # 逐局落盤，斷點續跑靠這行才不會漏算已完成局數
    print(f"{a.games - done} games in {time.time() - t0:.0f}s  results={res_count}  endings={reasons}")


if __name__ == '__main__':
    main()
