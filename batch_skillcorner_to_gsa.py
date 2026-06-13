# -*- coding: utf-8 -*-
r"""
batch_skillcorner_to_gsa.py
===========================
SkillCorner Open Data（10試合）→ GSA入力（Export_GSA形式）を一括生成する PoC バッチ。

各試合の各ゴールについて、ゴール直前30秒(300frame@10fps)の窓を切り出し、
xt_pipeline_22 の処理（GridID/ZoneID/xT付与・整形・ライン突破パス検出）を通して
Export_GSA_<match>_<period>_<mmss>.csv を出力する。

設計メモ:
  - 結合: tracking の player_id == match.json の players[].id（実証済み 22/22）。
  - 座標: メートル・ピッチ中心原点。pitch_length/width で 0..1 正規化。
  - 攻撃方向: home_team_side[period] が 'right_to_left' の期間は x を反転し、
             Home が常に x=1 方向へ攻めるよう向き付け（xt_pipeline の前提に合わせる）。
  - 欠損: 放送由来のため未検出/未出現はそのまま NaN（pipeline が許容）。

使い方:
  python batch_skillcorner_to_gsa.py --src C:\skillcorner_opendata\data\matches --out C:\skillcorner_gsa
  python batch_skillcorner_to_gsa.py --src ... --out ... --match 1925299   # 1試合だけ
"""
import argparse
import json
import os
import numpy as np
import pandas as pd

import xt_pipeline_22 as xp  # 同じ Export_GSA 契約を再利用

FPS = 10
WINDOW_SEC = 30
WINDOW_FRAMES = FPS * WINDOW_SEC  # 300


def load_match(match_dir, mid):
    with open(os.path.join(match_dir, f"{mid}_match.json"), encoding="utf-8") as f:
        m = json.load(f)
    home_id, away_id = m["home_team"]["id"], m["away_team"]["id"]
    pid_map = {p["id"]: (p["team_id"], p["number"]) for p in m["players"]
               if p.get("id") is not None and p.get("number") is not None}
    L = float(m.get("pitch_length") or 105.0)
    W = float(m.get("pitch_width") or 68.0)
    # home_team_side: [period1, period2] の攻撃方向
    side = m.get("home_team_side") or ["left_to_right", "right_to_left"]
    flip_period = {i + 1: (s == "right_to_left") for i, s in enumerate(side)}
    return dict(m=m, home_id=home_id, away_id=away_id, pid_map=pid_map,
                L=L, W=W, flip_period=flip_period,
                name=f"{m['home_team'].get('name')} {m.get('home_team_score')}-"
                     f"{m.get('away_team_score')} {m['away_team'].get('name')}")


def goal_frames(match_dir, mid):
    """得点本体のフレームを返す。連続する lead_to_goal フェーズ（同一保持チーム）は
    1得点に畳み込み、その最後の frame_end を採用する（build_match_phases と同方式）。"""
    ph = pd.read_csv(os.path.join(match_dir, f"{mid}_phases_of_play.csv"))
    if "index" in ph.columns:
        ph = ph.sort_values("index").reset_index(drop=True)
    flag = ph["team_possession_lead_to_goal"].astype(str).str.lower().isin(["true", "1"]).to_numpy()
    team = ph["team_in_possession_id"].to_numpy()
    out, n = [], len(ph)
    for i in range(n):
        if flag[i] and (i + 1 >= n or not (flag[i + 1] and team[i + 1] == team[i])):
            out.append((int(ph.loc[i, "frame_end"]), int(ph.loc[i, "period"])))
    return out


def collect_windows(match_dir, mid, goals, info):
    """tracking を1パスで読み、各ゴール窓のフレームを Sample 形式行へ。"""
    needed = {}  # frame -> goal_index
    spans = []
    for gi, (gf, period) in enumerate(goals):
        start = gf - WINDOW_FRAMES + 1
        spans.append((gi, gf, period, start))
        for fr in range(start, gf + 1):
            needed[fr] = gi
    buckets = {gi: [] for gi in range(len(goals))}
    home_id, away_id = info["home_id"], info["away_id"]
    pid_map, L, W = info["pid_map"], info["L"], info["W"]
    flip_period = info["flip_period"]

    path = os.path.join(match_dir, f"{mid}_tracking_extrapolated.jsonl")
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            rec = json.loads(line)
            fr = rec.get("frame")
            if fr not in needed:
                continue
            gi = needed[fr]
            period = rec.get("period") or spans[gi][2]
            flip = flip_period.get(period, False)
            sgn = -1.0 if flip else 1.0

            def nx(x):
                return (sgn * x + L / 2) / L if x is not None else np.nan

            def ny(y):
                return (y + W / 2) / W if y is not None else np.nan

            b = rec.get("ball_data") or {}
            grp = (rec.get("possession") or {}).get("group")
            poss = "H" if grp == "home" else ("A" if grp == "away" else "")
            row = {"frame_id": fr, "ball_x": nx(b.get("x")), "ball_y": ny(b.get("y")),
                   "is_goal_frame": 1 if fr == spans[gi][1] else 0, "ball_possession": poss}
            for p in rec.get("player_data") or []:
                pid = p.get("player_id")
                tm = pid_map.get(pid)
                if tm is None:
                    continue
                tid, num = tm
                pre = "home" if tid == home_id else ("away" if tid == away_id else None)
                if pre is None:
                    continue
                row[f"{pre}_{num}_x"] = nx(p.get("x"))
                row[f"{pre}_{num}_y"] = ny(p.get("y"))
            buckets[gi].append(row)
    return buckets, spans


def to_sample_df(rows):
    """Sample_TrackingData_22 互換（Home_1..11 / Away_1..11 をスロット割当）。"""
    df = pd.DataFrame(rows).sort_values("frame_id").reset_index(drop=True)
    df["frame"] = range(1, len(df) + 1)
    df["time_sec"] = (df["frame_id"] - df["frame_id"].iloc[0]) / FPS
    out = df[["frame", "time_sec", "ball_x", "ball_y", "is_goal_frame", "ball_possession"]].copy()
    for pre, Pre in (("home", "Home"), ("away", "Away")):
        jerseys = sorted({int(c.split("_")[1]) for c in df.columns
                          if c.startswith(f"{pre}_") and c.endswith("_x")})
        for slot, j in enumerate(jerseys[:11], start=1):
            out[f"{Pre}_{slot}_x"] = df.get(f"{pre}_{j}_x")
            out[f"{Pre}_{slot}_y"] = df.get(f"{pre}_{j}_y")
        for slot in range(min(len(jerseys), 11) + 1, 12):
            out[f"{Pre}_{slot}_x"] = np.nan
            out[f"{Pre}_{slot}_y"] = np.nan
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="matches ルート")
    ap.add_argument("--out", required=True, help="Export_GSA 出力先")
    ap.add_argument("--match", help="特定 match_id だけ処理")
    args = ap.parse_args()

    xt_map = xp.load_xt_map(xp.XT_MAP_CSV)
    os.makedirs(args.out, exist_ok=True)
    mids = [args.match] if args.match else sorted(
        d for d in os.listdir(args.src) if os.path.isdir(os.path.join(args.src, d)))

    total = 0
    for mid in mids:
        md = os.path.join(args.src, mid)
        info = load_match(md, mid)
        goals = goal_frames(md, mid)
        print(f"[{mid}] {info['name']} | goals={len(goals)}")
        if not goals:
            continue
        buckets, spans = collect_windows(md, mid, goals, info)
        for gi, gf, period, start in spans:
            rows = buckets[gi]
            if len(rows) < 10:
                print(f"   goal{gi}: frames {len(rows)} 不足、スキップ")
                continue
            sample = to_sample_df(rows)
            enriched = xp.assign_grid_and_xt_22(sample, xt_map)
            result = xp.reformat_to_22player_schema(enriched, FPS, float(sample["time_sec"].iloc[0]))
            # LBP検出は全 Int64 列を float64 化したコピーで実行
            # （Int64 NA が行抽出で pd.NA になり xt_pipeline の float() で落ちるのを回避）。
            tmp = result.copy()
            for c in tmp.columns:
                if str(tmp[c].dtype) == "Int64":
                    tmp[c] = tmp[c].astype("float64")
            tmp = xp.add_zone_and_lbp_columns(tmp, FPS)
            for c in ("is_line_breaking_pass", "lbp_passer", "lbp_receiver", "lbp_nearby_def_count"):
                result[c] = tmp[c].values
            mmss = f"{(gf // FPS) // 60:02d}{(gf // FPS) % 60:02d}"
            outp = os.path.join(args.out, f"Export_GSA_{mid}_P{period}_{mmss}.csv")
            result.to_csv(outp, index=False)
            print(f"   goal{gi} P{period} f{gf}: {result.shape[0]}行 -> {os.path.basename(outp)}")
            total += 1
    print(f"\n完了: {total} 窓を Export_GSA 形式で出力 -> {args.out}")


if __name__ == "__main__":
    main()
