# -*- coding: utf-8 -*-
r"""
soccernet_add_xt.py
===================
soccernet_to_pitchlog.py が出したトラッキングCSVに、選手ごとの xT を付与する。

xT は攻撃方向に依存する（敵陣ゴール=高xT）。GSR は team=home/away しか
持たないので、各クリップで各チームの攻撃方向を「GKの位置」から推定する:
  GKが自陣ゴール側にいる → そちら(自陣)を守る → 逆方向へ攻める。
  GK_x < 0（左ゴール側）→ +x方向へ攻撃(dir=+1, x_normそのまま)
  GK_x > 0（右ゴール側）→ -x方向へ攻撃(dir=-1, 1-x_normで反転)
GKが取れないチームは相手の逆向き、双方不明なら home=+x/away=-x（低信頼）。

出力: 入力CSV + 列 attack_dir, xt（player/goalkeeper のみ。ball/referee は空）

使い方:
  python soccernet_add_xt.py --csv C:\soccernet\gamestate-2024\SNGS-116\SNGS-116_tracking.csv
  python soccernet_add_xt.py --csv C:\soccernet\gsr_test_all.csv --xt xT_BaseMap_105x68.csv
"""
import argparse
import os
import numpy as np
import pandas as pd

XB, YB = 105, 68


def load_xt(path):
    a = pd.read_csv(path, index_col=0).values.astype(np.float64)
    assert a.shape == (YB, XB), f"xT map shape {a.shape}"
    return a


def team_dirs(clip_df):
    """クリップ内の各チームの攻撃方向 dir(+1/-1) と推定方法を返す。"""
    dirs, method = {}, {}
    gk = clip_df[clip_df["role"] == "goalkeeper"]
    for t in ("home", "away"):
        g = gk[gk["team"] == t]
        if len(g):
            dirs[t] = 1 if g["x_m"].median() < 0 else -1
            method[t] = "gk"
    # 片方だけ判明 → 相手は逆
    if "home" in dirs and "away" not in dirs:
        dirs["away"] = -dirs["home"]; method["away"] = "opp"
    if "away" in dirs and "home" not in dirs:
        dirs["home"] = -dirs["away"]; method["home"] = "opp"
    # 双方不明 → 既定
    if not dirs:
        dirs = {"home": 1, "away": -1}; method = {"home": "default", "away": "default"}
    return dirs, method


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="トラッキングCSV（変換アダプタの出力）")
    ap.add_argument("--xt", default="xT_BaseMap_105x68.csv", help="xTベースマップCSV")
    ap.add_argument("--out", help="出力CSV（既定: 入力 + _xt）")
    args = ap.parse_args()

    xt = load_xt(args.xt)
    df = pd.read_csv(args.csv)
    df["team"] = df["team"].fillna("")

    df["attack_dir"] = np.nan
    df["xt"] = np.nan
    is_obj = df["role"].isin(["player", "goalkeeper"]) & df["team"].isin(["home", "away"])

    for clip, idx in df.groupby("clip").groups.items():
        cdf = df.loc[idx]
        dirs, method = team_dirs(cdf)
        sel = idx[is_obj.loc[idx]]
        for t in ("home", "away"):
            rows = sel[df.loc[sel, "team"] == t]
            if len(rows) == 0:
                continue
            d = dirs[t]
            xn = df.loc[rows, "x_norm"].to_numpy()
            yn = df.loc[rows, "y_norm"].to_numpy()
            xu = xn if d == 1 else (1.0 - xn)
            xi = np.clip((xu * XB).astype(int), 0, XB - 1)
            yi = np.clip((yn * YB).astype(int), 0, YB - 1)
            df.loc[rows, "attack_dir"] = d
            df.loc[rows, "xt"] = np.round(xt[yi, xi], 5)
        # サマリー
        amean = df.loc[sel, "xt"].mean()
        print(f"{clip}: dir home={dirs['home']:+d}({method['home']}) "
              f"away={dirs['away']:+d}({method['away']}) | xt平均 {amean:.4f}")

    out = args.out or (os.path.splitext(args.csv)[0] + "_xt.csv")
    df.to_csv(out, index=False, encoding="utf-8")
    print(f"-> {out}  ({len(df)} 行, xt付与 {int(df['xt'].notna().sum())} 行)")


if __name__ == "__main__":
    main()
