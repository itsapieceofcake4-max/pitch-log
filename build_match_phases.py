"""
build_match_phases.py
=====================
SkillCorner phases_of_play.csv から、試合全体ビュー(app_24)用の
軽量サマリーCSV `match_phases_summary.csv` を生成する。
（cloud デプロイ用に同梱できるよう、必要列だけに絞った派生ファイル）

Usage:
  python build_match_phases.py [phases_of_play.csv] [out.csv]
  省略時: skillcorner_1925299/1925299_phases_of_play.csv を読む
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

HOME_ID, AWAY_ID = 1802, 871
HOME_NAME, AWAY_NAME = "Brisbane", "Perth"
HALF_LEN = 45.0  # 後半オフセット(分)

DEFAULT_IN = "skillcorner_1925299/1925299_phases_of_play.csv"
DEFAULT_OUT = "match_phases_summary.csv"
XT_MAP_CSV  = "xT_BaseMap_105x68.csv"

PITCH_L, PITCH_W = 105.0, 68.0
X_BINS, Y_BINS   = 105, 68


def load_xt_map(path: str) -> np.ndarray:
    arr = pd.read_csv(path, index_col=0).values.astype(np.float64)
    assert arr.shape == (Y_BINS, X_BINS), f"xT map shape {arr.shape}"
    return arr


def phase_xt(xt_map: np.ndarray, x_m, y_m, attacking_side) -> np.ndarray:
    """
    フェーズ座標(メートル・中心原点) → 実xT。
    xTマップは「x=1方向へ攻撃」基準なので、right_to_left は x をミラー。
    """
    x = np.asarray(x_m, dtype=float)
    y = np.asarray(y_m, dtype=float)
    valid = ~(np.isnan(x) | np.isnan(y))
    xn = np.clip((np.where(valid, x, 0) + PITCH_L / 2) / PITCH_L, 0, 1)
    yn = np.clip((np.where(valid, y, 0) + PITCH_W / 2) / PITCH_W, 0, 1)
    rtl = np.asarray(attacking_side) == "right_to_left"
    xn = np.where(rtl, 1 - xn, xn)          # 攻撃方向を x=1 に揃える
    xi = np.clip(np.floor(xn * X_BINS).astype(int), 0, X_BINS - 1)
    yi = np.clip(np.floor(yn * Y_BINS).astype(int), 0, Y_BINS - 1)
    return np.where(valid, xt_map[yi, xi], 0.0)


def build(src: str, dst: str, xt_path: str = XT_MAP_CSV) -> pd.DataFrame:
    df = pd.read_csv(src)
    out = pd.DataFrame()
    out["index"]      = df["index"]
    out["period"]     = df["period"]
    out["frame_start"] = df["frame_start"]
    out["frame_end"]   = df["frame_end"]
    out["minute"]     = df["minute_start"]
    out["second"]     = df["second_start"]
    df = pd.read_csv(src)
    out = pd.DataFrame()
    out["index"]      = df["index"]
    out["period"]     = df["period"]
    out["frame_start"] = df["frame_start"]
    out["frame_end"]   = df["frame_end"]
    out["minute"]     = df["minute_start"]
    out["second"]     = df["second_start"]
    # 連続表示時間(分): 後半は +45
    t = df["minute_start"] + df["second_start"] / 60.0
    out["t_min"]      = np.where(df["period"] == 2, t + HALF_LEN, t).round(3)
    out["duration"]   = df["duration"]

    is_home = df["team_in_possession_id"] == HOME_ID
    out["team"]       = np.where(is_home, "Home", "Away")
    out["team_name"]  = np.where(is_home, HOME_NAME, AWAY_NAME)
    out["phase_type"] = df["team_in_possession_phase_type"]
    out["third_start"] = df["third_start"]
    out["third_end"]   = df["third_end"]
    out["x_start"]    = df["x_start"]
    out["x_end"]      = df["x_end"]
    out["pen_area_end"] = df["penalty_area_end"].astype(bool)

    is_shot = df["team_possession_lead_to_shot"].astype(bool)
    is_goal_raw = df["team_possession_lead_to_goal"].astype(bool)

    # 得点シーケンスは複数フェーズに分割される → 連続得点フェーズの最後だけをゴール本体に
    gi = is_goal_raw.values
    tid = df["team_in_possession_id"].values
    goal_moment = np.zeros(len(df), dtype=bool)
    for i in range(len(df)):
        if gi[i] and (i + 1 >= len(df) or not (gi[i + 1] and tid[i + 1] == tid[i])):
            goal_moment[i] = True

    out["is_shot"]    = is_shot
    out["is_goal"]    = goal_moment

    # ── xT実値ベースのモメンタム（一般的指標：xT added per possession）──
    xt_map = load_xt_map(xt_path)
    xt_s = phase_xt(xt_map, df["x_start"], df["y_start"], df["attacking_side"])
    xt_e = phase_xt(xt_map, df["x_end"],   df["y_end"],   df["attacking_side"])
    xt_gain = xt_e - xt_s                       # そのフェーズで稼いだ脅威(ΔxT)
    out["xt_start"] = xt_s.round(5)
    out["xt_end"]   = xt_e.round(5)
    out["xt_gain"]  = xt_gain.round(5)
    # Home=+ / Away=- の符号付きΔxT がモメンタムの素
    out["signed"]   = (xt_gain * np.where(is_home, 1.0, -1.0)).round(5)

    # キーモーメント分類（Home視点）
    #   goal_home/away : 得点本体 / chance: Homeのシュート機会 / pinch: Awayのシュート機会
    kind = []
    for sh, go, hm in zip(is_shot.values, goal_moment, is_home.values):
        if go:
            kind.append("goal_home" if hm else "goal_away")
        elif sh:
            kind.append("chance" if hm else "pinch")
        else:
            kind.append("")
    out["moment"] = kind

    out = out.sort_values("t_min").reset_index(drop=True)
    out.to_csv(dst, index=False)
    return out


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_IN
    dst = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT
    if not Path(src).exists():
        sys.exit(f"ERROR: {src} not found")
    out = build(src, dst)
    n_goal = (out["moment"].str.startswith("goal")).sum()
    print(f"saved -> {dst}  rows={len(out)}")
    print(f"  chance={int((out.moment=='chance').sum())}  "
          f"pinch={int((out.moment=='pinch').sum())}  goals={int(n_goal)}")
