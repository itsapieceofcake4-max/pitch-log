"""
rugby/animate.py
================
モジュール2: 2Dピッチアニメーション（タクティカルボード風 MP4）の生成。

トラッキング CSV を読み込み、縮尺の正確な 2D ピッチ図の上に選手をプロットして
動画として書き出す。抽出データが正しいかの目視確認（デバッグ）と、戦術分析用の
「2Dマップ映像」の両方に使う。

描画は matplotlib ではなく OpenCV で行う。1 フレームごとに figure を作り直す
matplotlib は数百フレームで極端に遅くなるのに対し、OpenCV は背景画像を一度だけ
作って使い回せるため 1 桁速い（仕様書の推奨に沿う）。

    python -m rugby.animate --csv tracks_long.csv --out tactical.mp4 --fps 25
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from .pitch_model import PRESETS, PitchSpec, RUGBY_UNION_15, pitch_lines


def _bgr(hex_color: str) -> tuple[int, int, int]:
    """#RRGGBB → OpenCV の BGR タプル。アプリと同じ配色を使うための変換。"""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return (b, g, r)


# アプリ本体（rugby/theme.py）と同じパレットを使い、画面と書き出しの見た目を揃える
from .theme import COLORS as _C, turf_stripes                     # noqa: E402

COLOR_BG = _bgr(_C["bg"])
COLOR_TURF_D = _bgr(_C["turf_dark"])
COLOR_TURF_L = _bgr(_C["turf_light"])
COLOR_LINE = _bgr(_C["pitch_line"])
COLOR_TEAM = {0: _bgr(_C["team_a"]), 1: _bgr(_C["team_b"])}
COLOR_UNKNOWN = _bgr(_C["unknown"])
COLOR_BALL = _bgr(_C["ball"])
COLOR_TEXT = _bgr(_C["text"])
COLOR_ACCENT = _bgr(_C["accent"])
COLOR_MUTED = _bgr(_C["text_muted"])


class PitchRenderer:
    """ピッチ座標(m) → 画像ピクセル の変換と、背景ピッチ図の生成。"""

    def __init__(self, spec: PitchSpec, width_px: int = 1280, margin_m: float = 4.0,
                 include_in_goal: bool = True):
        self.spec = spec
        self.margin = margin_m
        x0 = (spec.x_min if include_in_goal else 0.0) - margin_m
        x1 = (spec.x_max if include_in_goal else spec.length) + margin_m
        y0, y1 = -margin_m, spec.width + margin_m

        self.x0, self.y0 = x0, y0
        self.scale = width_px / (x1 - x0)                  # px per meter
        self.w = width_px
        self.h = int(round((y1 - y0) * self.scale))
        self.background = self._draw_background()

    def to_px(self, x_m, y_m):
        """ピッチ座標 → 画像座標。Y は上下反転（画像は下向きが正）。"""
        px = (np.asarray(x_m, float) - self.x0) * self.scale
        py = self.h - (np.asarray(y_m, float) - self.y0) * self.scale
        return px, py

    def _draw_background(self) -> np.ndarray:
        # ピッチ外の余白は UI と同じ暗色にして、ピッチ面だけを浮かび上がらせる
        img = np.full((self.h, self.w, 3), COLOR_BG, np.uint8)
        x0p, y0p = self.to_px(self.spec.x_min, self.spec.width)
        x1p, y1p = self.to_px(self.spec.x_max, 0.0)

        # 芝の刈り込みストライプ（アプリ画面と同じ定義を共有）
        for xa, xb, light in turf_stripes(self.spec.x_min, self.spec.x_max):
            pa, _ = self.to_px(xa, 0)
            pb, _ = self.to_px(xb, 0)
            cv2.rectangle(img, (int(pa), int(y0p)), (int(pb), int(y1p)),
                          COLOR_TURF_L if light else COLOR_TURF_D, -1)

        # ピッチ面のふちを一段暗く落として、面の輪郭を締める
        cv2.rectangle(img, (int(x0p), int(y0p)), (int(x1p), int(y1p)),
                      tuple(int(c * 0.55) for c in COLOR_TURF_D), 2, cv2.LINE_AA)

        # ライン：白を少し透過させてシャープだが硬すぎない印象にする
        lines = img.copy()
        for kind, verts in pitch_lines(self.spec):
            pts = np.array([self.to_px(x, y) for x, y in verts]).T.reshape(-1, 2)
            pts_i = pts.astype(np.int32)
            if kind == "solid":
                cv2.polylines(lines, [pts_i], False, COLOR_LINE, 2, cv2.LINE_AA)
            else:
                for a, b in zip(pts_i[:-1], pts_i[1:]):
                    _dashed(lines, tuple(a), tuple(b), COLOR_LINE, 2)
        return cv2.addWeighted(lines, 0.78, img, 0.22, 0)


def _draw_hud(img: np.ndarray, t_sec: float, frame_no: int, n_players: int) -> None:
    """左上に時刻・フレーム・検出人数を表示する情報バー。"""
    h, w = img.shape[:2]
    pad = 12
    bar = img[0:44, 0:w].copy()
    cv2.rectangle(bar, (0, 0), (w, 44), COLOR_BG, -1)
    img[0:44, 0:w] = cv2.addWeighted(bar, 0.72, img[0:44, 0:w], 0.28, 0)

    cv2.line(img, (pad, 12), (pad + 3, 32), COLOR_ACCENT, 3, cv2.LINE_AA)
    cv2.putText(img, "PITCH LOG", (pad + 12, 27),
                cv2.FONT_HERSHEY_DUPLEX, 0.52, COLOR_TEXT, 1, cv2.LINE_AA)
    cv2.putText(img, f"{t_sec:6.2f}s", (pad + 130, 27),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLOR_ACCENT, 1, cv2.LINE_AA)
    cv2.putText(img, f"frame {frame_no}   |   {n_players} tracked",
                (pad + 230, 27),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOR_MUTED, 1, cv2.LINE_AA)


def _dashed(img, p1, p2, color, thickness, dash_px: int = 14) -> None:
    a, b = np.array(p1, float), np.array(p2, float)
    dist = float(np.linalg.norm(b - a))
    if dist < 1e-6:
        return
    n = max(int(dist / dash_px), 1)
    for i in range(0, n, 2):
        s = a + (b - a) * (i / n)
        e = a + (b - a) * (min(i + 1, n) / n)
        cv2.line(img, tuple(s.astype(int)), tuple(e.astype(int)), color, thickness, cv2.LINE_AA)


def render_animation(
    df: pd.DataFrame,
    out_path: str | Path,
    spec: PitchSpec = RUGBY_UNION_15,
    fps: float = 25.0,
    width_px: int = 1280,
    trail_frames: int = 30,
    show_voronoi: bool = False,
    voronoi_alpha: float = 0.25,
    show_ids: bool = True,
    progress=None,
) -> Path:
    """トラッキング長形式データから MP4 を書き出す。

    Parameters
    ----------
    trail_frames : 軌跡（テール）として残す過去フレーム数。0 で無効。
    show_voronoi : ボロノイ図（モジュール5）を背景レイヤーに重ねる。
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rend = PitchRenderer(spec, width_px)
    frames = sorted(df["frame"].unique())
    if not frames:
        raise ValueError("フレームがありません。")

    writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"mp4v"),
                             fps, (rend.w, rend.h))
    if not writer.isOpened():
        raise RuntimeError("VideoWriter を開けませんでした（コーデック不足の可能性）")

    players = df[df["kind"] == "player"] if "kind" in df.columns else df
    balls = df[df["kind"] == "ball"] if "kind" in df.columns else df.iloc[0:0]

    # 軌跡描画のため、track_id ごとに frame→座標 を引ける形にしておく
    by_frame = {f: g for f, g in players.groupby("frame")}
    hist: dict[int, list[tuple[float, float]]] = {}

    if show_voronoi:
        from .voronoi import cells_for_frame

    try:
        for n, f in enumerate(frames):
            img = rend.background.copy()
            g = by_frame.get(f)

            if g is not None and show_voronoi:
                cells = cells_for_frame(g, spec)
                if cells:
                    layer = img.copy()
                    for c in cells:
                        px, py = rend.to_px(c.polygon[:, 0], c.polygon[:, 1])
                        poly = np.column_stack([px, py]).astype(np.int32)
                        cv2.fillPoly(layer, [poly],
                                     COLOR_TEAM.get(c.team, COLOR_UNKNOWN))
                    img = cv2.addWeighted(layer, voronoi_alpha, img, 1 - voronoi_alpha, 0)
                    # 境界は極細に。塗りが主張しすぎないよう線で輪郭だけ拾う。
                    for c in cells:
                        px, py = rend.to_px(c.polygon[:, 0], c.polygon[:, 1])
                        poly = np.column_stack([px, py]).astype(np.int32)
                        cv2.polylines(img, [poly], True,
                                      COLOR_TEAM.get(c.team, COLOR_UNKNOWN),
                                      1, cv2.LINE_AA)
                    # 塗りつぶしで沈むピッチラインを描き直す
                    for kind, verts in pitch_lines(spec):
                        pts = np.array([rend.to_px(x, y) for x, y in verts]).T.reshape(-1, 2)
                        if kind == "solid":
                            cv2.polylines(img, [pts.astype(np.int32)], False,
                                          COLOR_LINE, 1, cv2.LINE_AA)

            if g is not None:
                # 軌跡
                if trail_frames > 0:
                    for _, r in g.iterrows():
                        tid = int(r["track_id"])
                        hist.setdefault(tid, []).append((float(r["x_m"]), float(r["y_m"])))
                        if len(hist[tid]) > trail_frames:
                            hist[tid] = hist[tid][-trail_frames:]
                    for _, r in g.iterrows():
                        tid = int(r["track_id"])
                        pts = hist.get(tid, [])
                        if len(pts) < 2:
                            continue
                        team = r["team"]
                        color = COLOR_TEAM.get(int(team), COLOR_UNKNOWN) \
                            if pd.notna(team) else COLOR_UNKNOWN
                        arr = np.array(pts, float)
                        px, py = rend.to_px(arr[:, 0], arr[:, 1])
                        tail = np.column_stack([px, py]).astype(np.int32)
                        cv2.polylines(img, [tail], False,
                                      tuple(int(c * 0.65) for c in color), 2, cv2.LINE_AA)

                # 影 → ドットの順に描き、ピッチから浮いた立体感を出す
                shadow = img.copy()
                for _, r in g.iterrows():
                    px, py = rend.to_px(r["x_m"], r["y_m"])
                    cv2.circle(shadow, (int(px) + 2, int(py) + 3), 12, (0, 0, 0),
                               -1, cv2.LINE_AA)
                img = cv2.addWeighted(shadow, 0.34, img, 0.66, 0)

                for _, r in g.iterrows():
                    team = r["team"]
                    color = COLOR_TEAM.get(int(team), COLOR_UNKNOWN) \
                        if pd.notna(team) else COLOR_UNKNOWN
                    px, py = rend.to_px(r["x_m"], r["y_m"])
                    c = (int(px), int(py))
                    cv2.circle(img, c, 11, color, -1, cv2.LINE_AA)
                    cv2.circle(img, c, 11, COLOR_BG, 2, cv2.LINE_AA)
                    if show_ids:
                        label = str(r.get("jersey") or int(r["track_id"]))
                        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_DUPLEX,
                                                      0.34, 1)
                        cv2.putText(img, label, (c[0] - tw // 2, c[1] + th // 2),
                                    cv2.FONT_HERSHEY_DUPLEX, 0.34, COLOR_BG, 1,
                                    cv2.LINE_AA)

            b = balls[balls["frame"] == f] if len(balls) else None
            if b is not None and not b.empty:
                for _, r in b.iterrows():
                    if pd.isna(r["x_m"]):
                        continue
                    px, py = rend.to_px(r["x_m"], r["y_m"])
                    cv2.circle(img, (int(px), int(py)), 7, COLOR_BALL, -1, cv2.LINE_AA)
                    cv2.circle(img, (int(px), int(py)), 7, (0, 0, 0), 1, cv2.LINE_AA)

            t_sec = (float(g["time_sec"].iloc[0])
                     if g is not None and "time_sec" in g.columns else n / fps)
            _draw_hud(img, t_sec, int(f), len(g) if g is not None else 0)

            writer.write(img)
            if progress and (n % 20 == 0 or n == len(frames) - 1):
                progress((n + 1) / len(frames), f"描画中 {n + 1}/{len(frames)}")
    finally:
        writer.release()

    return out_path


def main() -> None:
    import io
    import sys

    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="トラッキングCSVから2Dピッチ動画を生成する")
    ap.add_argument("--csv", required=True, help="長形式のトラッキングCSV")
    ap.add_argument("--out", required=True, help="出力 mp4")
    ap.add_argument("--fps", type=float, default=25.0)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--trail", type=int, default=30, help="軌跡フレーム数（0で無効）")
    ap.add_argument("--voronoi", action="store_true", help="ボロノイ図を重ねる")
    ap.add_argument("--preset", default=RUGBY_UNION_15.name, choices=list(PRESETS))
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    if "kind" not in df.columns:
        df["kind"] = "player"
    p = render_animation(
        df, args.out, PRESETS[args.preset], fps=args.fps, width_px=args.width,
        trail_frames=args.trail, show_voronoi=args.voronoi,
        progress=lambda f, m: print(f"  [{f*100:5.1f}%] {m}", end="\r"),
    )
    print(f"\n出力: {p}")


if __name__ == "__main__":
    main()
