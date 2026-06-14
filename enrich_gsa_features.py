# -*- coding: utf-8 -*-
r"""
enrich_gsa_features.py
======================
Export_GSA（位置・xT・GridID）に、feature_catalog の全10カテゴリの指標を付与する。

自前計算（位置・xTから）:
  ① 動き・速度系  ② 距離・位置関係  ③ チーム形状  ④ ゾーン拡張
  ⑦ 個人xT変化   ⑧ 時間ラグ       ⑩ 目的変数候補
SkillCorner 結合（dynamic_events / phases_of_play から、生フレームで対応付け）:
  ⑤ 所有・フェーズ  ⑥ パス・前進系  ⑨ events連動（off-ball run / pressing / xshot 等）

使い方:
  python enrich_gsa_features.py --gsa C:\skillcorner_gsa\Export_GSA_1925299_P2_7351.csv \
      --match-dir C:\skillcorner_opendata\data\matches\1925299 --goal-frame 44311 \
      --out C:\Users\User\Desktop\sample_full_features.csv
"""
import argparse
import math
import os
import warnings
import numpy as np
import pandas as pd

warnings.simplefilter("ignore")  # DataFrame断片化の PerformanceWarning を抑制

PL, PW = 105.0, 68.0
DT = 0.1  # 10fps
SPRINT_MS = 5.5


def players_present(cols):
    out = []
    for tm in ("Home", "Away"):
        for i in range(1, 12):
            if f"{tm}_P{i}_X" in cols:
                out.append(f"{tm}_P{i}")
    return out


def hull_area(xs, ys):
    pts = sorted(set(zip(xs, ys)))
    if len(pts) < 3:
        return 0.0
    def cross(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])
    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    a = 0.0
    for i in range(len(hull)):
        x1, y1 = hull[i]; x2, y2 = hull[(i+1) % len(hull)]
        a += x1*y2 - x2*y1
    return abs(a) / 2.0


def add_kinematics(df, subj):
    """subj は 'Ball' か 'Home_Pn'。速度/加速度等を付与。"""
    x = df[f"{subj}_X"].to_numpy(dtype=float) * PL
    y = df[f"{subj}_Y"].to_numpy(dtype=float) * PW
    vx = np.gradient(x) / DT
    vy = np.gradient(y) / DT
    sp = np.hypot(vx, vy)
    df[f"{subj}_vx"] = np.round(vx, 3)
    df[f"{subj}_vy"] = np.round(vy, 3)
    df[f"{subj}_speed"] = np.round(sp, 3)
    df[f"{subj}_acceleration"] = np.round(np.gradient(sp) / DT, 3)
    if subj == "Ball":
        df["Ball_direction"] = np.round(np.degrees(np.arctan2(vy, vx)), 1)
    else:
        df[f"{subj}_is_sprinting"] = (sp > SPRINT_MS).astype(int)
        step = np.hypot(np.diff(x, prepend=x[0]), np.diff(y, prepend=y[0]))
        df[f"{subj}_dist_traveled"] = np.round(np.cumsum(step), 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gsa", required=True)
    ap.add_argument("--match-dir", required=True)
    ap.add_argument("--goal-frame", type=int, required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    d = pd.read_csv(args.gsa)
    N = len(d)
    subs = players_present(d.columns)
    mid = os.path.basename(args.match_dir.rstrip("\\/"))

    # ── ① 動き・速度系 ──
    add_kinematics(d, "Ball")
    for s in subs:
        add_kinematics(d, s)

    # ── ② 距離・位置関係 ──
    home = [s for s in subs if s.startswith("Home")]
    away = [s for s in subs if s.startswith("Away")]
    HX = {s: d[f"{s}_X"].to_numpy(float) for s in subs}
    HY = {s: d[f"{s}_Y"].to_numpy(float) for s in subs}
    for s in subs:
        opp = away if s.startswith("Home") else home
        goalx = 1.0 if s.startswith("Home") else 0.0
        dg = np.hypot((goalx - HX[s]) * PL, (0.5 - HY[s]) * PW)
        d[f"{s}_dist_goal"] = np.round(dg, 2)
        if opp:
            om = np.stack([np.hypot((HX[s]-HX[o])*PL, (HY[s]-HY[o])*PW) for o in opp], axis=1)
            d[f"{s}_dist_nearest_opp"] = np.round(np.nanmin(om, axis=1), 2)
            d[f"{s}_n_opp_within_3m"] = np.nansum(om <= 3.0, axis=1).astype(int)
            d[f"{s}_n_opp_within_5m"] = np.nansum(om <= 5.0, axis=1).astype(int)
    bx, by = d["Ball_X"].to_numpy(float), d["Ball_Y"].to_numpy(float)
    d["Ball_dist_goal_home"] = np.round(np.hypot((1-bx)*PL, (0.5-by)*PW), 2)
    d["Ball_dist_goal_away"] = np.round(np.hypot(bx*PL, (0.5-by)*PW), 2)
    # 保持者＝ボール最近接（2m以内）
    allm = np.stack([np.hypot((bx-HX[s])*PL, (by-HY[s])*PW) for s in subs], axis=1)
    nearest = np.nanargmin(np.where(np.isnan(allm), 1e9, allm), axis=1)
    nd = allm[np.arange(N), nearest]
    carrier = np.where(nd <= 2.0, [subs[i].split("_")[0] for i in nearest], "")
    d["Ball_carrier_team"] = carrier
    pres = np.zeros(N, int)
    for f in range(N):
        if carrier[f] in ("Home", "Away"):
            cs = subs[nearest[f]]
            opp = away if cs.startswith("Home") else home
            pres[f] = sum(np.hypot((HX[cs][f]-HX[o][f])*PL, (HY[cs][f]-HY[o][f])*PW) <= 3.0 for o in opp)
    d["Pressure_on_carrier"] = pres

    # ── ③ チーム形状 ──
    for tm, plist in (("Home", home), ("Away", away)):
        xs = np.stack([HX[s] for s in plist], axis=1)
        ys = np.stack([HY[s] for s in plist], axis=1)
        d[f"{tm}_centroid_X"] = np.round(np.nanmean(xs, 1), 4)
        d[f"{tm}_centroid_Y"] = np.round(np.nanmean(ys, 1), 4)
        d[f"{tm}_width"] = np.round((np.nanmax(ys, 1)-np.nanmin(ys, 1))*PW, 2)
        d[f"{tm}_depth"] = np.round((np.nanmax(xs, 1)-np.nanmin(xs, 1))*PL, 2)
        comp = []
        for f in range(N):
            pp = np.stack([xs[f]*PL, ys[f]*PW], axis=1)
            dd = [np.hypot(*(pp[i]-pp[j])) for i in range(len(pp)) for j in range(i+1, len(pp))]
            comp.append(np.nanmean(dd) if dd else np.nan)
        d[f"{tm}_compactness"] = np.round(comp, 2)
        d[f"{tm}_hull_area"] = [round(hull_area(xs[f]*PL, ys[f]*PW), 1) for f in range(N)]
        sx = np.sort(np.where(np.isnan(xs), 1.0 if tm == "Home" else 0.0, xs), axis=1)
        d[f"{tm}_last_def_line_X"] = np.round(sx[:, 1] if tm == "Home" else sx[:, -2], 4)

    # ── ④ ゾーン拡張 ──
    d["Ball_Zone_5div"] = np.clip((bx*5).astype(int)+1, 1, 5)
    d["Ball_Zone_lateral"] = np.select([by < 1/3, by > 2/3], ["left", "right"], "center")
    d["Ball_Grid20"] = np.clip((bx*5).astype(int), 0, 4)*4 + np.clip((by*4).astype(int), 0, 3) + 1
    d["Ball_in_penalty_area"] = (((bx >= 0.83) | (bx <= 0.17)) & (by >= 0.21) & (by <= 0.79)).astype(int)
    d["Ball_in_box_18yard"] = (((bx >= 0.83) | (bx <= 0.17)) & (by >= 0.21) & (by <= 0.79)).astype(int)
    d["Ball_in_half_space"] = (((by >= 0.21) & (by <= 0.37)) | ((by >= 0.63) & (by <= 0.79))).astype(int)
    d["Ball_zone_transition"] = (d["Ball_Zone_5div"].diff().fillna(0) != 0).astype(int)
    d["Ball_attacking_third_dwell"] = np.round((bx >= 0.66).cumsum()*DT, 1)

    # ── ⑦ 個人xT変化 ──
    for s in subs:
        xt = pd.to_numeric(d[f"{s}_xT"], errors="coerce")
        d[f"{s}_Delta_xT"] = xt.diff().round(5).fillna(0)
        d[f"{s}_Cumulative_xT_gain"] = xt.clip(lower=0).cumsum().round(5)
        d[f"{s}_xT_smoothed_3f"] = xt.rolling(3, min_periods=1).mean().round(5)
        d[f"{s}_peak_xT_in_scene"] = round(float(xt.max() or 0), 5)
        d[f"{s}_xT_acceleration"] = xt.diff().diff().round(5).fillna(0)
    for tm, plist in (("Home", home), ("Away", away)):
        xts = np.stack([pd.to_numeric(d[f"{s}_xT"], errors="coerce").to_numpy() for s in plist], axis=1)
        xs = np.stack([HX[s] for s in plist], axis=1)
        w = np.nansum(xts, axis=1)
        d[f"{tm}_xT_weighted_centroid_X"] = np.round(
            np.nansum(np.nan_to_num(xts)*np.nan_to_num(xs), axis=1)/np.where(w == 0, np.nan, w), 4)

    # ── ⑧ 時間ラグ ──
    bxt = pd.to_numeric(d["Ball_xT"], errors="coerce")
    for lag in (1, 5, 10, 20):
        d[f"Ball_xT_lag{lag}"] = bxt.shift(lag).round(5)
    for s in subs:
        xt = pd.to_numeric(d[f"{s}_xT"], errors="coerce")
        d[f"{s}_xT_lag5"] = xt.shift(5).round(5)
        d[f"{s}_xT_lag10"] = xt.shift(10).round(5)
        d[f"{s}_speed_lag5"] = d[f"{s}_speed"].shift(5)

    # ── ⑩ 目的変数候補 ──
    d["Ball_xT_smoothed_5f"] = bxt.rolling(5, min_periods=1).mean().round(5)
    d["Delta_Ball_xT_smoothed_3f"] = d["Ball_xT_smoothed_5f"].diff().round(5).fillna(0)
    d["Ball_xT_max_in_5sec_window"] = bxt.rolling(50, min_periods=1).max().round(5)
    peak_i = int(np.nanargmax(bxt.to_numpy()))
    d["Time_to_peak_xT_sec"] = np.round((peak_i - np.arange(N))*DT, 1)
    d["Time_to_goal_sec"] = np.round((N - 1 - np.arange(N))*DT, 1)
    d["Is_attacking_third_entry"] = ((bx >= 0.66) & (pd.Series(bx).shift(1).fillna(0) < 0.66)).astype(int)
    d["Is_penalty_area_entry"] = (d["Ball_in_penalty_area"].diff().fillna(0) == 1).astype(int)

    # ── ⑤⑥⑨ SkillCorner 結合（生フレームで対応付け）──
    raw = args.goal_frame - N + (d["Frame"].to_numpy())  # Frame=N → goal_frame
    d["_raw_frame"] = raw
    rmin, rmax = int(raw.min()), int(raw.max())
    ev = pd.read_csv(os.path.join(args.match_dir, f"{mid}_dynamic_events.csv"))
    ev = ev[(ev["frame_end"] >= rmin) & (ev["frame_start"] <= rmax)].copy()
    ph = pd.read_csv(os.path.join(args.match_dir, f"{mid}_phases_of_play.csv"))
    ph = ph[(ph["frame_end"] >= rmin) & (ph["frame_start"] <= rmax)].copy()
    import json
    with open(os.path.join(args.match_dir, f"{mid}_match.json"), encoding="utf-8") as f:
        home_id = json.load(f)["home_team"]["id"]

    def frames_of(sub):
        m = np.zeros(N, bool)
        for _, r in sub.iterrows():
            a = max(int(r["frame_start"]), rmin); b = min(int(r["frame_end"]), rmax)
            m[(raw >= a) & (raw <= b)] = True
        return m

    # ⑤ 所有・フェーズ
    poss = np.array([""]*N, dtype=object); pdur = np.zeros(N); ptype = np.array([""]*N, object)
    dphase = np.array([""]*N, object)
    for _, r in ph.iterrows():
        a = max(int(r["frame_start"]), rmin); b = min(int(r["frame_end"]), rmax)
        sel = (raw >= a) & (raw <= b)
        poss[sel] = "H" if r["team_in_possession_id"] == home_id else "A"
        pdur[sel] = (raw[sel]-int(r["frame_start"]))*DT
        ptype[sel] = str(r.get("team_in_possession_phase_type"))
        dphase[sel] = str(r.get("team_out_of_possession_phase_type"))
    d["Ball_possession"] = poss
    d["Possession_duration_sec"] = np.round(pdur, 1)
    d["Possession_team_phase"] = ptype
    d["Defensive_phase"] = dphase
    interr = ev[ev["game_interruption_before"].astype(str).str.lower().ne("nan") &
               ev["game_interruption_before"].notna()]
    d["Is_set_piece"] = frames_of(interr).astype(int)
    d["Is_open_play"] = (1 - d["Is_set_piece"]).astype(int)

    # ⑥ パス・前進系（player_possession のうちパス）
    pp = ev[ev["event_type"] == "player_possession"].copy()
    passes = pp[pp["pass_distance"].notna()]
    pflag = np.zeros(N, int); pxt = np.zeros(N); pdist = np.zeros(N); pfwd = np.zeros(N); pbrk = np.zeros(N, int)
    for _, r in passes.iterrows():
        fs = int(r["frame_start"])
        idx = np.where(raw == fs)[0]
        if len(idx) == 0:
            idx = [int(np.argmin(np.abs(raw - fs)))]
        i = idx[0]
        pflag[i] = 1
        pxt[i] = float(r.get("xthreat") or 0)
        pdist[i] = float(r.get("pass_distance") or 0)
        pfwd[i] = float(r.get("pass_distance") or 0) * (1 if r.get("pass_ahead") else -0)
        pbrk[i] = int(bool(r.get("first_line_break"))) + int(bool(r.get("second_last_line_break"))) + int(bool(r.get("last_line_break")))
    d["Pass_event_flag"] = pflag
    d["Pass_xT_gain"] = np.round(pxt, 5)
    d["Pass_distance_m"] = np.round(pdist, 2)
    d["Pass_forward_component_m"] = np.round(pfwd, 2)
    d["Pass_breaks_line_count"] = pbrk
    fv = d["Ball_vx"].to_numpy()
    d["Ball_forward_velocity"] = np.round(np.where(poss == "A", -fv, fv), 3)

    # ⑨ events連動
    d["Is_pass_moment"] = (d["Pass_event_flag"] == 1).astype(int)
    eng = ev[ev["event_type"] == "on_ball_engagement"]
    d["Is_engagement_moment"] = frames_of(eng).astype(int)
    obr = ev[ev["event_type"] == "off_ball_run"]
    d["Is_off_ball_run_active"] = frames_of(obr).astype(int)
    # 進行中のオフボールラン種別
    runsub = np.array([""]*N, object)
    for _, r in obr.iterrows():
        a = max(int(r["frame_start"]), rmin); b = min(int(r["frame_end"]), rmax)
        sv = r.get("associated_off_ball_run_subtype")
        if pd.isna(sv):
            sv = r.get("event_subtype")
        runsub[(raw >= a) & (raw <= b)] = "" if pd.isna(sv) else str(sv)
    d["OffBallRun_subtype"] = runsub
    shotty = ev[ev["xshot_player_possession_max"].notna() & (ev["xshot_player_possession_max"] > 0)]
    d["Is_shot_moment"] = frames_of(shotty).astype(int)
    pc = ev[ev.get("pressing_chain", False) == True]
    d["Pressing_chain_active"] = frames_of(pc).astype(int)
    pdng = ev[ev.get("possession_danger", False) == True]
    d["possession_danger_active"] = frames_of(pdng).astype(int)

    d = d.drop(columns=["_raw_frame"])
    d.to_csv(args.out, index=False, encoding="utf-8")
    print(f"列数: {d.shape[1]}  行数: {d.shape[0]}")
    print(f"保存 -> {args.out}")
    # カバレッジ
    flags = ["Pass_event_flag", "Is_engagement_moment", "Is_off_ball_run_active",
             "Is_shot_moment", "Pressing_chain_active"]
    print("イベント結合カバレッジ:", {f: int(d[f].sum()) for f in flags})


if __name__ == "__main__":
    main()
