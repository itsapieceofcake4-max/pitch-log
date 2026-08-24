"""
pff/loader.py
=============
PFF FC データの読み込みと座標系の正規化。

実データで確認した仕様（推測ではない）
--------------------------------------
- **fps 29.97**（Metadata の `fps` に明記。frameNum/videoTimeMs からも一致）
- **座標はピッチ中心が原点のメートル**。x が長辺（±52.5）、y が短辺（±34）
- **選手に `speed` は入っていない**（キーは jerseyNum/confidence/visibility/x/y のみ）。
  引き継ぎ資料の「速度が計算済み」は誤りなので、必要なら座標から求める。
- **`homeTeamStartLeft: true` は「前半にホームが +x へ攻める」を意味する**。
  3854 で検証：前半の日本のシュートは x=+48.7、後半の田中のゴールは x=-57.6。
- 時刻は `eventTime`(秒) と `videoTimeMs`(ミリ秒) が同一基準（動画開始から）。
- ボールは 27.6% のフレームで欠損。`balls` が空配列になる。
"""

from __future__ import annotations

import bz2
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

import numpy as np
import pandas as pd

from .paths import GameFiles, locate

VISIBILITY_ORDER = {"VISIBLE": 2, "ESTIMATED": 1}
CONFIDENCE_ORDER = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}


# ── メタデータ ────────────────────────────────────────────────────────────────

@dataclass
class MatchMeta:
    game_id: int
    home_name: str
    away_name: str
    home_id: str
    away_id: str
    fps: float
    pitch_length: float
    pitch_width: float
    home_start_left: bool
    period_bounds: dict[int, tuple[float, float]]   # period → (開始秒, 終了秒)
    video_url: str | None = None
    stadium: str | None = None

    def home_attacks_positive_x(self, period: int) -> bool:
        """そのピリオドでホームが +x 方向へ攻めるか。

        `home_start_left=True` なら前半は +x（3854 の実データで検証済み）。
        後半は反転する。
        """
        first_half = self.home_start_left
        return first_half if period == 1 else not first_half


def load_meta(game_id: int, files: GameFiles | None = None) -> MatchMeta:
    f = files or locate(game_id)
    if not f.metadata:
        raise FileNotFoundError(f"Metadata が見つかりません: game_id={game_id}")

    raw = json.loads(Path(f.metadata).read_text(encoding="utf-8"))
    m = raw[0] if isinstance(raw, list) else raw

    bounds: dict[int, tuple[float, float]] = {}
    for p in (1, 2, 3, 4):
        s, e = m.get(f"startPeriod{p}"), m.get(f"endPeriod{p}")
        if s is not None and e is not None:
            bounds[p] = (float(s), float(e))

    # ピッチ寸法と左右は Event の stadiumMetadata が持っている
    pitch_l, pitch_w, start_left, stadium = 105.0, 68.0, True, None
    if f.event:
        try:
            ev = json.loads(Path(f.event).read_text(encoding="utf-8"))
            sm = (ev[0].get("stadiumMetadata") or {}) if ev else {}
            pitch_l = float(sm.get("pitchLength") or 105.0)
            pitch_w = float(sm.get("pitchWidth") or 68.0)
            start_left = bool(sm.get("homeTeamStartLeft", True))
            stadium = sm.get("stadiumName")
        except Exception:
            pass

    ht, at = m.get("homeTeam") or {}, m.get("awayTeam") or {}
    return MatchMeta(
        game_id=int(game_id),
        home_name=ht.get("name") or "Home",
        away_name=at.get("name") or "Away",
        home_id=str(ht.get("id") or ""),
        away_id=str(at.get("id") or ""),
        fps=float(m.get("fps") or 29.97),
        pitch_length=pitch_l,
        pitch_width=pitch_w,
        home_start_left=start_left,
        period_bounds=bounds,
        video_url=m.get("videoUrl"),
        stadium=stadium,
    )


def load_roster(game_id: int, files: GameFiles | None = None) -> pd.DataFrame:
    """出場選手表。columns = [player_id, name, shirt, position, team_id, team_name, started]"""
    f = files or locate(game_id)
    if not f.roster:
        raise FileNotFoundError(f"Roster が見つかりません: game_id={game_id}")

    raw = json.loads(Path(f.roster).read_text(encoding="utf-8"))
    rows = []
    for r in raw:
        p = r.get("player") or {}
        t = r.get("team") or {}
        rows.append({
            "player_id": str(p.get("id") or ""),
            "name": p.get("nickname") or p.get("name") or "",
            "shirt": str(r.get("shirtNumber") or ""),
            "position": r.get("positionGroupType") or "",
            "team_id": str(t.get("id") or ""),
            "team_name": t.get("name") or "",
            "started": bool(r.get("started")),
        })
    return pd.DataFrame(rows)


# ── イベント ──────────────────────────────────────────────────────────────────

def load_events(game_id: int, files: GameFiles | None = None) -> pd.DataFrame:
    """イベントを平坦な DataFrame にする。

    1 行 = 1 イベント。座標は含めず（重いため）、時刻・種別・選手・結果に絞る。
    シーン選定に必要な情報を一覧できるようにするのが目的。
    """
    f = files or locate(game_id)
    if not f.event:
        raise FileNotFoundError(f"Event が見つかりません: game_id={game_id}")

    raw = json.loads(Path(f.event).read_text(encoding="utf-8"))
    rows = []
    for e in raw:
        ge = e.get("gameEvents") or {}
        pe = e.get("possessionEvents") or {}
        sm = e.get("stadiumMetadata") or {}
        ball = (e.get("ball") or [{}])
        b = ball[0] if ball else {}

        # シュート結果は入れ子の可能性があるので広めに探す
        outcome = None
        for src in (pe, pe.get("shootingEvent") or {}):
            if isinstance(src, dict) and src.get("shotOutcomeType"):
                outcome = src["shotOutcomeType"]
                break

        rows.append({
            "game_id": int(game_id),
            "event_time": e.get("eventTime"),
            "start_time": e.get("startTime"),
            "end_time": e.get("endTime"),
            "duration": e.get("duration"),
            "period": ge.get("period"),
            "game_clock": ge.get("startGameClock"),
            "clock": ge.get("startFormattedGameClock"),
            "is_home": ge.get("homeTeam"),
            "player_id": ge.get("playerId"),
            "player": ge.get("playerName"),
            "game_event_type": ge.get("gameEventType"),
            "possession_event_type": pe.get("possessionEventType"),
            "shot_outcome": outcome,
            "attacking_dir": sm.get("teamAttackingDirection"),
            "ball_x": b.get("x"),
            "ball_y": b.get("y"),
            "video_url": pe.get("eventVideoUrl") or ge.get("eventVideoUrl"),
        })
    return pd.DataFrame(rows)


# ── トラッキング ──────────────────────────────────────────────────────────────

def iter_tracking(
    path: str | Path,
    t0_sec: float | None = None,
    t1_sec: float | None = None,
    progress: Callable[[int], None] | None = None,
) -> Iterator[dict]:
    """`.jsonl.bz2` を解凍せずに 1 フレームずつ流し読みする。

    `t0_sec`〜`t1_sec`（動画時刻・秒）を指定すると、その範囲だけを返し、
    範囲を過ぎた時点で読み取りを打ち切る。全 17 万フレームを載せずに済む。
    """
    lo = None if t0_sec is None else t0_sec * 1000.0
    hi = None if t1_sec is None else t1_sec * 1000.0

    with bz2.open(str(path), "rt", encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if not line.strip():
                continue
            fr = json.loads(line)
            vt = fr.get("videoTimeMs")
            if vt is None:
                continue
            if hi is not None and vt > hi:
                break                              # 以降は不要
            if lo is not None and vt < lo:
                if progress and i % 20000 == 0:
                    progress(i)
                continue
            yield fr
            if progress and i % 5000 == 0:
                progress(i)


def _first_ball(balls) -> dict:
    """ボール要素を取り出す。

    `balls` は list、`ballsSmoothed` は dict という非対称な構造になっている
    （実データで確認）。どちらで来ても 1 個の dict にして返す。
    """
    if isinstance(balls, dict):
        return balls
    if isinstance(balls, list) and balls:
        first = balls[0]
        return first if isinstance(first, dict) else {}
    return {}


def _players_to_rows(players: list[dict], side: str) -> list[dict]:
    out = []
    for p in players or []:
        x, y = p.get("x"), p.get("y")
        if x is None or y is None:
            continue
        out.append({
            "side": side,
            "shirt": str(p.get("jerseyNum") or ""),
            "x_m": float(x),
            "y_m": float(y),
            "visibility": p.get("visibility"),
            "confidence": p.get("confidence"),
        })
    return out


# 直近に読んだ区間を 1 件だけ覚えておく。
# 1 シーンにつき「窓の判定」と「本番の切り出し」で 2 回読むことになるが、
# 後者は前者の部分区間なので、覚えておけば bz2 の展開が 1 回で済む。
# 40MB の展開に 13 秒かかるため、一括処理では効果が大きい。
_CACHE: dict[str, object] = {}


def _cache_get(game_id: int, t0: float, t1: float, smoothed: bool) -> pd.DataFrame | None:
    c = _CACHE.get("entry")
    if not c:
        return None
    key, lo, hi, df = c
    if key != (game_id, smoothed) or t0 < lo - 1e-6 or t1 > hi + 1e-6:
        return None
    return df[(df["video_time"] >= t0) & (df["video_time"] <= t1)].reset_index(drop=True)


def _cache_put(game_id: int, t0: float, t1: float, smoothed: bool,
               df: pd.DataFrame) -> None:
    _CACHE["entry"] = ((game_id, smoothed), t0, t1, df)


def load_tracking_window(
    game_id: int,
    t0_sec: float,
    t1_sec: float,
    files: GameFiles | None = None,
    smoothed: bool = True,
    progress: Callable[[int], None] | None = None,
    use_cache: bool = True,
) -> pd.DataFrame:
    """指定した動画時刻の区間だけを長形式で読み込む。

    Parameters
    ----------
    smoothed : True なら `homePlayersSmoothed` を使う（座標が滑らか）。
        平滑化側には visibility/confidence が入らない場合があるため、
        品質フラグは常に生値（`homePlayers`）から引く。

    Returns
    -------
    columns = [frame, video_time, period, side, shirt, x_m, y_m,
               visibility, confidence, ball_x_m, ball_y_m, ball_z]
    """
    f = files or locate(game_id)
    if not f.tracking:
        raise FileNotFoundError(f"Tracking が見つかりません: game_id={game_id}")

    if use_cache:
        hit = _cache_get(game_id, t0_sec, t1_sec, smoothed)
        if hit is not None:
            return hit

    rows: list[dict] = []
    for fr in iter_tracking(f.tracking, t0_sec, t1_sec, progress):
        frame = fr.get("frameNum")
        vt = float(fr["videoTimeMs"]) / 1000.0
        period = fr.get("period")

        b = _first_ball(fr.get("ballsSmoothed") if smoothed else fr.get("balls"))
        if not b:
            b = _first_ball(fr.get("balls"))
        bx, by = b.get("x"), b.get("y")
        bz = b.get("z")

        # 品質フラグは生値から。座標は指定に応じて平滑化側を使う。
        raw_home = fr.get("homePlayers") or []
        raw_away = fr.get("awayPlayers") or []
        qual = {(r["side"], r["shirt"]): r
                for r in _players_to_rows(raw_home, "home") + _players_to_rows(raw_away, "away")}

        if smoothed:
            src_home = fr.get("homePlayersSmoothed") or raw_home
            src_away = fr.get("awayPlayersSmoothed") or raw_away
        else:
            src_home, src_away = raw_home, raw_away

        for r in _players_to_rows(src_home, "home") + _players_to_rows(src_away, "away"):
            q = qual.get((r["side"], r["shirt"]))
            rows.append({
                "frame": frame,
                "video_time": round(vt, 4),
                "period": period,
                "side": r["side"],
                "shirt": r["shirt"],
                "x_m": r["x_m"],
                "y_m": r["y_m"],
                "visibility": (q or r).get("visibility"),
                "confidence": (q or r).get("confidence"),
                "ball_x_m": float(bx) if bx is not None else np.nan,
                "ball_y_m": float(by) if by is not None else np.nan,
                "ball_z": float(bz) if bz is not None else np.nan,
            })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values(["frame", "side", "shirt"]).reset_index(drop=True)
    if use_cache:
        _cache_put(game_id, t0_sec, t1_sec, smoothed, df)
    return df


# ── 座標の正規化 ──────────────────────────────────────────────────────────────

def normalize(df: pd.DataFrame, meta: MatchMeta,
              clip: bool = True) -> pd.DataFrame:
    """PFF のメートル座標（中心原点）を、Pitch Log の正規化座標 [0,1] に直す。

    ホームが常に x=1 の方向へ攻めるように、ピリオドごとに向きを揃える。
    Export_GSA / app_22 / app_23 はこの向きを前提にしている。

    `clip=True` ならピッチ外（ゴール内のボールなど）を [0,1] に丸める。
    """
    out = df.copy()
    L, W = meta.pitch_length, meta.pitch_width

    # ピリオドごとに符号を決める（+1 ならそのまま、-1 なら左右反転）
    period = pd.to_numeric(out["period"], errors="coerce").fillna(1).astype(int)
    sgn = period.map(lambda p: 1.0 if meta.home_attacks_positive_x(p) else -1.0)

    for src_x, src_y, dst_x, dst_y in (
        ("x_m", "y_m", "x_norm", "y_norm"),
        ("ball_x_m", "ball_y_m", "ball_x_norm", "ball_y_norm"),
    ):
        if src_x not in out.columns:
            continue
        nx = (pd.to_numeric(out[src_x], errors="coerce") * sgn + L / 2) / L
        ny = (pd.to_numeric(out[src_y], errors="coerce") * sgn + W / 2) / W
        if clip:
            nx = nx.clip(0.0, 1.0)
            ny = ny.clip(0.0, 1.0)
        out[dst_x] = nx.round(6)
        out[dst_y] = ny.round(6)

    return out


def filter_quality(df: pd.DataFrame,
                   min_visibility: str | None = None,
                   min_confidence: str | None = None) -> pd.DataFrame:
    """品質フラグで足切りする。

    min_visibility : "VISIBLE" を指定すると推定値を落とす
    min_confidence : "MEDIUM" / "HIGH" を指定するとそれ未満を落とす

    ⚠ 落とした選手はそのフレームで欠測になる。落としすぎると人数が揃わない。
    """
    out = df
    if min_visibility:
        need = VISIBILITY_ORDER.get(min_visibility, 0)
        out = out[out["visibility"].map(lambda v: VISIBILITY_ORDER.get(v, 0) >= need)]
    if min_confidence:
        need = CONFIDENCE_ORDER.get(min_confidence, 0)
        out = out[out["confidence"].map(lambda c: CONFIDENCE_ORDER.get(c, 0) >= need)]
    return out.reset_index(drop=True)
