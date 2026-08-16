"""
rugby/detection.py
==================
上空映像から「動く点」（選手・ボール）をフレーム単位で検出する。

方式
----
1. **手ブレ補正**   ドローン等でカメラが動く場合、基準フレームへ ORB 特徴で
   射影補正する。以降の検出座標はすべて「基準フレーム座標系」で扱うため、
   キャリブレーションのホモグラフィをそのまま適用できる。
2. **背景差分**     固定俯瞰カメラでは MOG2 背景差分が最も安定して動体を拾う。
3. **ピッチ基準サイズフィルタ**  ホモグラフィから局所スケール(m/px)が分かるので、
   「実寸で何メートルの塊か」で選手／ボールを判別する。画面内の位置によって
   ピクセル面積が変わっても、実寸基準なら閾値が一定でよい。

`ultralytics` が入っていれば YOLO バックエンドも使える（任意）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .calibration import Calibration


# ── 検出結果 ──────────────────────────────────────────────────────────────────

@dataclass
class Detection:
    """1 フレーム内の 1 検出。座標は基準フレームのピクセル系。"""

    cx: float
    cy: float
    bbox: tuple[int, int, int, int]      # x, y, w, h
    pitch_x: float                       # メートル
    pitch_y: float
    area_m2: float                       # 実寸換算の面積
    hist: np.ndarray | None = None       # 見た目特徴（HSV ヒストグラム）
    kind: str = "player"                 # "player" | "ball"
    score: float = 1.0


# ── 手ブレ補正 ────────────────────────────────────────────────────────────────

class Stabilizer:
    """基準フレームに対する射影変換を推定して、カメラの揺れを打ち消す。

    固定カメラなら `enabled=False` でスキップできる（処理が約 2 倍速くなる）。
    """

    def __init__(self, reference: np.ndarray, enabled: bool = True, max_features: int = 1200):
        self.enabled = enabled
        self.ref_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
        self.orb = cv2.ORB_create(max_features)
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        self.ref_kp, self.ref_des = self.orb.detectAndCompute(self.ref_gray, None)
        self.size = (reference.shape[1], reference.shape[0])

    def align(self, frame: np.ndarray) -> np.ndarray:
        """frame を基準フレームの見え方へ補正して返す。失敗時は原フレーム。"""
        if not self.enabled or self.ref_des is None:
            return frame
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        kp, des = self.orb.detectAndCompute(gray, None)
        if des is None or len(des) < 10:
            return frame
        matches = self.matcher.match(des, self.ref_des)
        if len(matches) < 10:
            return frame
        matches = sorted(matches, key=lambda m: m.distance)[:200]
        src = np.float32([kp[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
        dst = np.float32([self.ref_kp[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
        H, _ = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
        if H is None:
            return frame
        return cv2.warpPerspective(frame, H, self.size, flags=cv2.INTER_LINEAR)


# ── 背景差分ベースの検出器 ────────────────────────────────────────────────────

class BackgroundDetector:
    """MOG2 背景差分 + 実寸サイズフィルタによる選手／ボール検出。

    Parameters
    ----------
    player_size_m : 選手 1 人が占める実寸の目安（直径 m）。俯瞰では肩幅〜0.8m 程度。
    ball_size_m   : ボールの実寸（長径 0.3m 程度）。
    detect_ball   : ボール検出を試みるか。**既定 False**。

    ボール検出について（重要）
    -------------------------
    上空映像でのボールは十数ピクセル以下しかなく、背景差分では芝のノイズと
    大きさで区別できない。合成映像での検証では、拾えた候補の位置誤差が
    中央値 15m 超と実用にならなかった。誤った座標を出すと下流の分析を壊すため
    既定では無効にしてある。ボール位置が必要な場合は
      - `backend="yolo"`（sports ball クラス）を高解像度映像に対して使う
      - もしくは手動アノテーション
    を検討すること。
    """

    def __init__(
        self,
        calib: Calibration,
        player_size_m: float = 0.85,
        ball_size_m: float = 0.30,
        history: int = 400,
        var_threshold: float = 24.0,
        learning_rate: float = 0.004,
        detect_ball: bool = False,
    ):
        self.calib = calib
        self.learning_rate = learning_rate
        self.detect_ball = detect_ball

        # 「選手 1 人ぶんの実測面積」は、輪郭・影・アンチエイリアス・衣服の
        # はみ出しの分だけ幾何計算値より大きくなる（実測で 1.5〜2 倍）。
        # 閾値を幾何推定のまま使うと、2 人が重なった塊が「1 人」として通り、
        # 必ず片方のトラックが失われて交錯のたびに ID が分裂する。
        # そこで毎フレームの面積分布の中央値＝単独選手の面積とみなして較正する。
        self._geo_area = float(np.pi * (player_size_m / 2.0) ** 2)
        self._nominal_area = self._geo_area
        self._calibrated = False
        self._ball_area = float(np.pi * (ball_size_m / 2.0) ** 2)

        self.bg = cv2.createBackgroundSubtractorMOG2(
            history=history, varThreshold=var_threshold, detectShadows=True
        )
        self.k_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        self.k_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))

    def warmup(self, frames: list[np.ndarray]) -> None:
        """背景モデルを事前学習する。芝など静止背景を先に覚えさせる。"""
        for f in frames:
            self.bg.apply(f, learningRate=0.02)

    def detect(self, frame: np.ndarray) -> list[Detection]:
        raw = self.bg.apply(frame, learningRate=self.learning_rate)
        # MOG2 の影(127)を除去して前景(255)のみ残す
        raw = np.where(raw >= 200, 255, 0).astype(np.uint8)

        # 選手用マスク: ノイズ除去(OPEN)と穴埋め(CLOSE)を強めにかける。
        mask = cv2.morphologyEx(raw, cv2.MORPH_OPEN, self.k_open, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self.k_close, iterations=2)

        # ボール用マスク: ボールは数ピクセルしかないので、選手用の OPEN を
        # かけると消し飛ぶ。小物体は穴埋めのみの軽い処理で別に拾う。
        mask_small = cv2.morphologyEx(raw, cv2.MORPH_CLOSE, self.k_open, iterations=1)

        n, _, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)

        # ── 1 巡目: 実寸面積とピッチ座標を求める ──
        cand: list[tuple] = []
        for i in range(1, n):                      # 0 は背景
            x, y, w, h, area_px = stats[i]
            cx, cy = centroids[i]
            if area_px < 4:
                continue

            mpp = self.calib.meters_per_pixel((cx, cy))
            if not np.isfinite(mpp) or mpp <= 0:
                continue
            area_m2 = float(area_px) * (mpp ** 2)

            pitch = self.calib.to_pitch(np.array([[cx, cy]], float))[0]
            if not np.all(np.isfinite(pitch)):
                continue
            if not self.calib.spec.contains(pitch[0], pitch[1]):
                continue                            # ピッチ外（観客・ベンチ）は捨てる

            cand.append((x, y, w, h, area_px, cx, cy, area_m2, pitch))

        self._calibrate_area([c[7] for c in cand])
        lo = self._nominal_area * 0.35
        hi = self._nominal_area * 1.6

        # ── 2 巡目: 較正済み閾値で分類する ──
        players: list[Detection] = []
        balls: list[Detection] = []

        for x, y, w, h, area_px, cx, cy, area_m2, pitch in cand:
            det = Detection(
                cx=float(cx), cy=float(cy),
                bbox=(int(x), int(y), int(w), int(h)),
                pitch_x=float(pitch[0]), pitch_y=float(pitch[1]),
                area_m2=area_m2,
                hist=_appearance_hist(frame, (x, y, w, h)),
            )

            if lo <= area_m2 <= hi:
                det.kind = "player"
                det.score = float(np.clip(area_px / 40.0, 0.2, 1.0))
                players.append(det)
            elif area_m2 > hi:
                # 重なり・密集（ラック/モール）は 1 塊になる。実寸から人数を
                # 見積もって分割し、両方のトラックを生かす。
                players.extend(self._split_cluster(frame, mask, (x, y, w, h), area_m2))

        if self.detect_ball:
            balls = self._detect_ball(frame, mask_small, players, lo)

        return players + balls

    def _detect_ball(
        self, frame: np.ndarray, mask_small: np.ndarray,
        players: list[Detection], lo: float,
    ) -> list[Detection]:
        """軽い処理のマスクから小物体（ボール候補）を拾う。

        選手ブロブと重なるものは除外する。手中のボールは選手と一体化して
        いるため、ここで拾えるのは主に空中（パス・キック）のボール。
        """
        n, _, stats, centroids = cv2.connectedComponentsWithStats(mask_small, connectivity=8)
        boxes = [p.bbox for p in players]
        out: list[Detection] = []

        for i in range(1, n):
            x, y, w, h, area_px = stats[i]
            cx, cy = centroids[i]
            if area_px < 2:
                continue

            mpp = self.calib.meters_per_pixel((cx, cy))
            if not np.isfinite(mpp) or mpp <= 0:
                continue
            area_m2 = float(area_px) * (mpp ** 2)
            if not (self._ball_area * 0.15 <= area_m2 < lo):
                continue

            # 選手の矩形に含まれる小物体は、選手の一部（手足・影）とみなす
            if any(bx <= cx <= bx + bw and by <= cy <= by + bh
                   for bx, by, bw, bh in boxes):
                continue

            pitch = self.calib.to_pitch(np.array([[cx, cy]], float))[0]
            if not np.all(np.isfinite(pitch)):
                continue
            if not self.calib.spec.contains(pitch[0], pitch[1]):
                continue

            out.append(Detection(
                cx=float(cx), cy=float(cy),
                bbox=(int(x), int(y), int(w), int(h)),
                pitch_x=float(pitch[0]), pitch_y=float(pitch[1]),
                area_m2=area_m2,
                hist=_appearance_hist(frame, (x, y, w, h)),
                kind="ball", score=0.5,
            ))
        return out

    def _calibrate_area(self, areas: list[float]) -> None:
        """面積分布の中央値から「単独選手 1 人ぶんの面積」を推定する。

        画面内の大半は単独の選手なので、妥当な範囲に絞った中央値は重なりの
        影響を受けにくい。EMA で徐々に更新し、フレーム間で安定させる。
        """
        plausible = [a for a in areas if self._geo_area * 0.3 <= a <= self._geo_area * 4.0]
        if len(plausible) < 8:
            return
        med = float(np.median(plausible))
        if self._calibrated:
            self._nominal_area = 0.85 * self._nominal_area + 0.15 * med
        else:
            self._nominal_area = med
            self._calibrated = True

    def _split_cluster(
        self, frame: np.ndarray, mask: np.ndarray, box: tuple[int, int, int, int], area_m2: float
    ) -> list[Detection]:
        """大きな前景塊を、推定人数の k-means で分割する（ラック・密集対策）。"""
        x, y, w, h = box
        k = int(np.clip(round(area_m2 / max(self._nominal_area, 1e-6)), 2, 8))

        sub = mask[y:y + h, x:x + w]
        ys, xs = np.nonzero(sub)
        if len(xs) < k * 4:
            return []
        pts = np.column_stack([xs, ys]).astype(np.float32)

        crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
        _, _, centers = cv2.kmeans(pts, k, None, crit, 3, cv2.KMEANS_PP_CENTERS)

        out: list[Detection] = []
        for cx_l, cy_l in centers:
            cx, cy = float(cx_l) + x, float(cy_l) + y
            pitch = self.calib.to_pitch(np.array([[cx, cy]], float))[0]
            if not np.all(np.isfinite(pitch)):
                continue
            if not self.calib.spec.contains(pitch[0], pitch[1]):
                continue
            side = max(int(np.sqrt(len(pts) / k)), 4)
            bb = (int(cx - side / 2), int(cy - side / 2), side, side)
            out.append(
                Detection(
                    cx=cx, cy=cy, bbox=bb,
                    pitch_x=float(pitch[0]), pitch_y=float(pitch[1]),
                    area_m2=area_m2 / k,
                    hist=_appearance_hist(frame, bb),
                    kind="player",
                    score=0.4,                       # 分割由来は確信度を下げる
                )
            )
        return out


# ── YOLO バックエンド（任意） ────────────────────────────────────────────────

class YoloDetector:
    """ultralytics YOLO による人物検出。導入済みならこちらが高精度。

    背景差分と違い「静止している選手」も拾えるのが利点。
    """

    def __init__(self, calib: Calibration, weights: str = "yolov8n.pt", conf: float = 0.25,
                 ground_point: str = "auto"):
        """
        conf : 推論の信頼度閾値。重なった選手の部分的な見え方（低信頼度枠）も
            トラッカーへ渡せるよう、0.2〜0.3 と低めに設定する。
        ground_point : 枠のどこを「選手のピッチ上の位置」とみなすか。
            - "bottom_center" : 枠の底辺中央＝足元。斜め・側方からの映像で正しい。
            - "centroid"      : 枠の中心。**真上からの俯瞰ではこちらが正しい**
              （真俯瞰では足元も頭も同じ位置に写り、枠の底辺は体の「手前側の縁」に
              すぎないため、底辺中央を使うと体半分ぶん系統的にずれる）。
            - "auto"          : カメラの俯角を推定して自動選択する。
        """
        from ultralytics import YOLO           # 遅延 import（未導入環境を壊さない）

        self.calib = calib
        self.model = YOLO(weights)
        self.conf = conf
        self.ground_point = (
            self._infer_ground_point() if ground_point == "auto" else ground_point
        )

    def _infer_ground_point(self) -> str:
        """ピッチの手前と奥のスケール比から、俯瞰か斜めかを判定する。

        真俯瞰ならピッチ全体で m/px がほぼ一定になる。斜めになるほど手前と奥で
        比が開くので、比が 1.35 を超えたら斜め映像とみなす。
        """
        spec = self.calib.spec
        near = self.calib.to_image(np.array([[spec.length / 2, 1.0]], float))[0]
        far = self.calib.to_image(np.array([[spec.length / 2, spec.width - 1.0]], float))[0]
        if not (np.all(np.isfinite(near)) and np.all(np.isfinite(far))):
            return "centroid"
        s_near = self.calib.meters_per_pixel(tuple(near))
        s_far = self.calib.meters_per_pixel(tuple(far))
        if not (np.isfinite(s_near) and np.isfinite(s_far)) or min(s_near, s_far) <= 0:
            return "centroid"
        ratio = max(s_near, s_far) / min(s_near, s_far)
        return "bottom_center" if ratio > 1.35 else "centroid"

    def warmup(self, frames: list[np.ndarray]) -> None:
        return

    def detect(self, frame: np.ndarray) -> list[Detection]:
        res = self.model.predict(frame, conf=self.conf, verbose=False, classes=[0, 32])
        out: list[Detection] = []
        for r in res:
            for b in r.boxes:
                x1, y1, x2, y2 = (float(v) for v in b.xyxy[0])
                cls = int(b.cls[0])
                cx = (x1 + x2) / 2.0
                # 接地点。斜め映像なら底辺中央、真俯瞰なら枠の中心（上の説明を参照）
                cy = y2 if (self.ground_point == "bottom_center" and cls != 32) \
                    else (y1 + y2) / 2.0
                pitch = self.calib.to_pitch(np.array([[cx, cy]], float))[0]
                if not np.all(np.isfinite(pitch)):
                    continue
                if not self.calib.spec.contains(pitch[0], pitch[1]):
                    continue
                bb = (int(x1), int(y1), int(x2 - x1), int(y2 - y1))
                mpp = self.calib.meters_per_pixel((cx, (y1 + y2) / 2.0))
                out.append(
                    Detection(
                        cx=cx, cy=cy, bbox=bb,
                        pitch_x=float(pitch[0]), pitch_y=float(pitch[1]),
                        area_m2=float(bb[2] * bb[3]) * (mpp ** 2),
                        hist=_appearance_hist(frame, bb),
                        kind="ball" if cls == 32 else "player",
                        score=float(b.conf[0]),
                    )
                )
        return out


# ── 見た目特徴 ────────────────────────────────────────────────────────────────

# 芝生とみなす HSV の色相帯（OpenCV の H は 0–180）
GRASS_H = (32, 88)


def _appearance_hist(frame: np.ndarray, bbox, upper_ratio: float = 0.6) -> np.ndarray | None:
    """選手のジャージ色を表す HSV ヒストグラム。

    枠内の平均色をそのまま取ると、背景の芝（緑）やパンツ・ソックスの色に
    引きずられて 2 チームが分離しなくなる。そこで

      1. 枠の**上部 60%** だけを使う（シャツの占有率を上げる）
      2. **芝の色相をマスク**して計算から除外する
      3. 彩度・明度が極端に低い画素（影）も除外する

    の 3 段で前処理してからヒストグラムを取る。
    """
    x, y, w, h = (int(v) for v in bbox)
    H, W = frame.shape[:2]
    x0, y0 = max(x, 0), max(y, 0)
    x1 = min(x + w, W)
    # 上半身のみ（俯瞰でも肩まわりがシャツ色を最もよく表す）
    y1 = min(y + max(int(h * upper_ratio), 1), H)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None

    hsv = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]

    not_grass = ~((hue >= GRASS_H[0]) & (hue <= GRASS_H[1]) & (sat > 60))
    lit = (sat > 40) & (val > 40)
    m = (not_grass & lit).astype(np.uint8)

    # 芝を抜いた結果ほぼ空になったら、影の条件だけに緩める
    if int(m.sum()) < 8:
        m = lit.astype(np.uint8)
    if int(m.sum()) < 4:
        m = None

    hist = cv2.calcHist([hsv], [0, 1], m, [16, 8], [0, 180, 0, 256])
    cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
    return hist.flatten()


def hist_similarity(a: np.ndarray | None, b: np.ndarray | None) -> float:
    """0（無関係）〜1（同一）の見た目類似度。"""
    if a is None or b is None:
        return 0.5                               # 情報なし = 中立
    return float(np.clip(cv2.compareHist(a.astype(np.float32),
                                         b.astype(np.float32),
                                         cv2.HISTCMP_CORREL), 0.0, 1.0))


def build_detector(calib: Calibration, backend: str = "auto", **kw):
    """バックエンドを選んで検出器を返す。"auto" は YOLO があれば YOLO。"""
    yolo_keys = ("weights", "conf", "ground_point")
    if backend in ("auto", "yolo"):
        try:
            return YoloDetector(calib, **{k: v for k, v in kw.items() if k in yolo_keys})
        except Exception:
            if backend == "yolo":
                raise
    return BackgroundDetector(calib, **{k: v for k, v in kw.items() if k not in yolo_keys})
