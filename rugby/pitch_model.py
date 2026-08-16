"""
rugby/pitch_model.py
====================
ラグビーピッチの寸法モデルとキャリブレーション用ランドマーク定義。

座標系（ピッチ座標・単位メートル）
---------------------------------
    原点 (0, 0) = 左ゴールライン × 下タッチライン の交点
    X 軸 : 0 → length  （ピッチの長辺方向 / 左ゴールライン → 右ゴールライン）
    Y 軸 : 0 → width   （ピッチの短辺方向 / 下タッチライン → 上タッチライン）

インゴールは X < 0（左）および X > length（右）に伸びる。
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ── ピッチ仕様 ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PitchSpec:
    """ピッチ寸法（メートル）。World Rugby 規定の範囲内で可変。"""

    name: str
    length: float = 100.0     # ゴールライン間
    width: float = 70.0       # タッチライン間
    in_goal: float = 10.0     # インゴール奥行き（6–22m）。サッカーでは 0。
    n_players: int = 15       # 1チームあたりの出場人数
    sport: str = "rugby"      # "rugby" | "soccer"（ライン描画の分岐に使う）

    @property
    def x_min(self) -> float:
        return -self.in_goal

    @property
    def x_max(self) -> float:
        return self.length + self.in_goal

    def normalize(self, x_m: float, y_m: float) -> tuple[float, float]:
        """メートル → 正規化座標 [0, 1]（PitchLog 既存パイプライン互換）。

        インゴールを含む全長を 0–1 に写す。
        """
        span = self.x_max - self.x_min
        return (x_m - self.x_min) / span, y_m / self.width

    def contains(self, x_m: float, y_m: float, margin: float = 3.0) -> bool:
        """インゴール＋マージンを含む撮影範囲内かどうか。"""
        return (
            self.x_min - margin <= x_m <= self.x_max + margin
            and -margin <= y_m <= self.width + margin
        )


RUGBY_UNION_15 = PitchSpec("ラグビーユニオン (15人制)", 100.0, 70.0, 10.0, 15, "rugby")
RUGBY_LEAGUE_13 = PitchSpec("ラグビーリーグ (13人制)", 100.0, 68.0, 8.0, 13, "rugby")
RUGBY_SEVENS = PitchSpec("セブンズ (7人制)", 100.0, 70.0, 10.0, 7, "rugby")
SOCCER = PitchSpec("サッカー (11人制)", 105.0, 68.0, 0.0, 11, "soccer")

PRESETS: dict[str, PitchSpec] = {
    p.name: p for p in (RUGBY_UNION_15, RUGBY_LEAGUE_13, RUGBY_SEVENS, SOCCER)
}


# ── キャリブレーション用ランドマーク ──────────────────────────────────────────

@dataclass(frozen=True)
class Landmark:
    """映像上でクリックして指定するピッチ上の既知点。"""

    key: str
    label_ja: str
    x: float          # ピッチ座標（m）
    y: float
    group: str        # UI グルーピング用


def build_landmarks(spec: PitchSpec) -> list[Landmark]:
    """ピッチ仕様から、映像上で識別しやすいランドマーク一覧を生成する。

    タッチラインと各横断ラインの交点を基本とする。5m / 15m の破線との交点も
    含めることで、映像に片側半分しか写っていない場合でも 4 点を確保できる。
    """
    if spec.sport == "soccer":
        return _soccer_landmarks(spec)

    L, W = spec.length, spec.width
    G = spec.in_goal
    out: list[Landmark] = []

    def add(key: str, label: str, x: float, y: float, group: str) -> None:
        out.append(Landmark(key, label, x, y, group))

    # 縦断ライン（X 固定）× タッチライン（Y = 0 / W）
    vlines = [
        ("dead_l", "デッドボールL", -G),
        ("goal_l", "ゴールラインL", 0.0),
        ("m22_l", "22mラインL", 22.0),
        ("m10_l", "10mラインL", L / 2 - 10.0),
        ("half", "ハーフウェイ", L / 2),
        ("m10_r", "10mラインR", L / 2 + 10.0),
        ("m22_r", "22mラインR", L - 22.0),
        ("goal_r", "ゴールラインR", L),
        ("dead_r", "デッドボールR", L + G),
    ]

    for key, label, x in vlines:
        add(f"{key}__touch_bot", f"{label} × 下タッチ", x, 0.0, label)
        add(f"{key}__touch_top", f"{label} × 上タッチ", x, W, label)

    # 5m / 15m 破線との交点（ゴールライン・22m・10m・ハーフウェイのみ）
    dashed = [(5.0, "5m破線"), (15.0, "15m破線")]
    for key, label, x in vlines[1:-1]:          # デッドボールラインは対象外
        for off, dlabel in dashed:
            add(f"{key}__d{int(off)}_bot", f"{label} × {dlabel}(下)", x, off, label)
            add(f"{key}__d{int(off)}_top", f"{label} × {dlabel}(上)", x, W - off, label)

    return out


# ── 直線としてのピッチライン（線を引くキャリブレーション用） ─────────────────

@dataclass(frozen=True)
class PitchLine:
    """ピッチ上の直線。映像上でなぞってもらい、交点から座標を復元する。

    axis="x" … 縦断ライン（x = value の直線。ピッチを横切る向き）
    axis="y" … 横断ライン（y = value の直線。ピッチの長辺に沿う向き）
    """

    key: str
    label_ja: str
    axis: str
    value: float


def build_pitch_line_defs(spec: PitchSpec) -> list[PitchLine]:
    """なぞる対象になりうる直線の一覧を返す。

    交点を 4 つ作るには「縦断 2 本 + 横断 2 本」以上が必要。
    """
    L, W, G = spec.length, spec.width, spec.in_goal

    if spec.sport == "soccer":
        cy = W / 2
        x_lines = [
            ("goal_l", "左ゴールライン", 0.0),
            ("ga_l", "左ゴールエリア外側 (5.5m)", 5.5),
            ("pa_l", "左ペナルティエリア外側 (16.5m)", 16.5),
            ("half", "ハーフウェイライン", L / 2),
            ("pa_r", "右ペナルティエリア外側 (16.5m)", L - 16.5),
            ("ga_r", "右ゴールエリア外側 (5.5m)", L - 5.5),
            ("goal_r", "右ゴールライン", L),
        ]
        y_lines = [
            ("touch_bot", "下タッチライン", 0.0),
            ("pa_bot", "PA 下辺", cy - 20.16),
            ("ga_bot", "GA 下辺", cy - 9.16),
            ("ga_top", "GA 上辺", cy + 9.16),
            ("pa_top", "PA 上辺", cy + 20.16),
            ("touch_top", "上タッチライン", W),
        ]
    else:
        x_lines = [
            ("dead_l", "左デッドボールライン", -G),
            ("goal_l", "左ゴールライン（トライライン）", 0.0),
            ("m22_l", "左 22m ライン", 22.0),
            ("m10_l", "左 10m ライン", L / 2 - 10.0),
            ("half", "ハーフウェイライン", L / 2),
            ("m10_r", "右 10m ライン", L / 2 + 10.0),
            ("m22_r", "右 22m ライン", L - 22.0),
            ("goal_r", "右ゴールライン（トライライン）", L),
            ("dead_r", "右デッドボールライン", L + G),
        ]
        y_lines = [
            ("touch_bot", "下タッチライン", 0.0),
            ("d5_bot", "下 5m 破線", 5.0),
            ("d15_bot", "下 15m 破線", 15.0),
            ("d15_top", "上 15m 破線", W - 15.0),
            ("d5_top", "上 5m 破線", W - 5.0),
            ("touch_top", "上タッチライン", W),
        ]

    return ([PitchLine(k, lb, "x", v) for k, lb, v in x_lines]
            + [PitchLine(k, lb, "y", v) for k, lb, v in y_lines])


def pitch_line_index(spec: PitchSpec) -> dict[str, PitchLine]:
    return {pl.key: pl for pl in build_pitch_line_defs(spec)}


def _soccer_landmarks(spec: PitchSpec) -> list[Landmark]:
    """サッカー用の基準点。ペナルティエリアの四隅が最も取りやすい。"""
    L, W = spec.length, spec.width
    cy = W / 2
    out: list[Landmark] = []

    def add(key: str, label: str, x: float, y: float, group: str) -> None:
        out.append(Landmark(key, label, x, y, group))

    for side, sname, sx, sgn in (("l", "左", 0.0, 1.0), ("r", "右", L, -1.0)):
        add(f"goal_{side}__touch_bot", f"{sname}ゴールライン × 下タッチ", sx, 0.0, f"{sname}ゴールライン")
        add(f"goal_{side}__touch_top", f"{sname}ゴールライン × 上タッチ", sx, W, f"{sname}ゴールライン")

        pa_x = sx + sgn * 16.5
        add(f"pa_{side}__out_bot", f"{sname}PA 外側・下", pa_x, cy - 20.16, f"{sname}ペナルティエリア")
        add(f"pa_{side}__out_top", f"{sname}PA 外側・上", pa_x, cy + 20.16, f"{sname}ペナルティエリア")
        add(f"pa_{side}__goal_bot", f"{sname}PA ゴールライン側・下", sx, cy - 20.16, f"{sname}ペナルティエリア")
        add(f"pa_{side}__goal_top", f"{sname}PA ゴールライン側・上", sx, cy + 20.16, f"{sname}ペナルティエリア")

        ga_x = sx + sgn * 5.5
        add(f"ga_{side}__out_bot", f"{sname}GA 外側・下", ga_x, cy - 9.16, f"{sname}ゴールエリア")
        add(f"ga_{side}__out_top", f"{sname}GA 外側・上", ga_x, cy + 9.16, f"{sname}ゴールエリア")
        add(f"ga_{side}__goal_bot", f"{sname}GA ゴールライン側・下", sx, cy - 9.16, f"{sname}ゴールエリア")
        add(f"ga_{side}__goal_top", f"{sname}GA ゴールライン側・上", sx, cy + 9.16, f"{sname}ゴールエリア")

        add(f"pk_{side}", f"{sname}ペナルティスポット", sx + sgn * 11.0, cy, f"{sname}ペナルティエリア")

    add("half__touch_bot", "ハーフウェイ × 下タッチ", L / 2, 0.0, "ハーフウェイ")
    add("half__touch_top", "ハーフウェイ × 上タッチ", L / 2, W, "ハーフウェイ")
    add("center", "センターマーク", L / 2, cy, "ハーフウェイ")
    add("circle_bot", "センターサークル × ハーフウェイ(下)", L / 2, cy - 9.15, "ハーフウェイ")
    add("circle_top", "センターサークル × ハーフウェイ(上)", L / 2, cy + 9.15, "ハーフウェイ")
    return out


def landmark_index(spec: PitchSpec) -> dict[str, Landmark]:
    return {lm.key: lm for lm in build_landmarks(spec)}


# ── 描画用のライン定義（2D マップ描画に使用） ────────────────────────────────

def pitch_lines(spec: PitchSpec) -> list[tuple[str, list[tuple[float, float]]]]:
    """2D マッピング描画用のライン一覧。(種別, 頂点列) のリスト。

    種別: "solid"（実線） / "dashed"（破線）
    """
    if spec.sport == "soccer":
        return _soccer_lines(spec)

    L, W, G = spec.length, spec.width, spec.in_goal
    lines: list[tuple[str, list[tuple[float, float]]]] = []

    # 外周（インゴールを含む）
    lines.append(("solid", [(-G, 0), (L + G, 0), (L + G, W), (-G, W), (-G, 0)]))

    # 横断実線
    for x in (0.0, L, L / 2, 22.0, L - 22.0):
        lines.append(("solid", [(x, 0), (x, W)]))

    # 10m ライン（規定上は破線）
    for x in (L / 2 - 10.0, L / 2 + 10.0):
        lines.append(("dashed", [(x, 0), (x, W)]))

    # 5m / 15m 縦破線
    for y in (5.0, 15.0, W - 15.0, W - 5.0):
        lines.append(("dashed", [(0, y), (L, y)]))

    return lines


def _circle(cx: float, cy: float, r: float, n: int = 48) -> list[tuple[float, float]]:
    import math

    return [(cx + r * math.cos(2 * math.pi * i / n),
             cy + r * math.sin(2 * math.pi * i / n)) for i in range(n + 1)]


def _soccer_lines(spec: PitchSpec) -> list[tuple[str, list[tuple[float, float]]]]:
    """サッカーピッチ（外周・ハーフウェイ・センターサークル・PA・GA）。"""
    L, W = spec.length, spec.width
    lines: list[tuple[str, list[tuple[float, float]]]] = [
        ("solid", [(0, 0), (L, 0), (L, W), (0, W), (0, 0)]),
        ("solid", [(L / 2, 0), (L / 2, W)]),
        ("solid", _circle(L / 2, W / 2, 9.15)),
    ]
    for side in (0.0, L):
        sgn = 1.0 if side == 0.0 else -1.0
        # ペナルティエリア 16.5m × 40.32m
        lines.append(("solid", [
            (side, W / 2 - 20.16), (side + sgn * 16.5, W / 2 - 20.16),
            (side + sgn * 16.5, W / 2 + 20.16), (side, W / 2 + 20.16),
        ]))
        # ゴールエリア 5.5m × 18.32m
        lines.append(("solid", [
            (side, W / 2 - 9.16), (side + sgn * 5.5, W / 2 - 9.16),
            (side + sgn * 5.5, W / 2 + 9.16), (side, W / 2 + 9.16),
        ]))
    return lines
