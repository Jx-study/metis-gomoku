"""probe.py 與 probe_reg.py 共用元件：模型結構、batch 組裝、資料切分。

網路結構與 C 端推理逐層對應，量化時不必換架構：
第一層稀疏累加器（黑白共用權重）、clipped ReLU、fc1（bias 分色）、clipped ReLU、fc2 依序相接。
"""
import numpy as np
import torch
import torch.nn as nn

CLIP = 127.0

# 對照基準來自 Texel 調參實驗（同一批棋譜、同一種 WDL 標籤、同樣以對局為單位切 80/20）
TEXEL_TUNED = 0.19106
FREE_LINEAR = 0.19235


class Probe(nn.Module):
    def __init__(self, n_feats, acc, l1):
        super().__init__()
        self.emb = nn.EmbeddingBag(n_feats, acc, mode='sum')
        self.acc_bias = nn.Parameter(torch.zeros(acc))
        self.fc1 = nn.Linear(2 * acc, l1)
        self.fc1_bias_white = nn.Parameter(torch.zeros(l1))
        self.fc2 = nn.Linear(l1, 1)

    def forward(self, bf, boff, wf, woff, black_view):
        ab = self.emb(bf, boff) + self.acc_bias
        aw = self.emb(wf, woff) + self.acc_bias
        v = black_view.unsqueeze(1)
        me = torch.where(v, ab, aw)
        them = torch.where(v, aw, ab)
        a = torch.cat([me, them], dim=1).clamp(0.0, CLIP)
        h = self.fc1(a) + torch.where(v, torch.zeros_like(self.fc1_bias_white),
                                      self.fc1_bias_white)
        return torch.sigmoid(self.fc2(h.clamp(0.0, CLIP))).squeeze(-1)


def make_batch(flat, off, idx):
    """從 ragged 陣列取一批，回傳 EmbeddingBag 要的 (input, offsets)。"""
    parts, offs, cur = [], [], 0
    for i in idx:
        s, e = off[i], off[i + 1]
        parts.append(flat[s:e])
        offs.append(cur)
        cur += e - s
    inp = np.concatenate(parts).astype(np.int64) if cur else np.zeros(0, dtype=np.int64)
    return torch.from_numpy(inp), torch.tensor(offs, dtype=torch.long)


def load_split(feats_path, seed):
    """讀 feats.npz，回傳 (n_feats, bf, boff, wf, woff, y_black, rng, tr, te)。

    以對局為單位切 80/20：同一局的局面高度相關，按局面切會讓保留集偷看到訓練局。
    """
    d = np.load(feats_path)
    n_feats = int(d['n_feats'])
    bf, boff, wf, woff = d['bf'], d['boff'], d['wf'], d['woff']
    res = d['result']
    y_black = np.where(res == 1, 1.0, np.where(res == 0, 0.5, 0.0)).astype(np.float32)

    gid = d['gid']
    rng = np.random.RandomState(seed)
    games = np.unique(gid)
    rng.shuffle(games)
    test_games = set(games[:max(1, int(len(games) * 0.2))].tolist())
    is_test = np.isin(gid, list(test_games))
    tr, te = np.where(~is_test)[0], np.where(is_test)[0]
    return n_feats, bf, boff, wf, woff, y_black, rng, tr, te


def make_run_epoch(model, opt, loss_fn, bf, boff, wf, woff, y_black, batch, rng):
    """回傳一個跑完整個 idx 一輪（訓練或評估）並回傳平均 loss 的函數。"""
    def run(idx, view_black, train):
        tot = cnt = 0
        order = rng.permutation(len(idx)) if train else np.arange(len(idx))
        for i in range(0, len(idx), batch):
            sel = idx[order[i:i + batch]]
            bi, bo = make_batch(bf, boff, sel)
            wi, wo = make_batch(wf, woff, sel)
            v = torch.full((len(sel),), view_black, dtype=torch.bool)
            y = torch.from_numpy(y_black[sel] if view_black else 1.0 - y_black[sel])
            loss = loss_fn(model(bi, bo, wi, wo, v), y)
            if train:
                opt.zero_grad()
                loss.backward()
                opt.step()
            tot += loss.item() * len(sel)
            cnt += len(sel)
        return tot / cnt
    return run


def print_baseline(const, te_b, te_w, label='probe test (黑/白)'):
    print(f"\nconst baseline         {const:.5f}")
    print(f"Texel tuned (參考)      {TEXEL_TUNED:.5f}")
    print(f"free linear (參考)      {FREE_LINEAR:.5f}")
    print(f"{label}      {te_b:.5f} / {te_w:.5f}")


def print_gate_note():
    print("閘門: < 0.180 通過；0.180-0.188 邊際；> 0.188 不通過")
