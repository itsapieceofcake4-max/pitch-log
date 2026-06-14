# -*- coding: utf-8 -*-
r"""
describe_features.py
====================
enrich_gsa_features.py の出力（全特徴量サンプル）に、各列の「内容（説明）」を付ける。

出力2種:
  1) <out>_annotated.csv  … 横持ち。ヘッダ=指標名 / 1行目=内容 / 2行目=サンプル先頭値
  2) <out>_dictionary.csv … 縦持ち。1指標=1行（No, 指標名, カテゴリ, 内容, サンプル値）

使い方:
  python describe_features.py --csv C:\Users\User\Desktop\sample_full_features.csv
"""
import argparse
import os
import re
import pandas as pd

# 主語を剥がした「コア」名 → (カテゴリ, 内容)
CORE = {
    "X": ("基本", "X座標（正規化0–1, 1=敵陣ゴール方向）"),
    "Y": ("基本", "Y座標（正規化0–1）"),
    "GridID": ("基本", "105×68グリッドのセルID（1–7140）"),
    "ZoneID": ("基本", "絶対ゾーンID（深度21×幅14）"),
    "xT": ("基本", "期待脅威xT（攻撃方向で向き付け）"),
    "MAX_xT": ("基本", "チーム内の最大xT"),
    "SUM_xT": ("基本", "チーム内の合計xT"),
    "vx": ("①速度", "速度のX成分（m/s）"),
    "vy": ("①速度", "速度のY成分（m/s）"),
    "speed": ("①速度", "速度の大きさ（m/s）"),
    "acceleration": ("①速度", "加速度（m/s²）"),
    "direction": ("①速度", "進行方向（度）"),
    "is_sprinting": ("①速度", "スプリント判定（>5.5m/s, 0/1）"),
    "dist_traveled": ("①速度", "累積走行距離（m）"),
    "dist_goal": ("②距離", "攻撃ゴールまでの距離（m）"),
    "dist_goal_home": ("②距離", "ボール→Homeゴール距離（m）"),
    "dist_goal_away": ("②距離", "ボール→Awayゴール距離（m）"),
    "dist_nearest_opp": ("②距離", "最近接の相手との距離（m）"),
    "n_opp_within_3m": ("②距離", "3m以内の相手数（プレッシャー強度）"),
    "n_opp_within_5m": ("②距離", "5m以内の相手数"),
    "carrier_team": ("②距離", "ボール保持チーム（Home/Away/空）"),
    "centroid_X": ("③形状", "チーム重心のX"),
    "centroid_Y": ("③形状", "チーム重心のY"),
    "width": ("③形状", "チーム横幅（m）"),
    "depth": ("③形状", "チーム縦幅（m）"),
    "compactness": ("③形状", "選手間の平均距離（m, 小=密集）"),
    "hull_area": ("③形状", "布陣の凸包面積（m²）"),
    "last_def_line_X": ("③形状", "最終DFラインのX（正規化）"),
    "Zone_5div": ("④ゾーン", "縦5分割ゾーン（1–5）"),
    "Zone_lateral": ("④ゾーン", "横3分割（left/center/right）"),
    "Grid20": ("④ゾーン", "5×4=20分割グリッド（1–20）"),
    "in_penalty_area": ("④ゾーン", "ペナルティエリア内フラグ（0/1）"),
    "in_box_18yard": ("④ゾーン", "18yardボックス内（0/1）"),
    "in_half_space": ("④ゾーン", "ハーフスペース内（0/1）"),
    "zone_transition": ("④ゾーン", "ゾーン変化フラグ（0/1）"),
    "attacking_third_dwell": ("④ゾーン", "アタッキングサード滞在の累計（秒）"),
    "Delta_xT": ("⑦個人xT", "xT変化量（前フレーム差）"),
    "Cumulative_xT_gain": ("⑦個人xT", "累積xT獲得（正の増分の積み上げ）"),
    "xT_smoothed_3f": ("⑦個人xT", "xTの3フレーム移動平均"),
    "peak_xT_in_scene": ("⑦個人xT", "シーン中の最大xT"),
    "xT_acceleration": ("⑦個人xT", "xT変化の加速度"),
    "xT_weighted_centroid_X": ("⑦個人xT", "xT加重重心のX"),
    "xT_lag1": ("⑧ラグ", "0.1秒前のxT"),
    "xT_lag5": ("⑧ラグ", "0.5秒前のxT"),
    "xT_lag10": ("⑧ラグ", "1秒前のxT"),
    "xT_lag20": ("⑧ラグ", "2秒前のxT"),
    "speed_lag5": ("⑧ラグ", "0.5秒前の速度"),
    "xT_smoothed_5f": ("⑩目的変数", "xTの5フレーム移動平均（ノイズ除去）"),
    "forward_velocity": ("⑥パス", "ボールの前進速度（保持方向, m/s）"),
}

# 完全一致（グローバル列）
EXACT = {
    "Frame": ("基本", "フレーム番号（1–300）"),
    "Time": ("基本", "相対時刻（秒）"),
    "Match_Time_sec": ("基本", "シーン内の経過秒"),
    "is_line_breaking_pass": ("⑥パス", "ライン突破パス進行中（0/1）"),
    "lbp_passer": ("⑥パス", "突破パスのパサー（player id）"),
    "lbp_receiver": ("⑥パス", "突破パスの受け手"),
    "lbp_nearby_def_count": ("⑥パス", "受け手周辺の守備者数"),
    "Pressure_on_carrier": ("②距離", "ボール保持者の3m以内の相手数"),
    "Ball_possession": ("⑤局面", "保持チーム（H/A/空）"),
    "Possession_duration_sec": ("⑤局面", "連続保持時間（秒）"),
    "Possession_team_phase": ("⑤局面", "攻撃局面（build_up/create/finish/direct）"),
    "Defensive_phase": ("⑤局面", "守備局面（block/press 等）"),
    "Is_open_play": ("⑤局面", "オープンプレー中（0/1）"),
    "Is_set_piece": ("⑤局面", "セットプレー中（0/1）"),
    "Pass_event_flag": ("⑥パス", "パス発生フレーム（0/1）"),
    "Pass_xT_gain": ("⑥パス", "そのパスのxT（SkillCorner xthreat）"),
    "Pass_distance_m": ("⑥パス", "パス距離（m）"),
    "Pass_forward_component_m": ("⑥パス", "パスの前進成分（m）"),
    "Pass_breaks_line_count": ("⑥パス", "突破した守備ライン数（0–3）"),
    "Ball_forward_velocity": ("⑥パス", "ボールの前進速度（保持方向, m/s）"),
    "Is_pass_moment": ("⑨events", "パス発生フラグ（events由来, 0/1）"),
    "Is_shot_moment": ("⑨events", "シュート脅威フレーム（xshot>0, 0/1）"),
    "Is_engagement_moment": ("⑨events", "守備接触（デュエル/プレス）中（0/1）"),
    "Is_off_ball_run_active": ("⑨events", "オフボールラン進行中（0/1）"),
    "OffBallRun_subtype": ("⑨events", "進行中ランの種別（overlap/裏抜け等）"),
    "Pressing_chain_active": ("⑨events", "プレッシングチェーン進行中（0/1）"),
    "possession_danger_active": ("⑨events", "危険な保持局面（VAEP的価値の代替）"),
    "Ball_xT_smoothed_5f": ("⑩目的変数", "Ball_xTの5フレーム移動平均"),
    "Delta_Ball_xT_smoothed_3f": ("⑩目的変数", "平滑化Ball_xTの変化量"),
    "Ball_xT_max_in_5sec_window": ("⑩目的変数", "直近5秒の最大Ball_xT"),
    "Time_to_peak_xT_sec": ("⑩目的変数", "xTピークまでの秒数（負=ピーク後）"),
    "Time_to_goal_sec": ("⑩目的変数", "ゴールまでの残り秒数"),
    "Is_attacking_third_entry": ("⑩目的変数", "アタッキングサード進入の瞬間（0/1）"),
    "Is_penalty_area_entry": ("⑩目的変数", "ペナルティエリア進入の瞬間（0/1）"),
}


def subject_and_core(col):
    m = re.match(r"(Home|Away)_P(\d+)_(.+)", col)
    if m:
        return f"{m.group(1)}選手{m.group(2)}", m.group(3)
    if col.startswith("Ball_"):
        return "ボール", col[5:]
    m = re.match(r"(Home|Away)_(.+)", col)
    if m:
        return f"{m.group(1)}チーム", m.group(2)
    return "", col


def describe(col):
    if col in EXACT:
        cat, desc = EXACT[col]
        return cat, desc
    subj, core = subject_and_core(col)
    if core in CORE:
        cat, desc = CORE[core]
        return cat, (f"{subj}の{desc}" if subj else desc)
    return "?", "(説明未登録)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    args = ap.parse_args()
    d = pd.read_csv(args.csv)
    cols = list(d.columns)
    cats = [describe(c)[0] for c in cols]
    descs = [describe(c)[1] for c in cols]
    first = d.iloc[0]

    stem = os.path.splitext(args.csv)[0]

    # 1) 横持ち: ヘッダ=名前 / 1行目=内容 / 2行目=サンプル値
    wide = pd.DataFrame([descs, list(first.values)], columns=cols, index=["内容", "サンプル値(先頭フレーム)"])
    wide_path = stem + "_annotated.csv"
    wide.to_csv(wide_path, encoding="utf-8-sig")

    # 2) 縦持ち: 1指標=1行
    long = pd.DataFrame({"No": range(1, len(cols)+1), "指標名": cols,
                         "カテゴリ": cats, "内容": descs,
                         "サンプル値(先頭フレーム)": list(first.values)})
    long_path = stem + "_dictionary.csv"
    long.to_csv(long_path, index=False, encoding="utf-8-sig")

    print(f"指標数: {len(cols)}")
    print(f"横持ち -> {wide_path}")
    print(f"縦持ち -> {long_path}")
    miss = [c for c in cols if describe(c)[1] == "(説明未登録)"]
    print(f"説明未登録: {len(miss)}", miss[:10])


if __name__ == "__main__":
    main()
