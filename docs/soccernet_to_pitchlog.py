# -*- coding: utf-8 -*-
r"""
soccernet_to_pitchlog.py
========================
SoccerNet GSR (gamestate) の Labels-GameState.json を
Pitch Log で扱える長形式トラッキングCSVへ変換する。

座標系:
  GSR bbox_pitch は「足元(bottom_middle)・メートル・ピッチ中心原点(105x68)」。
  Pitch Log の phase_xt と同じ系なので x_m/y_m はそのまま流せる。
  正規化は x_norm=(x_m+52.5)/105, y_norm=(y_m+34)/68 を 0..1 にclip。

出力列:
  clip, frame, time_s, role, team, jersey, track_id, x_m, y_m, x_norm, y_norm
  role: player/goalkeeper/referee/ball  ／ team: home(=left)/away(=right)/空(ball等)

使い方:
  # 1クリップ
  python soccernet_to_pitchlog.py --src C:\soccernet\gamestate-2024\SNGS-116
  # gamestate ルート配下を一括（各クリップごとに CSV 出力）
  python soccernet_to_pitchlog.py --src C:\soccernet\gamestate-2024 --out C:\soccernet\pitchlog_csv
  # 全クリップを1ファイルに連結
  python soccernet_to_pitchlog.py --src C:\soccernet\gamestate-2024 --combine all_tracking.csv
"""
import argparse
import csv
import json
import os

PITCH_L, PITCH_W = 105.0, 68.0
KEEP_ROLES = {"player", "goalkeeper", "referee", "ball"}
TEAM_MAP = {"left": "home", "right": "away"}


def clip01(v):
    return 0.0 if v < 0 else 1.0 if v > 1 else v


def convert_sequence(seq_dir, fps=25.0):
    """1シーケンスを行リスト（dict）に変換して返す。"""
    jpath = os.path.join(seq_dir, "Labels-GameState.json")
    with open(jpath, encoding="utf-8") as f:
        d = json.load(f)
    clip = d.get("info", {}).get("name") or os.path.basename(seq_dir)
    # image_id -> frame番号（file_name の数字）
    frame_of = {}
    for im in d["images"]:
        try:
            frame_of[im["image_id"]] = int(os.path.splitext(im["file_name"])[0])
        except (KeyError, ValueError):
            pass
    rows = []
    for a in d["annotations"]:
        at = a.get("attributes") or {}
        role = at.get("role")
        if role not in KEEP_ROLES:
            continue
        bp = a.get("bbox_pitch")
        if not bp or bp.get("x_bottom_middle") is None:
            continue
        x_m = float(bp["x_bottom_middle"]); y_m = float(bp["y_bottom_middle"])
        frame = frame_of.get(a["image_id"])
        if frame is None:
            continue
        rows.append({
            "clip": clip,
            "frame": frame,
            "time_s": round((frame - 1) / fps, 3),
            "role": role,
            "team": TEAM_MAP.get(at.get("team"), ""),
            "jersey": at.get("jersey") or "",
            "track_id": a.get("track_id", ""),
            "x_m": round(x_m, 3),
            "y_m": round(y_m, 3),
            "x_norm": round(clip01((x_m + PITCH_L / 2) / PITCH_L), 4),
            "y_norm": round(clip01((y_m + PITCH_W / 2) / PITCH_W), 4),
        })
    rows.sort(key=lambda r: (r["frame"], r["team"], str(r["jersey"])))
    return clip, rows


FIELDS = ["clip", "frame", "time_s", "role", "team", "jersey",
          "track_id", "x_m", "y_m", "x_norm", "y_norm"]


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader(); w.writerows(rows)


def find_sequences(src):
    if os.path.exists(os.path.join(src, "Labels-GameState.json")):
        return [src]
    return [os.path.join(src, d) for d in sorted(os.listdir(src))
            if os.path.isdir(os.path.join(src, d))
            and os.path.exists(os.path.join(src, d, "Labels-GameState.json"))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="シーケンスdir または gamestateルート")
    ap.add_argument("--out", help="クリップ別CSVの出力先（既定: 各シーケンスdir内）")
    ap.add_argument("--combine", help="全クリップを連結する1ファイルのパス")
    ap.add_argument("--fps", type=float, default=25.0)
    args = ap.parse_args()

    seqs = find_sequences(args.src)
    if not seqs:
        print("Labels-GameState.json が見つかりません。"); return
    if args.out:
        os.makedirs(args.out, exist_ok=True)

    combined = []
    for sd in seqs:
        clip, rows = convert_sequence(sd, fps=args.fps)
        if args.combine:
            combined += rows
        else:
            outp = (os.path.join(args.out, f"{clip}_tracking.csv") if args.out
                    else os.path.join(sd, f"{clip}_tracking.csv"))
            write_csv(outp, rows)
            print(f"{clip}: {len(rows)} 行 -> {outp}")
    if args.combine:
        write_csv(args.combine, combined)
        print(f"{len(seqs)} クリップ / {len(combined)} 行 -> {args.combine}")


if __name__ == "__main__":
    main()
