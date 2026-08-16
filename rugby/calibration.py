"""
rugby/calibration.py
====================
映像のピクセル座標 ↔ ピッチ座標（メートル）を結ぶホモグラフィの推定・保存・適用。

上空からの映像は平面（ピッチ）を平面（画像）に射影しているので、両者は
3x3 ホモグラフィ行列で厳密に対応づけられる。ユーザーが映像上でピッチライン
の交点（ランドマーク）を 4 点以上クリックすれば H が一意に決まる。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

import cv2
import numpy as np

from .pitch_model import PitchSpec, PRESETS, landmark_index, pitch_line_index


MIN_POINTS = 4


# ── ホモグラフィ本体 ──────────────────────────────────────────────────────────

@dataclass
class Calibration:
    """画像 → ピッチ の対応づけ一式。"""

    H: np.ndarray                    # 3x3  画像ピクセル → ピッチ座標(m)
    spec: PitchSpec
    image_points: list[tuple[float, float]]
    pitch_points: list[tuple[float, float]]
    landmark_keys: list[str]
    frame_size: tuple[int, int]      # (width, height)
    reproj_error_m: float
    # クリックしたフレームの時刻。手ブレ補正はこのフレームを基準に揃える必要が
    # ある（別のフレームを基準にすると、その時点のブレ量ぶん座標が丸ごとずれる）。
    ref_time_sec: float | None = None

    @property
    def H_inv(self) -> np.ndarray:
        """ピッチ座標(m) → 画像ピクセル。"""
        return np.linalg.inv(self.H)

    # ── 変換 ──
    def to_pitch(self, pts_px: np.ndarray) -> np.ndarray:
        """画像ピクセル (N,2) → ピッチ座標メートル (N,2)。"""
        return _apply_h(self.H, pts_px)

    def to_image(self, pts_m: np.ndarray) -> np.ndarray:
        """ピッチ座標メートル (N,2) → 画像ピクセル (N,2)。"""
        return _apply_h(self.H_inv, pts_m)

    def meters_per_pixel(self, pt_px: tuple[float, float]) -> float:
        """指定ピクセル位置における局所スケール（m/px）。

        選手サイズによる検出フィルタを画面内の位置に応じて変えるために使う。
        上空からの映像でも周辺部ほど 1px が示す実距離は大きくなる。
        """
        x, y = pt_px
        base = _apply_h(self.H, np.array([[x, y]], float))[0]
        dx = _apply_h(self.H, np.array([[x + 1.0, y]], float))[0]
        dy = _apply_h(self.H, np.array([[x, y + 1.0]], float))[0]
        sx = float(np.hypot(*(dx - base)))
        sy = float(np.hypot(*(dy - base)))
        return float((sx + sy) / 2.0)

    # ── 永続化 ──
    def to_dict(self) -> dict:
        d = asdict(self)
        d["H"] = self.H.tolist()
        d["spec"] = {
            "name": self.spec.name,
            "length": self.spec.length,
            "width": self.spec.width,
            "in_goal": self.spec.in_goal,
            "n_players": self.spec.n_players,
        }
        return d

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: str | Path) -> "Calibration":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        s = d["spec"]
        spec = PRESETS.get(s["name"]) or PitchSpec(
            s["name"], s["length"], s["width"], s["in_goal"], s["n_players"]
        )
        return cls(
            H=np.array(d["H"], float),
            spec=spec,
            image_points=[tuple(p) for p in d["image_points"]],
            pitch_points=[tuple(p) for p in d["pitch_points"]],
            landmark_keys=list(d["landmark_keys"]),
            frame_size=tuple(d["frame_size"]),
            reproj_error_m=float(d["reproj_error_m"]),
            ref_time_sec=d.get("ref_time_sec"),
        )


def _apply_h(H: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """同次座標でホモグラフィを適用。pts は (N,2)。"""
    pts = np.asarray(pts, dtype=float).reshape(-1, 2)
    if len(pts) == 0:
        return pts
    ones = np.ones((len(pts), 1))
    hom = np.hstack([pts, ones]) @ H.T
    w = hom[:, 2:3]
    # 無限遠（地平線越え）は NaN にして下流で除外させる
    w = np.where(np.abs(w) < 1e-9, np.nan, w)
    return hom[:, :2] / w


def calibrate(
    image_points: list[tuple[float, float]],
    landmark_keys: list[str],
    spec: PitchSpec,
    frame_size: tuple[int, int],
    ref_time_sec: float | None = None,
) -> Calibration:
    """クリックされた画像点とランドマーク名から Calibration を構築する。

    `ref_time_sec` にはクリックしたフレームの時刻を渡す。手ブレ補正を使う際、
    このフレームへ揃えないと座標が系統的にずれる。

    Raises
    ------
    ValueError : 点が 4 未満、または対応が取れない（縮退した配置）場合。
    """
    if len(image_points) != len(landmark_keys):
        raise ValueError("画像点とランドマークの数が一致していません。")
    if len(image_points) < MIN_POINTS:
        raise ValueError(f"キャリブレーションには最低 {MIN_POINTS} 点が必要です。")

    idx = landmark_index(spec)
    missing = [k for k in landmark_keys if k not in idx]
    if missing:
        raise ValueError(f"未知のランドマーク: {missing}")

    src = np.array(image_points, dtype=np.float32)
    dst = np.array([[idx[k].x, idx[k].y] for k in landmark_keys], dtype=np.float32)

    if len(src) == MIN_POINTS:
        H = cv2.getPerspectiveTransform(src, dst)
    else:
        # 5 点以上なら RANSAC で外れ値（クリックミス）を吸収
        H, _ = cv2.findHomography(src, dst, cv2.RANSAC, ransacReprojThreshold=1.5)

    if H is None or not np.all(np.isfinite(H)):
        raise ValueError(
            "ホモグラフィを計算できませんでした。"
            "4 点が同一直線上に並んでいないか確認してください。"
        )

    proj = _apply_h(H, src.astype(float))
    err = float(np.nanmean(np.linalg.norm(proj - dst.astype(float), axis=1)))

    return Calibration(
        H=np.asarray(H, dtype=float),
        spec=spec,
        image_points=[tuple(map(float, p)) for p in image_points],
        pitch_points=[(float(idx[k].x), float(idx[k].y)) for k in landmark_keys],
        landmark_keys=list(landmark_keys),
        frame_size=tuple(frame_size),
        reproj_error_m=err,
        ref_time_sec=ref_time_sec,
    )


# ── 線を引くキャリブレーション ────────────────────────────────────────────────

def line_intersection(
    a: tuple[float, float], b: tuple[float, float],
    c: tuple[float, float], d: tuple[float, float],
) -> tuple[float, float] | None:
    """線分 ab と cd を含む直線どうしの交点。平行なら None。

    線分の内部で交わる必要はない（画面外に交点があってもよい）。
    """
    x1, y1 = a
    x2, y2 = b
    x3, y3 = c
    x4, y4 = d
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-9:
        return None
    t1 = x1 * y2 - y1 * x2
    t2 = x3 * y4 - y3 * x4
    return ((t1 * (x3 - x4) - (x1 - x2) * t2) / den,
            (t1 * (y3 - y4) - (y1 - y2) * t2) / den)


def calibrate_from_lines(
    drawn: dict[str, tuple[tuple[float, float], tuple[float, float]]],
    spec: PitchSpec,
    frame_size: tuple[int, int],
    ref_time_sec: float | None = None,
) -> Calibration:
    """なぞったピッチラインの交点からホモグラフィを求める。

    点を 1 つずつクリックするより精度が出やすい。線は長く取れるので、
    数ピクセルのずれが向きに与える影響が小さく、交点は 2 本の線全体の情報から
    決まるため。隅が画面外・オクルージョンで見えない場合にも使える。

    Parameters
    ----------
    drawn : {ライン名: ((x1, y1), (x2, y2))} なぞった線分の画像座標。
        縦断（axis="x"）2 本以上・横断（axis="y"）2 本以上が必要。

    Raises
    ------
    ValueError : 本数が足りない、または交点が 4 点に満たない場合。
    """
    idx = pitch_line_index(spec)
    unknown = [k for k in drawn if k not in idx]
    if unknown:
        raise ValueError(f"未知のライン: {unknown}")

    xs = {k: v for k, v in drawn.items() if idx[k].axis == "x"}
    ys = {k: v for k, v in drawn.items() if idx[k].axis == "y"}
    if len(xs) < 2 or len(ys) < 2:
        raise ValueError(
            "縦断ライン（ゴールライン・22m など）2 本以上と、"
            "横断ライン（タッチラインなど）2 本以上をなぞってください。"
            f"現在: 縦断 {len(xs)} 本 / 横断 {len(ys)} 本"
        )

    img_pts: list[tuple[float, float]] = []
    pitch_pts: list[tuple[float, float]] = []
    for kx, (a, b) in xs.items():
        for ky, (c, d) in ys.items():
            p = line_intersection(a, b, c, d)
            if p is None:
                continue
            img_pts.append(p)
            pitch_pts.append((idx[kx].value, idx[ky].value))

    if len(img_pts) < MIN_POINTS:
        raise ValueError(
            "交点を 4 つ作れませんでした。線が平行になっていないか確認してください。"
        )

    src = np.array(img_pts, dtype=np.float32)
    dst = np.array(pitch_pts, dtype=np.float32)

    if len(src) == MIN_POINTS:
        H = cv2.getPerspectiveTransform(src, dst)
    else:
        H, _ = cv2.findHomography(src, dst, cv2.RANSAC, ransacReprojThreshold=1.5)

    if H is None or not np.all(np.isfinite(H)):
        raise ValueError(
            "ホモグラフィを計算できませんでした。なぞった線の向きを確認してください。"
        )

    proj = _apply_h(H, src.astype(float))
    err = float(np.nanmean(np.linalg.norm(proj - dst.astype(float), axis=1)))

    return Calibration(
        H=np.asarray(H, dtype=float),
        spec=spec,
        image_points=[tuple(map(float, p)) for p in img_pts],
        pitch_points=[tuple(map(float, p)) for p in pitch_pts],
        landmark_keys=[f"{kx}×{ky}" for kx in xs for ky in ys],
        frame_size=tuple(frame_size),
        reproj_error_m=err,
        ref_time_sec=ref_time_sec,
    )


def order_quad(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """4 点を「左上 → 右上 → 右下 → 左下」の順に並べ替える（画像座標系）。

    重心まわりの偏角で環状に並べてから、左上に最も近い点を先頭へ回す。
    画像座標は Y が下向きなので、時計回りになるよう向きを揃える。
    """
    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    if len(pts) != 4:
        raise ValueError(f"4 点必要です（現在 {len(pts)} 点）。")

    c = pts.mean(axis=0)
    ang = np.arctan2(pts[:, 1] - c[1], pts[:, 0] - c[0])
    ring = pts[np.argsort(ang)]

    start = int(np.argmin(ring[:, 0] + ring[:, 1]))       # 左上に最も近い点
    ring = np.roll(ring, -start, axis=0)

    # ring[0] の両隣が「右上」と「左下」。どちら回りに並んだかは環状ソートの
    # 向きだけでは決まらないので、辺の向きで判定する。右上へ向かう辺は横長、
    # 左下へ向かう辺は縦長になる。
    v_next = ring[1] - ring[0]
    v_prev = ring[3] - ring[0]
    horiz_next = abs(v_next[0]) - abs(v_next[1])
    horiz_prev = abs(v_prev[0]) - abs(v_prev[1])
    if horiz_prev > horiz_next:                           # 逆回りなので折り返す
        ring = ring[[0, 3, 2, 1]]

    return [tuple(map(float, p)) for p in ring]


def quad_from_enclosing_lines(
    segments: list[tuple[tuple[float, float], tuple[float, float]]],
) -> list[tuple[float, float]]:
    """ピッチを囲む 4 本の線分から、4 隅（交点）を求める。

    どの線がどのラインかを指定させる必要はない。画像上の傾きから縦向き 2 本・
    横向き 2 本に振り分け、その交点を取れば四隅が決まる。
    """
    if len(segments) != 4:
        raise ValueError(f"線は 4 本引いてください（現在 {len(segments)} 本）。")

    vert, horiz = [], []
    for s in segments:
        (x1, y1), (x2, y2) = s
        (vert if abs(x2 - x1) < abs(y2 - y1) else horiz).append(s)

    if len(vert) != 2 or len(horiz) != 2:
        raise ValueError(
            "縦向き 2 本・横向き 2 本になるように囲んでください。"
            f"（現在 縦 {len(vert)} 本 / 横 {len(horiz)} 本）"
        )

    pts = []
    for v in vert:
        for h in horiz:
            p = line_intersection(v[0], v[1], h[0], h[1])
            if p is None:
                raise ValueError("線が平行で交点を作れません。囲む形に引いてください。")
            pts.append(p)

    return order_quad(pts)


def calibrate_from_quad(
    corners: list[tuple[float, float]],
    spec: PitchSpec,
    frame_size: tuple[int, int],
    include_in_goal: bool = True,
    flip_x: bool = False,
    flip_y: bool = False,
    ref_time_sec: float | None = None,
) -> Calibration:
    """ピッチ外周の 4 隅からホモグラフィを求める（最も簡単な方式）。

    ラインの名前を一切指定しなくてよい。囲んだ範囲がピッチのどこかだけを
    `include_in_goal` で選ぶ。

    Parameters
    ----------
    corners : 画像座標の 4 隅。順不同でよい（内部で並べ替える）。
    include_in_goal :
        True  … デッドボールラインまで含めた外周を囲んだ場合
        False … ゴールライン（トライライン）間を囲んだ場合
        サッカー（in_goal=0）ではどちらでも同じ。
    flip_x, flip_y :
        復元したピッチの向きが実際と逆だったときに反転させる。
        画像の左右・上下がピッチのどちら向きかはカメラ設置次第で決まらないため、
        重ね描きを見て合わない場合に切り替える。
    """
    ordered = order_quad(corners)                          # 左上→右上→右下→左下

    x0 = spec.x_min if include_in_goal else 0.0
    x1 = spec.x_max if include_in_goal else spec.length
    y0, y1 = 0.0, spec.width
    if flip_x:
        x0, x1 = x1, x0
    if flip_y:
        y0, y1 = y1, y0

    dst_pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

    src = np.array(ordered, dtype=np.float32)
    dst = np.array(dst_pts, dtype=np.float32)
    H = cv2.getPerspectiveTransform(src, dst)

    if H is None or not np.all(np.isfinite(H)):
        raise ValueError(
            "ホモグラフィを計算できませんでした。4 隅が潰れていないか確認してください。"
        )

    proj = _apply_h(H, src.astype(float))
    err = float(np.nanmean(np.linalg.norm(proj - dst.astype(float), axis=1)))

    return Calibration(
        H=np.asarray(H, dtype=float),
        spec=spec,
        image_points=[tuple(map(float, p)) for p in ordered],
        pitch_points=[tuple(map(float, p)) for p in dst_pts],
        landmark_keys=["左上", "右上", "右下", "左下"],
        frame_size=tuple(frame_size),
        reproj_error_m=err,
        ref_time_sec=ref_time_sec,
    )


# ── 補助: ピッチ枠を画像上に描く ──────────────────────────────────────────────

def draw_pitch_overlay(
    frame: np.ndarray, calib: Calibration, color=(0, 255, 255), thickness: int = 2
) -> np.ndarray:
    """キャリブレーション結果の目視確認用に、ピッチラインを映像へ重ねる。"""
    from .pitch_model import pitch_lines

    out = frame.copy()
    h, w = out.shape[:2]

    for kind, verts in pitch_lines(calib.spec):
        pts = calib.to_image(np.array(verts, dtype=float))
        if not np.all(np.isfinite(pts)):
            continue
        pts_i = pts.astype(np.int32)
        # 画面から大きく外れる線は描かない（射影の破綻を目立たせない）
        if np.any(np.abs(pts_i) > 10 * max(h, w)):
            continue
        if kind == "solid":
            cv2.polylines(out, [pts_i], False, color, thickness, cv2.LINE_AA)
        else:
            for a, b in zip(pts_i[:-1], pts_i[1:]):
                _dashed_line(out, tuple(a), tuple(b), color, thickness)

    for (px, py) in calib.image_points:
        cv2.circle(out, (int(px), int(py)), 6, (0, 0, 255), -1, cv2.LINE_AA)
        cv2.circle(out, (int(px), int(py)), 6, (255, 255, 255), 1, cv2.LINE_AA)

    return out


def _dashed_line(img, p1, p2, color, thickness, dash: int = 12) -> None:
    p1a, p2a = np.array(p1, float), np.array(p2, float)
    dist = float(np.linalg.norm(p2a - p1a))
    if dist < 1e-6:
        return
    n = max(int(dist / dash), 1)
    for i in range(0, n, 2):
        a = p1a + (p2a - p1a) * (i / n)
        b = p1a + (p2a - p1a) * (min(i + 1, n) / n)
        cv2.line(img, tuple(a.astype(int)), tuple(b.astype(int)), color, thickness, cv2.LINE_AA)
