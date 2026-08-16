"""
rugby/pipeline.py
=================
動画 → 位置情報の時系列（DataFrame）への変換オーケストレーター。

長い試合映像から任意の 30 秒窓だけを切り出して処理できる。GSA が
「1 試合 1 シーン」単位で解析する前提に合わせた設計。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
import pandas as pd

from .calibration import Calibration
from .detection import BackgroundDetector, Stabilizer, build_detector
from .tracking import BallTracker, MultiObjectTracker, TrackState


ProgressFn = Callable[[float, str], None]


# ── 動画メタ情報 ──────────────────────────────────────────────────────────────

@dataclass
class VideoInfo:
    path: str
    fps: float
    n_frames: int
    width: int
    height: int

    @property
    def duration_sec(self) -> float:
        return self.n_frames / self.fps if self.fps > 0 else 0.0


def probe_video(path: str | Path) -> VideoInfo:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise FileNotFoundError(f"動画を開けません: {path}")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 25.0
        info = VideoInfo(
            path=str(path),
            fps=fps,
            n_frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
            width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )
    finally:
        cap.release()
    return info


def grab_frame(path: str | Path, at_sec: float) -> np.ndarray:
    """指定秒のフレームを 1 枚取得する（キャリブレーション画面用）。"""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise FileNotFoundError(f"動画を開けません: {path}")
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(at_sec, 0.0) * 1000.0)
        ok, frame = cap.read()
        if not ok:
            raise ValueError(f"{at_sec:.1f} 秒のフレームを取得できませんでした。")
        return frame
    finally:
        cap.release()


# ── 本処理 ────────────────────────────────────────────────────────────────────

def process_window(
    video_path: str | Path,
    calib: Calibration,
    start_sec: float = 0.0,
    duration_sec: float = 30.0,
    stride: int = 1,
    backend: str = "bgsub",
    stabilize: bool = False,
    warmup_sec: float = 4.0,
    max_predict_frames: int = 2,
    min_track_seconds: float = 1.0,
    smooth_positions: int = 0,
    tracker_kw: dict | None = None,
    progress: ProgressFn | None = None,
    **detector_kw,
) -> pd.DataFrame:
    """指定した時間窓を解析し、長形式の位置情報 DataFrame を返す。

    Parameters
    ----------
    stride    : 何フレームおきに処理するか。2 なら実効フレームレートが半分。
    backend   : "bgsub"（背景差分・依存少）/ "yolo" / "auto"
    stabilize : ドローン等でカメラが動く場合 True。
    warmup_sec: 背景モデルの事前学習に使う、窓の直前の秒数。
    max_predict_frames :
        検出が無いフレームで、カルマン予測だけの位置を何フレームまで出力するか。
        大きくすると穴は埋まるが、実際には見えていない位置を出すことになる。
        既定 2（短い遮蔽のみ補間し、それ以上は素直に欠測にする）。
    min_track_seconds :
        この秒数より短命なトラックを出力から除く。背景モデルが安定するまでの
        誤検出や、密集の分割ミスで生まれる一瞬のトラックを落とすための下限。
        0 で無効。
    smooth_positions :
        出力座標に Savitzky-Golay フィルタをかける窓（奇数フレーム, 5〜11 推奨）。
        検出枠の微小なブレ（ジッター）を均す。0 で無効。
        カルマンで既に平滑化されているため既定は 0。生の検出が荒い実写映像で
        効かせる想定。
    tracker_kw :
        MultiObjectTracker へ渡す調整値。映像の画質に応じて
        `{"meas_noise_m": 0.08, "process_accel": 15.0}` のように追従性を上げると
        位置精度が改善することがある。

    Returns
    -------
    columns = [frame, video_frame, time_sec, kind, track_id, team, jersey,
               x_m, y_m, x_norm, y_norm, speed_mps, status, carrier_id]
    """
    info = probe_video(video_path)
    dt = stride / info.fps

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"動画を開けません: {video_path}")

    try:
        # ── 基準フレーム（手ブレ補正の基準）──
        # キャリブレーションを取ったフレームへ揃える。解析窓の先頭フレームを
        # 基準にすると、そのフレーム自体のブレ量ぶん座標が丸ごとオフセットする
        # （検証では 6px のブレで 0.7m の系統誤差になった）。
        ref = None
        if stabilize and calib.ref_time_sec is not None:
            try:
                ref = grab_frame(video_path, calib.ref_time_sec)
            except Exception:
                ref = None
        if ref is None:
            cap.set(cv2.CAP_PROP_POS_MSEC, start_sec * 1000.0)
            ok, ref = cap.read()
            if not ok:
                raise ValueError(f"{start_sec:.1f} 秒から読み出せませんでした。")
        stab = Stabilizer(ref, enabled=stabilize)

        detector = (
            BackgroundDetector(calib, **detector_kw)
            if backend == "bgsub"
            else build_detector(calib, backend, **detector_kw)
        )

        # ── 背景モデルの事前学習（窓の手前を使う） ──
        if isinstance(detector, BackgroundDetector) and warmup_sec > 0:
            wstart = max(start_sec - warmup_sec, 0.0)
            cap.set(cv2.CAP_PROP_POS_MSEC, wstart * 1000.0)
            n_warm = int(warmup_sec * info.fps / max(stride, 1))
            warm = []
            for _ in range(n_warm):
                for _ in range(stride):
                    ok, f = cap.read()
                    if not ok:
                        break
                if not ok:
                    break
                warm.append(stab.align(f))
            if warm:
                detector.warmup(warm)
                if progress:
                    progress(0.05, f"背景モデルを学習しました（{len(warm)} フレーム）")

        # ── チーム色の学習（窓の先頭を一度なめる） ──
        tracker = MultiObjectTracker(dt=dt, **(tracker_kw or {}))
        cap.set(cv2.CAP_PROP_POS_MSEC, start_sec * 1000.0)
        n_total = max(int(duration_sec * info.fps / max(stride, 1)), 1)
        n_probe = min(n_total, int(3.0 * info.fps / max(stride, 1)))

        for _ in range(n_probe):
            for _ in range(stride):
                ok, f = cap.read()
                if not ok:
                    break
            if not ok:
                break
            tracker.teams.collect(detector.detect(stab.align(f)))
        tracker.teams.fit()
        if progress:
            progress(0.15, "チーム色を判別しました")

        # ── 本番パス ──
        # 背景差分は上の探索で状態が進んでいるので作り直して同条件に揃える
        if isinstance(detector, BackgroundDetector):
            detector = BackgroundDetector(calib, **detector_kw)
            if warmup_sec > 0 and warm:
                detector.warmup(warm)

        ball = BallTracker(dt=dt)
        cap.set(cv2.CAP_PROP_POS_MSEC, start_sec * 1000.0)

        rows: list[dict] = []
        start_frame = int(round(start_sec * info.fps))

        for i in range(n_total):
            ok = True
            for _ in range(stride):
                ok, f = cap.read()
                if not ok:
                    break
            if not ok:
                break

            frame = stab.align(f)
            dets = detector.detect(frame)
            tracks = tracker.step(dets)
            bstate = ball.step(dets, tracks)

            t_sec = i * dt
            vframe = start_frame + i * stride

            for tr in tracks:
                if tr.time_since_update > max_predict_frames:
                    continue                     # 見えていない位置は捏造しない
                x, y = tr.pitch_xy
                nx, ny = calib.spec.normalize(x, y)
                rows.append(dict(
                    frame=i + 1, video_frame=vframe, time_sec=round(t_sec, 3),
                    kind="player", track_id=tr.track_id,
                    team=tr.team, jersey=tr.jersey,
                    x_m=round(x, 3), y_m=round(y, 3),
                    x_norm=round(nx, 5), y_norm=round(ny, 5),
                    speed_mps=round(tr.kf.speed, 3),
                    status=tr.state.value, carrier_id=None,
                ))

            if bstate.pitch_x is not None:
                nx, ny = calib.spec.normalize(bstate.pitch_x, bstate.pitch_y)
                rows.append(dict(
                    frame=i + 1, video_frame=vframe, time_sec=round(t_sec, 3),
                    kind="ball", track_id=0, team=None, jersey=None,
                    x_m=round(bstate.pitch_x, 3), y_m=round(bstate.pitch_y, 3),
                    x_norm=round(nx, 5), y_norm=round(ny, 5),
                    speed_mps=None,
                    status=bstate.status, carrier_id=bstate.carrier_id,
                ))

            if progress and (i % 10 == 0 or i == n_total - 1):
                progress(0.15 + 0.85 * (i + 1) / n_total,
                         f"解析中 {i + 1}/{n_total} フレーム / 検出 {len(tracks)} 人")

    finally:
        cap.release()

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    if smooth_positions and smooth_positions >= 3:
        df = _smooth_positions(df, calib.spec, smooth_positions)

    df = _recompute_speed(df, dt)

    # 短命トラック（誤検出由来）を落とす。ボール行は対象外。
    if min_track_seconds > 0:
        min_frames = max(int(min_track_seconds / dt), 1)
        pl = df[df["kind"] == "player"]
        keep = pl["track_id"].value_counts()
        keep = set(keep[keep >= min_frames].index)
        df = df[(df["kind"] != "player") | df["track_id"].isin(keep)]

    return df.sort_values(["frame", "kind", "track_id"]).reset_index(drop=True)


# ── 速度の再計算 ──────────────────────────────────────────────────────────────

SPEED_SMOOTH_FRAMES = 5        # 平滑窓（フレーム）


def _smooth_positions(df: pd.DataFrame, spec, window: int) -> pd.DataFrame:
    """トラックごとに X/Y へ Savitzky-Golay フィルタをかける。

    移動平均と違い 2 次多項式で当てるため、加速・減速の山を潰さずに高周波の
    ジッターだけを落とせる。正規化座標も併せて振り直す。
    """
    from scipy.signal import savgol_filter

    out = df.copy()
    w = window if window % 2 == 1 else window + 1

    for _, g in out[out["kind"] == "player"].groupby("track_id", sort=False):
        if len(g) < 3:
            continue
        idx = g.sort_values("frame").index
        ww = min(w, len(idx) if len(idx) % 2 == 1 else len(idx) - 1)
        if ww < 3:
            continue
        for col in ("x_m", "y_m"):
            out.loc[idx, col] = savgol_filter(
                out.loc[idx, col].to_numpy(float), ww, polyorder=2
            ).round(3)

    is_p = out["kind"] == "player"
    nx, ny = zip(*[spec.normalize(x, y) for x, y in
                   zip(out.loc[is_p, "x_m"], out.loc[is_p, "y_m"])]) \
        if is_p.any() else ((), ())
    if is_p.any():
        out.loc[is_p, "x_norm"] = np.round(nx, 5)
        out.loc[is_p, "y_norm"] = np.round(ny, 5)
    return out


def _recompute_speed(df: pd.DataFrame, dt: float,
                     window: int = SPEED_SMOOTH_FRAMES) -> pd.DataFrame:
    """出力位置の平滑微分から速度を求め直す。

    カルマンの速度状態は、位置追従を優先すると必然的にノイジーになる
    （観測を強く信じる＝1 フレームの検出揺れがそのまま速度に乗る）。
    位置と速度で求められる平滑度が違うので、速度だけ別に均す。

    窓は既定 5 フレーム（25fps で 0.2 秒）。GSA で読みたい因果ラグより
    十分短く保つこと（平滑窓がラグを超えるとラグ構造が消える）。
    """
    from .tracking import MAX_PLAYER_SPEED

    out = df.copy()
    out["speed_mps"] = np.nan

    for tid, g in out[out["kind"] == "player"].groupby("track_id"):
        g = g.sort_values("frame")
        idx = g.index
        f = g["frame"].to_numpy()

        # 欠測フレームを挟んでも実時間で微分できるよう、フレーム番号を使う
        xs = g["x_m"].rolling(window, center=True, min_periods=1).mean().to_numpy()
        ys = g["y_m"].rolling(window, center=True, min_periods=1).mean().to_numpy()

        if len(f) < 2:
            out.loc[idx, "speed_mps"] = 0.0
            continue

        # 中心差分（端は片側差分）
        dx = np.gradient(xs, f * dt)
        dy = np.gradient(ys, f * dt)
        sp = np.hypot(dx, dy)
        out.loc[idx, "speed_mps"] = np.clip(sp, 0.0, MAX_PLAYER_SPEED).round(3)

    return out


# ── 追跡品質のサマリ ──────────────────────────────────────────────────────────

def track_summary(df: pd.DataFrame, spec_players: int = 15) -> pd.DataFrame:
    """トラックごとの出現状況。ID 取り違えや断片化の発見に使う。"""
    if df.empty:
        return pd.DataFrame()
    p = df[df["kind"] == "player"]
    n_frames = int(p["frame"].max())
    g = p.groupby("track_id").agg(
        出現フレーム数=("frame", "count"),
        開始フレーム=("frame", "min"),
        終了フレーム=("frame", "max"),
        チーム=("team", lambda s: s.dropna().mode().iloc[0] if s.notna().any() else None),
        背番号=("jersey", lambda s: s.dropna().iloc[0] if s.notna().any() else None),
        平均速度=("speed_mps", "mean"),
        最高速度=("speed_mps", "max"),
    ).reset_index()
    g["カバー率"] = (g["出現フレーム数"] / n_frames).round(3)
    g["平均速度"] = g["平均速度"].round(2)
    g["最高速度"] = g["最高速度"].round(2)
    return g.sort_values("出現フレーム数", ascending=False).reset_index(drop=True)
