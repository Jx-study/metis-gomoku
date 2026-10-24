"""Texel tuning 原型。

用法: python texel.py <train.npz> [--mode untied|tied] [--out tuned.json] [--dll ../../ai.dll]

1. 用快取的棋型計數在 numpy 重算 evaluate，先與 C 端分數逐筆對拍（必須全等才繼續）
2. 每個視角 p 各擬合 P(p 勝) = sigmoid((score - b) / K)，K、b 是擾動參數（搜索只看分數的序，
   正仿射變換不改變著法）
3. 座標下降調整權重，步長遞減；每輪掃完重擬 K、b
4. 以對局為單位切 80/20，報告訓練與保留集的 MSE，並與常數預測、自由線性模型比較
"""
import argparse
import json

import numpy as np
from scipy.optimize import minimize

import engine

L = np.array([1, 1, 2, 3, 4, 5, 2, 3, 4, 3, 4, 3, 4, 3, 3, 1])
KS = list(range(2, 15))                 # evaluate 用到的棋型 index（含 5，但非終局恆為 0）
TUNE_K = [2, 3, 4, 6, 7, 8, 9, 10, 11, 12, 13, 14]
PER = 37
W_ATK, W_DEF, BONUS, DEF_NUM, EXTRA_NUM = 0, 15, 30, 35, 36
NAMES = {2: '活二', 3: '活三', 4: '活四', 6: '眠二', 7: '純衝四眠三', 8: '衝四', 9: '跳活三',
         10: '跳活四', 11: '偏活跳三', 12: '跳四', 13: '偏活三', 14: '純衝四跳三'}


def load_default(dll):
    """向 DLL 查詢當前的 evalParams 預設值。

    不寫死常數：eval.c 的預設值會隨每輪調參更新，寫死的副本漂移後
    下面的對拍會拿舊值比對新 DLL，那道「必須全等才繼續」的保護就形同虛設。
    """
    return engine.get_params(engine.load(dll, 'texel_default'))


class View:
    """一個視角（ai = p）的預先計算特徵。"""

    def __init__(self, my, op, y):
        self.Fm = my[:, KS] // L[KS]
        self.Fo = op[:, KS] // L[KS]
        m, o = my, op
        c1 = (o[:, 4] > 0) & (m[:, 4] == 0) & (m[:, 8] == 0)
        c2 = ~c1 & (o[:, 8] > 0) & (m[:, 4] == 0) & (m[:, 8] == 0)
        c3 = (~c1 & ~c2
              & ((o[:, 3] > 0) | (o[:, 9] > 0) | (o[:, 13] > 0) | (o[:, 11] > 0))
              & (m[:, 3] == 0) & (m[:, 9] == 0) & (m[:, 13] == 0) & (m[:, 11] == 0))
        c4 = (~c1 & ~c2 & ~c3
              & ((o[:, 7] > 0) | (o[:, 14] > 0))
              & (m[:, 7] == 0) & (m[:, 14] == 0)
              & (m[:, 3] == 0) & (m[:, 9] == 0) & (m[:, 13] == 0) & (m[:, 11] == 0))
        no5 = m[:, 5] == 0
        no48 = (m[:, 4] == 0) & (m[:, 8] == 0)
        dbl_three = (o[:, 3] > 0) | (o[:, 9] > 0) | (o[:, 13] > 0) | (o[:, 11] > 0)
        dbl_four = (o[:, 4] > 0) | (o[:, 8] > 0) | (o[:, 10] > 0)
        self.B = np.stack([c1 & no5, c2 & no5, c3 & no48 & no5, c4 & no48 & no5,
                           dbl_three & dbl_four], axis=1).astype(np.int64)
        self.y = y

    def subset(self, idx):
        v = View.__new__(View)
        v.Fm, v.Fo, v.B, v.y = self.Fm[idx], self.Fo[idx], self.B[idx], self.y[idx]
        return v

    def score(self, ep):
        ep = np.asarray(ep, dtype=np.int64)
        att = self.Fm @ ep[W_ATK + 2:W_ATK + 15]
        dfn = self.Fo @ ep[W_DEF + 2:W_DEF + 15] + self.B @ ep[BONUS:BONUS + 5]
        s = 12000 + att - dfn * ep[DEF_NUM] // 100
        return s - np.where(dfn > att, dfn * ep[EXTRA_NUM] // 100, 0)


def sig(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -60, 60)))


def mse(s, y, kb):
    return float(np.mean((sig((s - kb[1]) / np.exp(kb[0])) - y) ** 2))


def fit_kb(s, y, kb0=None):
    kb0 = np.array([np.log(max(np.std(s), 1.0)), np.median(s)]) if kb0 is None else kb0
    r = minimize(lambda kb: mse(s, y, kb), kb0, method='Nelder-Mead',
                 options={'xatol': 1e-4, 'fatol': 1e-9, 'maxiter': 2000})
    return r.x, r.fun


def load_views(path):
    d = np.load(path)
    res = d['result']
    y1 = np.where(res == 1, 1.0, np.where(res == 0, 0.5, 0.0))
    v1 = View(d['c1'], d['c2'], y1)            # 黑 ai 視角
    v2 = View(d['c2'], d['c1'], 1.0 - y1)      # 白 ai 視角
    return d, v1, v2


def split(gid, seed=0):
    rng = np.random.default_rng(seed)
    games = np.unique(gid)
    test_games = set(rng.choice(games, size=len(games) // 5, replace=False).tolist())
    te = np.array([g in test_games for g in gid])
    return ~te, te


# 參數化：mode 決定哪些 C 參數綁在一起，回傳 (初值向量, 展開成 74 個 int 的函式)
def make_param_map(mode, init):
    if mode == 'untied':
        slots = []   # 每個 slot = 共用同一個值的 C 參數位置清單
        for c in range(2):
            base = c * PER
            slots += [[base + W_ATK + k] for k in TUNE_K]
            slots += [[base + W_DEF + k] for k in TUNE_K]
            slots += [[base + BONUS + i] for i in range(5)]
            slots += [[base + DEF_NUM], [base + EXTRA_NUM]]
    else:  # tied：原始結構，攻防共用、黑白共用，只有防守係數分色
        slots = [[c * PER + W_ATK + k for c in range(2)] + [c * PER + W_DEF + k for c in range(2)]
                 for k in TUNE_K]
        slots += [[c * PER + BONUS + i for c in range(2)] for i in range(5)]
        slots += [[DEF_NUM], [PER + DEF_NUM], [EXTRA_NUM, PER + EXTRA_NUM]]
    x0 = np.array([init[s[0]] for s in slots], dtype=np.int64)

    def expand(x):
        p = list(init)
        for s, v in zip(slots, x):
            for i in s:
                p[i] = int(v)
        return p
    return slots, x0, expand


def total_loss(views, p, kbs):
    return sum(mse(v.score(p[c * PER:(c + 1) * PER]), v.y, kbs[c]) for c, v in enumerate(views))


def refit(views, p, kbs):
    out = []
    for c, v in enumerate(views):
        kb, _ = fit_kb(v.score(p[c * PER:(c + 1) * PER]), v.y, kbs[c] if kbs else None)
        out.append(kb)
    return out


def tune(views, mode, init, max_sweeps=60, log=print):
    slots, x, expand = make_param_map(mode, init)
    scale = np.maximum(np.abs(x), 10)
    kbs = refit(views, expand(x), None)
    best = total_loss(views, expand(x), kbs)
    step = 0.5
    sweep = 0
    while step >= 0.01 and sweep < max_sweeps:
        sweep += 1
        improved = False
        for i in range(len(x)):
            for sgn in (1, -1):
                cand = x.copy()
                cand[i] = max(0, x[i] + sgn * max(1, int(round(step * max(abs(x[i]), scale[i] * 0.05)))))
                if cand[i] == x[i]:
                    continue
                l = total_loss(views, expand(cand), kbs)
                if l < best - 1e-12:
                    best, x, improved = l, cand, True
                    break
        kbs = refit(views, expand(x), kbs)
        best = total_loss(views, expand(x), kbs)
        log(f"  sweep {sweep:2d} step {step:.3f} loss {best:.6f}")
        if not improved:
            step /= 2
    return expand(x), kbs


def linear_upper_bound(v_tr, v_te):
    """自由線性 logistic 模型（同一組特徵，權重不受結構限制）的保留集 MSE。"""
    from sklearn.linear_model import LogisticRegression
    X = lambda v: np.hstack([v.Fm, v.Fo, v.B])
    ytr = (v_tr.y > 0.5).astype(int)
    m = LogisticRegression(C=1.0, max_iter=5000).fit(X(v_tr), ytr)
    return float(np.mean((m.predict_proba(X(v_te))[:, 1] - v_te.y) ** 2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('npz')
    # 正式方案只認 tied，untied 留給研究用手動指定
    ap.add_argument('--mode', default='tied', choices=['untied', 'tied'])
    ap.add_argument('--out', default='tuned.json')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--init', help='從既有參數檔起爬（迭代輪次用）')
    ap.add_argument('--dll', default='../../ai.dll', help='對拍與預設參數的來源')
    a = ap.parse_args()
    default = load_default(a.dll)
    init = json.load(open(a.init)) if a.init else default

    d, v1, v2 = load_views(a.npz)
    # 對拍：numpy 聚合分必須與 C 端 evaluate 逐筆相同
    for c, (v, ev) in enumerate(((v1, d['ev1']), (v2, d['ev2']))):
        diff = np.count_nonzero(v.score(default[c * PER:(c + 1) * PER]) != ev)
        assert diff == 0, f"aggregator mismatch on color {c + 1}: {diff} positions"
    print(f"aggregator == C evaluate on all {len(d['gid'])} positions x 2 views")

    tr, te = split(d['gid'], a.seed)
    views_tr = [v1.subset(tr), v2.subset(tr)]
    views_te = [v1.subset(te), v2.subset(te)]
    print(f"train {tr.sum()} / test {te.sum()} positions  (games {len(np.unique(d['gid']))})")

    kbs0 = refit(views_tr, default, None)
    tuned, kbs = tune(views_tr, a.mode, init)

    print("\n              black-view            white-view")
    print("              train     test        train     test")
    for name, p, kb in (('const', None, None), ('default', default, kbs0), ('tuned', tuned, kbs)):
        row = []
        for c in range(2):
            for vs in (views_tr, views_te):
                v = vs[c]
                if p is None:
                    row.append(float(np.mean((views_tr[c].y.mean() - v.y) ** 2)))
                else:
                    row.append(mse(v.score(p[c * PER:(c + 1) * PER]), v.y, kb[c]))
        print(f"  {name:10s}  {row[0]:.5f}  {row[1]:.5f}     {row[2]:.5f}  {row[3]:.5f}")
    ub = [linear_upper_bound(views_tr[c], views_te[c]) for c in range(2)]
    print(f"  {'free-linear':10s}  {'':7s}  {ub[0]:.5f}     {'':7s}  {ub[1]:.5f}")

    print("\nweights (black atk/def | white atk/def), default -> tuned")
    for k in TUNE_K:
        cells = []
        for c in range(2):
            for off in (W_ATK, W_DEF):
                i = c * PER + off + k
                cells.append(f"{default[i]:>6}->{tuned[i]:<6}")
        print(f"  {NAMES[k]:4s} " + '  '.join(cells))
    for c in range(2):
        b = c * PER
        print(f"  color {c + 1} bonus {default[b + BONUS:b + BONUS + 5]} -> {tuned[b + BONUS:b + BONUS + 5]}"
              f"  defnum {default[b + DEF_NUM]}->{tuned[b + DEF_NUM]}  extra {default[b + EXTRA_NUM]}->{tuned[b + EXTRA_NUM]}")
    json.dump(tuned, open(a.out, 'w'))
    print(f"\nwrote {a.out}")


if __name__ == '__main__':
    main()
