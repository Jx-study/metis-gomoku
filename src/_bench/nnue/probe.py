"""量位置感知特徵能把保留集 MSE 壓到多低。

用法: python probe.py <feats.npz> [--acc 64] [--l1 32] [--epochs 30] [--seed 0]

判讀標準：
    test MSE < 0.180：通過
    0.180 <= MSE <= 0.188：邊際，要人工判斷
    MSE > 0.188：不通過

模型結構、batch 組裝、資料切分見 probe_common.py（與 probe_reg.py 共用）。
"""
import argparse

import numpy as np
import torch
import torch.nn as nn

import probe_common as pc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('feats')
    ap.add_argument('--acc', type=int, default=64)
    ap.add_argument('--l1', type=int, default=32)
    ap.add_argument('--epochs', type=int, default=30)
    ap.add_argument('--batch', type=int, default=1024)
    ap.add_argument('--lr', type=float, default=1e-3)
    ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()

    n_feats, bf, boff, wf, woff, y_black, rng, tr, te = pc.load_split(a.feats, a.seed)

    torch.manual_seed(a.seed)
    model = pc.Probe(n_feats, a.acc, a.l1)
    opt = torch.optim.Adam(model.parameters(), lr=a.lr)
    loss_fn = nn.MSELoss()
    run = pc.make_run_epoch(model, opt, loss_fn, bf, boff, wf, woff, y_black, a.batch, rng)

    const = float(np.mean((y_black[te] - y_black[tr].mean()) ** 2))
    te_b = te_w = float('nan')
    for ep in range(a.epochs):
        model.train()
        tr_b, tr_w = run(tr, True, True), run(tr, False, True)
        model.eval()
        with torch.no_grad():
            te_b, te_w = run(te, True, False), run(te, False, False)
        print(f"epoch {ep+1}/{a.epochs} train={tr_b:.5f}/{tr_w:.5f} test={te_b:.5f}/{te_w:.5f}")

    pc.print_baseline(const, te_b, te_w)
    pc.print_gate_note()


if __name__ == '__main__':
    main()
