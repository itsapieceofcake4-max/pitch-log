"""
rugby/validate.py
=================
合成映像（正解座標つき）でパイプライン全体の精度を測る。

測る指標
--------
- **検出率**       正解選手のうち、何割が各フレームで追跡できていたか
- **位置誤差**     復元したピッチ座標と正解の距離（メートル）
- **ID 一貫性**    1 人の正解選手が、いくつの track_id に分裂したか

    python -m rugby.validate --video synth.mp4 --gt synth.groundtruth.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

from .calibration import calibrate
from .pitch_model import RUGBY_UNION_15, PitchSpec, landmark_index
from .pipeline import probe_video, process_window
from .make_synthetic import camera_homography, _project


# 映像に必ず写る 4 隅。実運用でユーザーがクリックする点に相当。
DEFAULT_KEYS = [
    "goal_l__touch_bot", "goal_r__touch_bot",
    "goal_r__touch_top", "goal_l__touch_top",
]


def build_calibration_from_camera(
    spec: PitchSpec, size: tuple[int, int], perspective: float, keys: list[str] | None = None
):
    """既知のカメラ行列からランドマークを逆算し、ユーザーのクリックを模擬する。"""
    keys = keys or DEFAULT_KEYS
    H_cam = camera_homography(spec, size, perspective)
    idx = landmark_index(spec)
    pitch_pts = np.array([[idx[k].x, idx[k].y] for k in keys], float)
    img_pts = _project(H_cam, pitch_pts)
    return calibrate([tuple(p) for p in img_pts], keys, spec, size, ref_time_sec=0.0)


def evaluate(pred: pd.DataFrame, gt: pd.DataFrame, max_match_m: float = 4.0) -> dict:
    """フレームごとに予測と正解を対応づけ、精度指標を集計する。"""
    p = pred[pred["kind"] == "player"]
    g = gt[gt["kind"] == "player"]

    frames = sorted(set(p["frame"]) & set(g["frame"]))
    errors: list[float] = []
    n_gt = n_matched = 0
    gt_to_tracks: dict[int, set[int]] = {}
    gt_track_counts: dict[int, dict[int, int]] = {}

    for f in frames:
        pf = p[p["frame"] == f]
        gf = g[g["frame"] == f]
        n_gt += len(gf)
        if pf.empty or gf.empty:
            continue

        P = pf[["x_m", "y_m"]].to_numpy(float)
        G = gf[["x_m", "y_m"]].to_numpy(float)
        D = np.linalg.norm(P[:, None, :] - G[None, :, :], axis=2)

        rows, cols = linear_sum_assignment(D)
        for r, c in zip(rows, cols):
            if D[r, c] > max_match_m:
                continue
            errors.append(float(D[r, c]))
            n_matched += 1
            gid = int(gf.iloc[c]["gt_id"])
            tid = int(pf.iloc[r]["track_id"])
            gt_to_tracks.setdefault(gid, set()).add(tid)
            gt_track_counts.setdefault(gid, {})
            gt_track_counts[gid][tid] = gt_track_counts[gid].get(tid, 0) + 1

    frag = [len(v) for v in gt_to_tracks.values()]
    err = np.array(errors) if errors else np.array([np.nan])

    # 支配トラック被覆率: 1 人の選手を「単一の ID」でどれだけ追い切れたか。
    # 実運用での手直し量に直結する指標（1.0 なら手直し不要）。
    cover = [max(c.values()) / sum(c.values()) for c in gt_track_counts.values()]

    return {
        "評価フレーム数": len(frames),
        "検出率": round(n_matched / n_gt, 3) if n_gt else 0.0,
        "位置誤差_平均m": round(float(np.nanmean(err)), 3),
        "位置誤差_中央値m": round(float(np.nanmedian(err)), 3),
        "位置誤差_90%tile_m": round(float(np.nanpercentile(err, 90)), 3),
        "追跡できた正解選手数": len(gt_to_tracks),
        "支配track被覆率_平均": round(float(np.mean(cover)), 3) if cover else 0.0,
        "支配track被覆率_最小": round(float(np.min(cover)), 3) if cover else 0.0,
        "1人あたり平均track数": round(float(np.mean(frag)), 2) if frag else 0.0,
        "予測track総数": int(p["track_id"].nunique()),
    }


def main() -> None:
    # Windows の既定コンソール(cp932)でも日本語ログで落ちないようにする
    import io
    import sys

    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="合成映像でパイプライン精度を検証する")
    ap.add_argument("--video", required=True)
    ap.add_argument("--gt", required=True)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--duration", type=float, default=10.0)
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--perspective", type=float, default=0.10)
    ap.add_argument("--backend", default="bgsub")
    args = ap.parse_args()

    info = probe_video(args.video)
    spec = RUGBY_UNION_15
    calib = build_calibration_from_camera(spec, (info.width, info.height), args.perspective)
    print(f"キャリブレーション再投影誤差: {calib.reproj_error_m:.4f} m")

    pred = process_window(
        args.video, calib,
        start_sec=args.start, duration_sec=args.duration,
        stride=args.stride, backend=args.backend,
        progress=lambda f, m: print(f"  [{f*100:5.1f}%] {m}", end="\r"),
    )
    print()

    gt = pd.read_csv(args.gt)
    # 正解を、処理した窓・stride に合わせて切り出す
    f0 = int(round(args.start * info.fps))
    n = int(args.duration * info.fps / max(args.stride, 1))
    sel = [f0 + i * args.stride + 1 for i in range(n)]
    gt = gt[gt["frame"].isin(sel)].copy()
    gt["frame"] = gt["frame"].map({v: i + 1 for i, v in enumerate(sel)})

    print("\n── 精度 ──")
    for k, v in evaluate(pred, gt).items():
        print(f"  {k:24s} {v}")


if __name__ == "__main__":
    main()
