"""
add_zone_ids.py
===============
既存の Export CSV に Zone_ID 列を追加する（生の X,Y は残す・非破壊）。

Zone_ID = depth_band × 100 + width_row
  depth_band : X方向 21分割  1(左ゴール) … 21(右ゴール)   = floor(x_norm×21)+1
  width_row  : Y方向 14分割  0(上) … 13(下)               = floor((1-y_norm)×14)
位置が同じなら全選手・ボールで同じID（絶対座標マッピング）。

Usage:
  python docs/add_zone_ids.py [入力CSV] [出力CSV]
  省略時: Export_GSA_22players_30s.csv を上書き
"""
import sys
import numpy as np
import pandas as pd

DEPTH_BANDS = 21
WIDTH_ROWS = 14


def coord_to_zone_id(x_norm, y_norm):
    x = pd.to_numeric(x_norm, errors="coerce").to_numpy(dtype=float)
    y = pd.to_numeric(y_norm, errors="coerce").to_numpy(dtype=float)
    valid = ~(np.isnan(x) | np.isnan(y))
    band = np.clip(np.floor(np.where(valid, x, 0) * DEPTH_BANDS), 0, DEPTH_BANDS - 1) + 1
    row = np.clip(np.floor((1 - np.where(valid, y, 0)) * WIDTH_ROWS), 0, WIDTH_ROWS - 1)
    zid = band * 100 + row
    return pd.array(np.where(valid, zid, pd.NA), dtype=pd.Int64Dtype())


def add_zone_ids(df: pd.DataFrame) -> pd.DataFrame:
    subjects = [c[:-2] for c in df.columns if c.endswith("_X") and f"{c[:-2]}_Y" in df.columns]
    out = df.copy()
    for s in subjects:
        col = f"{s}_ZoneID"
        if col in out.columns:
            continue
        zid = coord_to_zone_id(out[f"{s}_X"], out[f"{s}_Y"])
        # GridID の隣に挿入（無ければ末尾）
        anchor = f"{s}_GridID"
        out[col] = zid
        if anchor in out.columns:
            cols = list(out.columns)
            cols.insert(cols.index(anchor) + 1, cols.pop(cols.index(col)))
            out = out[cols]
    return out


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "Export_GSA_22players_30s.csv"
    dst = sys.argv[2] if len(sys.argv) > 2 else src
    df = pd.read_csv(src)
    before = df.shape[1]
    df2 = add_zone_ids(df)
    df2.to_csv(dst, index=False)
    print(f"{src}: {before} cols -> {df2.shape[1]} cols  (+{df2.shape[1]-before} ZoneID)")
    # sample
    r = df2.iloc[150]
    print("sample frame 150:")
    for s in ["Ball", "Home_P1", "Away_P11"]:
        print(f"  {s}: X={r[s+'_X']:.3f} Y={r[s+'_Y']:.3f} -> ZoneID={r[s+'_ZoneID']}")
