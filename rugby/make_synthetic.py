"""
rugby/make_synthetic.py
=======================
検証用の合成「上空映像」を生成する。

正解の座標が既知なので、検出・追跡・座標復元の精度を数値で測れる。
実際のラグビー部の映像が届く前に、パイプラインの健全性を確認するために使う。

    python -m rugby.make_synthetic --out C:\\tmp\\synth.mp4 --seconds 20
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from .pitch_model import RUGBY_UNION_15, PitchSpec, pitch_lines


TEAM_COLORS = [(60, 60, 210), (210, 120, 50)]     # BGR: 赤系 / 青系
BALL_COLOR = (30, 200, 240)


def camera_homography(spec: PitchSpec, size: tuple[int, int], perspective: float = 0.10):
    """ピッチ座標(m) → 画像ピクセル の射影行列を作る（仮想の高所カメラ）。

    perspective=0 で真上からの平行投影、値を上げるほど手前が広がる台形になる。
    """
    W, H = size
    mx, my = W * 0.05, H * 0.10
    x0, x1 = spec.x_min, spec.x_max
    y0, y1 = 0.0, spec.width

    src = np.float32([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
    shrink = perspective * (W - 2 * mx) * 0.5
    dst = np.float32([
        [mx + shrink, my],
        [W - mx - shrink, my],
        [W - mx, H - my],
        [mx, H - my],
    ])
    return cv2.getPerspectiveTransform(src, dst)


def _project(H: np.ndarray, pts: np.ndarray) -> np.ndarray:
    pts = np.asarray(pts, float).reshape(-1, 2)
    hom = np.hstack([pts, np.ones((len(pts), 1))]) @ H.T
    return hom[:, :2] / hom[:, 2:3]


def _crossing_trajectories(spec: PitchSpec, n: int, seconds: float, fps: float, rng,
                           speed: float = 5.0) -> np.ndarray:
    """左右から向かい合って直進させ、中央で密に交錯させる軌跡。

    追跡器にとって最悪の条件（同時に多数の重なりが起きる）を作るためのモード。
    実映像のスクラム・ラック・密集に近い負荷をかけられる。
    """
    T = int(seconds * fps)
    out = np.zeros((n, T, 2), float)
    t = np.arange(T) / fps

    for i in range(n):
        # 半数を左→右、半数を右→左に。レーンをずらして正面衝突は避ける。
        rightward = (i % 2 == 0)
        y0 = 4 + (spec.width - 8) * ((i // 2) / max(n // 2 - 1, 1))
        y0 += rng.uniform(-1.5, 1.5)
        x0 = rng.uniform(2, 12) if rightward else rng.uniform(spec.length - 12, spec.length - 2)
        v = speed * rng.uniform(0.75, 1.25) * (1 if rightward else -1)

        x = x0 + v * t
        # 端で折り返して常にピッチ内に居続けさせる
        span = spec.length - 4
        x = 2 + np.abs((x - 2) % (2 * span) - span)
        # 横方向はゆっくり蛇行させ、交錯の当たり方を毎回変える
        y = y0 + 3.0 * np.sin(2 * np.pi * t / rng.uniform(4.0, 8.0) + rng.uniform(0, 6.28))
        out[i, :, 0] = np.clip(x, 2, spec.length - 2)
        out[i, :, 1] = np.clip(y, 2, spec.width - 2)

    return out


def _trajectories(spec: PitchSpec, n: int, seconds: float, fps: float, rng,
                  max_speed: float = 7.0) -> np.ndarray:
    """(n, T, 2) の滑らかな軌跡を作る。

    ウェイポイントをピッチ全域から一様に選ぶと、区間距離が数十メートルになり
    選手が 30 m/s で移動する非現実的な軌跡になる。実際のラグビーは最大でも
    10 m/s 程度なので、1 区間の移動量を `max_speed × 区間秒数` で制限する。
    """
    T = int(seconds * fps)
    interval = 2.5                                  # ウェイポイント間隔（秒）
    n_way = max(int(seconds / interval), 3)
    step_max = max_speed * interval * 0.7           # 直線移動でない分を割り引く
    out = np.zeros((n, T, 2), float)

    for i in range(n):
        wx = np.empty(n_way)
        wy = np.empty(n_way)
        wx[0] = rng.uniform(5, spec.length - 5)
        wy[0] = rng.uniform(4, spec.width - 4)
        for k in range(1, n_way):
            ang = rng.uniform(0, 2 * np.pi)
            r = rng.uniform(0.2, 1.0) * step_max
            wx[k] = np.clip(wx[k - 1] + r * np.cos(ang), 3, spec.length - 3)
            wy[k] = np.clip(wy[k - 1] + r * np.sin(ang), 3, spec.width - 3)
        t_way = np.linspace(0, T - 1, n_way)
        t_all = np.arange(T)
        # 3 次補間相当の滑らかさを線形補間 + 移動平均で近似
        x = np.interp(t_all, t_way, wx)
        y = np.interp(t_all, t_way, wy)
        k = max(int(fps * 0.8), 3)
        ker = np.ones(k) / k
        x = np.convolve(np.pad(x, (k, k), mode="edge"), ker, "same")[k:-k]
        y = np.convolve(np.pad(y, (k, k), mode="edge"), ker, "same")[k:-k]
        out[i, :, 0], out[i, :, 1] = x, y

    return out


def generate(
    out_path: str | Path,
    seconds: float = 20.0,
    fps: float = 25.0,
    size: tuple[int, int] = (1280, 720),
    spec: PitchSpec = RUGBY_UNION_15,
    perspective: float = 0.10,
    noise: float = 4.0,
    seed: int = 7,
    n_per_team: int | None = None,
    motion: str = "random",
    shake_px: float = 0.0,
) -> tuple[Path, pd.DataFrame, np.ndarray]:
    """合成映像と正解座標を生成する。

    Parameters
    ----------
    n_per_team : 1 チームの人数（既定は spec の規定人数）
    motion     : "random"（ランダムウォーク）/ "crossing"（左右から直進して密に交錯）
    shake_px   : カメラの揺れ幅（px）。手ブレ補正の検証用。0 で固定カメラ。

    Returns
    -------
    (動画パス, 正解 DataFrame, カメラ行列 H)
    """
    rng = np.random.default_rng(seed)
    W, H_px = size
    H = camera_homography(spec, size, perspective)
    T = int(seconds * fps)

    n_per_team = n_per_team or spec.n_players
    n_total = n_per_team * 2
    players = (_crossing_trajectories(spec, n_total, seconds, fps, rng)
               if motion == "crossing"
               else _trajectories(spec, n_total, seconds, fps, rng))
    ball = _trajectories(spec, 1, seconds, fps, rng)[0]

    # 背景（芝 + ライン）を 1 枚作って使い回す
    bg = np.full((H_px, W, 3), (40, 105, 45), np.uint8)
    grass = rng.normal(0, 6, (H_px, W, 1)).astype(np.int16)
    bg = np.clip(bg.astype(np.int16) + grass, 0, 255).astype(np.uint8)
    for kind, verts in pitch_lines(spec):
        pts = _project(H, np.array(verts, float)).astype(np.int32)
        if kind == "solid":
            cv2.polylines(bg, [pts], False, (235, 235, 235), 2, cv2.LINE_AA)
        else:
            for a, b in zip(pts[:-1], pts[1:]):
                d = np.linalg.norm(b - a)
                for s in range(0, int(d / 14), 2):
                    p = a + (b - a) * (s * 14 / d)
                    q = a + (b - a) * (min((s + 1) * 14, d) / d)
                    cv2.line(bg, tuple(p.astype(int)), tuple(q.astype(int)),
                             (235, 235, 235), 2, cv2.LINE_AA)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"mp4v"),
                             fps, (W, H_px))
    if not writer.isOpened():
        raise RuntimeError("VideoWriter を開けませんでした（コーデック不足の可能性）")

    rows: list[dict] = []
    try:
        for t in range(T):
            frame = bg.copy()
            if noise > 0:
                frame = np.clip(
                    frame.astype(np.int16) + rng.normal(0, noise, frame.shape).astype(np.int16),
                    0, 255,
                ).astype(np.uint8)

            # 手ブレ（背景ごと平行移動させる）。選手も同じ量だけずらして整合を保つ。
            # t=0 でブレ 0 になるようにしてある。キャリブレーションを取るフレーム
            # がピッチ座標系の基準になるため、そこを揺れの無い状態に置く。
            if shake_px > 0:
                dx = shake_px * np.sin(2 * np.pi * t / (fps * 3.1))
                dy = shake_px * np.sin(2 * np.pi * t / (fps * 4.7))
                M = np.float32([[1, 0, dx], [0, 1, dy]])
                frame = cv2.warpAffine(frame, M, (W, H_px), borderMode=cv2.BORDER_REFLECT)
            else:
                dx = dy = 0.0

            # 選手を描く。奥（画面上）から順に描いて重なりを自然に見せる。
            order = np.argsort(-players[:, t, 1])
            for i in order:
                team = 0 if i < n_per_team else 1
                px, py = players[i, t]
                ix, iy = _project(H, np.array([[px, py]]))[0]
                ix, iy = ix + dx, iy + dy
                # 局所スケールから選手の見かけ半径(px)を求める
                nx, ny = _project(H, np.array([[px + 0.45, py]]))[0]
                r = max(int(abs(nx - ix + dx)), 3)
                cv2.circle(frame, (int(ix), int(iy)), r, TEAM_COLORS[team], -1, cv2.LINE_AA)
                cv2.circle(frame, (int(ix), int(iy)), r, (245, 245, 245), 1, cv2.LINE_AA)

                rows.append(dict(
                    frame=t + 1, time_sec=round(t / fps, 3), kind="player",
                    gt_id=int(i) + 1, team=team,
                    x_m=round(float(px), 3), y_m=round(float(py), 3),
                    img_x=round(float(ix), 2), img_y=round(float(iy), 2),
                ))

            bx, by = ball[t]
            ibx, iby = _project(H, np.array([[bx, by]]))[0]
            ibx, iby = ibx + dx, iby + dy
            nbx, _ = _project(H, np.array([[bx + 0.16, by]]))[0]
            br = max(int(abs(nbx - ibx)), 2)
            cv2.circle(frame, (int(ibx), int(iby)), br, BALL_COLOR, -1, cv2.LINE_AA)
            rows.append(dict(
                frame=t + 1, time_sec=round(t / fps, 3), kind="ball",
                gt_id=0, team=None,
                x_m=round(float(bx), 3), y_m=round(float(by), 3),
                img_x=round(float(ibx), 2), img_y=round(float(iby), 2),
            ))

            writer.write(frame)
    finally:
        writer.release()

    return out_path, pd.DataFrame(rows), H


def main() -> None:
    ap = argparse.ArgumentParser(description="検証用の合成上空映像を生成する")
    ap.add_argument("--out", required=True, help="出力 mp4 パス")
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--fps", type=float, default=25.0)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--perspective", type=float, default=0.10,
                    help="0=真上, 大きいほど斜め")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--players", type=int, default=None, help="1チームの人数")
    ap.add_argument("--motion", default="random", choices=["random", "crossing"],
                    help="crossing=左右から直進して密に交錯（過酷条件）")
    ap.add_argument("--shake", type=float, default=0.0, help="手ブレ幅(px)")
    args = ap.parse_args()

    path, gt, _ = generate(
        args.out, seconds=args.seconds, fps=args.fps,
        size=(args.width, args.height), perspective=args.perspective, seed=args.seed,
        n_per_team=args.players, motion=args.motion, shake_px=args.shake,
    )
    gt_path = Path(args.out).with_suffix(".groundtruth.csv")
    gt.to_csv(gt_path, index=False, encoding="utf-8-sig")
    print(f"動画     : {path}")
    print(f"正解座標 : {gt_path}  ({len(gt)} 行)")


if __name__ == "__main__":
    main()
