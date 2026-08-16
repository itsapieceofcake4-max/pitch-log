"""
rugby/tracking.py
=================
検出点に一貫した ID を与え続けるマルチオブジェクト追跡。

選手が重なると単純な最近傍追跡では ID が入れ替わる。ここでは 4 段構えで防ぐ:

1. **物理速度ゲート**  追跡はピッチ座標(m)で行う。人は 10 m/s を超えないので、
   ありえない移動量の対応づけを最初から除外できる（画像座標だと画面位置で
   スケールが変わるため、この制約が使えない）。
2. **カルマン予測**    遮蔽で検出が消えた間も等速モデルで位置を予測し続け、
   再出現時に同じ ID へ戻す。
3. **見た目の再同定**  ジャージ色の HSV ヒストグラムを EMA で保持し、
   位置だけでは決められない場合の決め手にする。
4. **チーム拘束**      別チームの検出には乗り換えないようコストを加算する。

上記でも残る取り違えは UI で手動修正する前提（背番号の割当も UI 側）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np
from scipy.optimize import linear_sum_assignment

from .detection import Detection, hist_similarity


MAX_PLAYER_SPEED = 11.0        # m/s  スプリント上限（余裕込み）

# 既定のフィルタ調整値。両者は比でしか効かないので、映像の解像度・画質に
# 応じて再調整する余地がある（合成映像では 0.08 / 15.0 が最良だった）。
# 小さい MEAS_NOISE と大きい PROCESS_ACCEL ほど観測に素早く追従し、
# 逆にすると滑らかだが遅れる。遅れは位置誤差としてそのまま出るため、
# team sports では追従寄りに置くほうが総合精度が高い。
MEAS_NOISE_M = 0.12            # m    重心推定の誤差
PROCESS_ACCEL = 12.0           # m/s² 想定する切り返しの激しさ
MAX_GATE_M = 12.0              # m    見失い中でも探索半径はここで頭打ちにする
DUP_MERGE_M = 0.9              # m    この距離で重なり続けるトラックは同一とみなす
DUP_MERGE_FRAMES = 5           #      重複と判定するまでの連続フレーム数
INFEASIBLE = 1e6


class TrackState(Enum):
    TENTATIVE = "tentative"     # 確定前（誤検出かもしれない）
    CONFIRMED = "confirmed"
    LOST = "lost"               # 遮蔽等で見失い中（予測で維持）


# ── カルマンフィルタ（等速モデル・ピッチ座標系） ────────────────────────────

class _Kalman:
    """状態 [x, y, vx, vy]（m, m/s）の等速モデル。"""

    def __init__(self, x: float, y: float, dt: float,
                 meas_noise: float = MEAS_NOISE_M, accel: float = PROCESS_ACCEL):
        self.dt = dt
        self.x = np.array([x, y, 0.0, 0.0], dtype=float)
        self.P = np.diag([meas_noise ** 2, meas_noise ** 2, 4.0, 4.0])
        self.F = np.array([
            [1, 0, dt, 0],
            [0, 1, 0, dt],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ], dtype=float)
        self.H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=float)
        self.R = np.eye(2) * (meas_noise ** 2)
        # 加速度ノイズ。小さすぎると等速モデルを信じ込んで観測に追従できず、
        # 出力が実際の検出位置から遅れる（＝生の検出より精度が落ちる）。
        a = accel
        q = np.array([dt ** 4 / 4, dt ** 3 / 2, dt ** 2], dtype=float) * (a ** 2)
        self.Q = np.array([
            [q[0], 0, q[1], 0],
            [0, q[0], 0, q[1]],
            [q[1], 0, q[2], 0],
            [0, q[1], 0, q[2]],
        ], dtype=float)

    def predict(self) -> np.ndarray:
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q
        # 物理的にありえない速度に発散させない
        sp = float(np.hypot(self.x[2], self.x[3]))
        if sp > MAX_PLAYER_SPEED:
            self.x[2:] *= MAX_PLAYER_SPEED / sp
        return self.x[:2].copy()

    def update(self, z: np.ndarray) -> None:
        y = np.asarray(z, float) - self.H @ self.x
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y
        self.P = (np.eye(4) - K @ self.H) @ self.P

    @property
    def pos(self) -> tuple[float, float]:
        return float(self.x[0]), float(self.x[1])

    @property
    def speed(self) -> float:
        return float(np.hypot(self.x[2], self.x[3]))


# ── トラック ──────────────────────────────────────────────────────────────────

@dataclass
class Track:
    """1 選手ぶんの追跡。track_id は映像内で一意。"""

    track_id: int
    kf: _Kalman
    hist: np.ndarray | None
    state: TrackState = TrackState.TENTATIVE
    hits: int = 1
    age: int = 0
    time_since_update: int = 0
    team: int | None = None                       # 0 / 1 / None(未確定)
    jersey: str | None = None                     # UI から手動割当
    team_votes: list[int] = field(default_factory=list)
    last_area_m2: float = 0.0
    dup_streak: dict[int, int] = field(default_factory=dict)   # 相手ID → 連続重複数

    def predict(self) -> None:
        self.kf.predict()
        self.age += 1
        self.time_since_update += 1

    def update(self, det: Detection, hist_alpha: float = 0.15) -> None:
        self.kf.update(np.array([det.pitch_x, det.pitch_y], float))
        self.hits += 1
        self.time_since_update = 0
        self.last_area_m2 = det.area_m2
        if det.hist is not None:
            # 指数移動平均で見た目を更新（急な照明変化に引きずられすぎない）
            self.hist = det.hist if self.hist is None else \
                (1 - hist_alpha) * self.hist + hist_alpha * det.hist
        if self.state is TrackState.LOST:
            self.state = TrackState.CONFIRMED

    @property
    def pitch_xy(self) -> tuple[float, float]:
        return self.kf.pos


# ── チーム判別 ────────────────────────────────────────────────────────────────

class TeamClassifier:
    """ジャージ色ヒストグラムを k-means で 2 チームへ分ける。

    第 3 クラスタ（レフェリー等）は最小クラスタとして team=None に落とす。
    """

    def __init__(self, n_teams: int = 2, with_referee: bool = True):
        self.k = n_teams + (1 if with_referee else 0)
        self.n_teams = n_teams
        self._samples: list[np.ndarray] = []
        self.centers: np.ndarray | None = None
        self._team_of_cluster: dict[int, int | None] = {}

    def collect(self, dets: list[Detection]) -> None:
        for d in dets:
            if d.kind == "player" and d.hist is not None:
                self._samples.append(d.hist)

    def fit(self) -> bool:
        if len(self._samples) < self.k * 8:
            return False
        from sklearn.cluster import KMeans

        X = np.vstack(self._samples)
        km = KMeans(n_clusters=self.k, n_init=8, random_state=0).fit(X)
        self.centers = km.cluster_centers_

        counts = np.bincount(km.labels_, minlength=self.k)
        order = np.argsort(-counts)               # 多い順 = 2 チーム
        self._team_of_cluster = {int(c): (i if i < self.n_teams else None)
                                 for i, c in enumerate(order)}
        return True

    def predict(self, hist: np.ndarray | None) -> int | None:
        if hist is None or self.centers is None:
            return None
        d = np.linalg.norm(self.centers - hist[None, :], axis=1)
        return self._team_of_cluster.get(int(np.argmin(d)))


# ── マルチオブジェクト追跡 ────────────────────────────────────────────────────

class MultiObjectTracker:
    """検出列 → 一貫 ID 付きトラック列。

    Parameters
    ----------
    dt         : フレーム間隔（秒）。速度ゲートとカルマンに使う。
    max_age    : 未検出のまま維持する最大フレーム数（遮蔽の許容長）。
    n_init     : TENTATIVE → CONFIRMED に必要な連続ヒット数。
    w_appear   : コスト内での見た目の重み（0 で位置のみ）。
    """

    def __init__(
        self,
        dt: float,
        max_age: int = 25,
        n_init: int = 3,
        w_appear: float = 0.35,
        team_penalty: float = 0.6,
        meas_noise_m: float = MEAS_NOISE_M,
        process_accel: float = PROCESS_ACCEL,
    ):
        self.dt = dt
        self.max_age = max_age
        self.n_init = n_init
        self.w_appear = w_appear
        self.team_penalty = team_penalty
        self.meas_noise_m = meas_noise_m
        self.process_accel = process_accel
        # 1 フレームで動ける最大距離 + 検出ノイズ
        self.gate_m = MAX_PLAYER_SPEED * dt + 3 * meas_noise_m
        self.tracks: list[Track] = []
        self.teams = TeamClassifier()
        self._next_id = 1

    # ── 1 フレーム処理 ──
    def step(self, dets: list[Detection]) -> list[Track]:
        players = [d for d in dets if d.kind == "player"]

        for t in self.tracks:
            t.predict()

        matches, unmatched_t, unmatched_d = self._associate(players)

        for ti, di in matches:
            tr = self.tracks[ti]
            tr.update(players[di])
            if tr.state is TrackState.TENTATIVE and tr.hits >= self.n_init:
                tr.state = TrackState.CONFIRMED
            team = self.teams.predict(tr.hist)
            if team is not None:
                tr.team_votes.append(team)
                if len(tr.team_votes) > 60:
                    tr.team_votes.pop(0)
                tr.team = int(np.bincount(tr.team_votes).argmax())

        for ti in unmatched_t:
            tr = self.tracks[ti]
            if tr.state is TrackState.CONFIRMED and tr.time_since_update > 0:
                tr.state = TrackState.LOST

        for di in unmatched_d:
            self._spawn(players[di])

        # 期限切れを破棄。未確定トラックは短命に。
        self.tracks = [
            t for t in self.tracks
            if not (
                t.time_since_update > self.max_age
                or (t.state is TrackState.TENTATIVE and t.time_since_update > self.n_init)
            )
        ]
        self._suppress_duplicates()
        return [t for t in self.tracks if t.state is not TrackState.TENTATIVE]

    # ── 重複トラックの統合 ──
    def _suppress_duplicates(self) -> None:
        """同一選手に張り付いた重複トラックを畳む。

        遮蔽から復帰した際、元のトラックと新規トラックが同じ選手に併走する
        ことがある。一定フレーム以上ゼロ距離で重なり続けたペアは同一とみなし、
        古い（＝実績のある）方を残す。
        """
        # 見失い直後のトラックも対象に含める（遮蔽復帰時の二重化がここで起きる）
        alive = [t for t in self.tracks if t.time_since_update <= 3]
        drop: set[int] = set()

        for i, a in enumerate(alive):
            for b in alive[i + 1:]:
                if a.track_id in drop or b.track_id in drop:
                    continue
                ax, ay = a.pitch_xy
                bx, by = b.pitch_xy
                if float(np.hypot(ax - bx, ay - by)) > DUP_MERGE_M:
                    a.dup_streak.pop(b.track_id, None)
                    b.dup_streak.pop(a.track_id, None)
                    continue
                n = a.dup_streak.get(b.track_id, 0) + 1
                a.dup_streak[b.track_id] = n
                b.dup_streak[a.track_id] = n
                if n >= DUP_MERGE_FRAMES:
                    keep, kill = (a, b) if (a.hits, -a.track_id) >= (b.hits, -b.track_id) else (b, a)
                    if kill.jersey and not keep.jersey:
                        keep.jersey = kill.jersey
                    drop.add(kill.track_id)

        if drop:
            self.tracks = [t for t in self.tracks if t.track_id not in drop]

    # ── 対応づけ ──
    def _cost_block(
        self, t_idx: list[int], d_idx: list[int], dets: list[Detection]
    ) -> np.ndarray:
        """指定トラック × 指定検出のコスト行列を作る。"""
        cost = np.full((len(t_idx), len(d_idx)), INFEASIBLE, dtype=float)
        # 検出側のチーム推定は使い回す（トラック数ぶん再計算しない）
        d_team = {j: self.teams.predict(dets[j].hist) for j in d_idx}

        for a, i in enumerate(t_idx):
            tr = self.tracks[i]
            tx, ty = tr.pitch_xy
            # 見失っている間は「その間に動けた距離」だけ探索半径を広げる。
            # ただしコストの正規化には固定の gate_m を使う。可変ゲートで割ると
            # 見失いが長いトラックほど距離が安く見え、比較が不公平になるため。
            gate = min(
                MAX_PLAYER_SPEED * self.dt * (1 + tr.time_since_update) + 3 * self.meas_noise_m,
                MAX_GATE_M,
            )
            for b, j in enumerate(d_idx):
                d = dets[j]
                dist = float(np.hypot(d.pitch_x - tx, d.pitch_y - ty))
                if dist > gate:
                    continue
                c = dist / self.gate_m
                if self.w_appear > 0:
                    c += self.w_appear * (1.0 - hist_similarity(tr.hist, d.hist))
                if tr.team is not None:
                    dt_ = d_team[j]
                    if dt_ is not None and dt_ != tr.team:
                        c += self.team_penalty
                cost[a, b] = c
        return cost

    def _associate(self, dets: list[Detection]):
        """マッチングカスケード方式の対応づけ。

        直近に更新されたトラックから順に検出を確保していく。全トラックを
        一度に Hungarian へ通すと、長く見失って位置が不確かなトラックが
        「全体コストの最小化」の名目で正しいトラックから検出を奪い、
        ID の取り違えと分裂を大量に生む。年齢順に段階的へ解くことでこれを防ぐ。
        （DeepSORT の matching cascade と同じ考え方）
        """
        if not self.tracks or not dets:
            return [], list(range(len(self.tracks))), list(range(len(dets)))

        by_age: dict[int, list[int]] = {}
        for i, tr in enumerate(self.tracks):
            by_age.setdefault(tr.time_since_update, []).append(i)

        remaining_d = list(range(len(dets)))
        matches: list[tuple[int, int]] = []
        unmatched_t: list[int] = []

        for age in sorted(by_age):
            t_idx = by_age[age]
            if not remaining_d:
                unmatched_t.extend(t_idx)
                continue

            cost = self._cost_block(t_idx, remaining_d, dets)
            rows, cols = linear_sum_assignment(cost)

            taken_t, taken_d = set(), set()
            for r, c in zip(rows, cols):
                if cost[r, c] >= INFEASIBLE:
                    continue
                matches.append((t_idx[r], remaining_d[c]))
                taken_t.add(r)
                taken_d.add(c)

            unmatched_t.extend(t for a, t in enumerate(t_idx) if a not in taken_t)
            remaining_d = [d for b, d in enumerate(remaining_d) if b not in taken_d]

        return matches, sorted(unmatched_t), sorted(remaining_d)

    def _spawn(self, det: Detection) -> None:
        tr = Track(
            track_id=self._next_id,
            kf=_Kalman(det.pitch_x, det.pitch_y, self.dt,
                       self.meas_noise_m, self.process_accel),
            hist=det.hist,
            last_area_m2=det.area_m2,
        )
        team = self.teams.predict(det.hist)
        if team is not None:
            tr.team = team
            tr.team_votes.append(team)
        self.tracks.append(tr)
        self._next_id += 1


# ── ボール追跡 ────────────────────────────────────────────────────────────────

@dataclass
class BallState:
    """ボールの推定位置と、その根拠。

    ラグビーのボールは大半の時間を選手の手中で過ごすため、俯瞰映像から
    常時直接検出するのは現実的でない。そこで
      - 空中（パス・キック）は検出点をそのまま採用   → status="flight"
      - 保持中は「キャリア（保持者）の位置」で代用    → status="carried"
    の 2 モードで表現する。どちらでもない場合は status="lost"。
    """

    pitch_x: float | None = None
    pitch_y: float | None = None
    status: str = "lost"
    carrier_id: int | None = None
    confidence: float = 0.0


class BallTracker:
    """ボール候補と選手トラックから、フレームごとのボール状態を決める。

    ⚠ 上空映像でのボール追跡は本質的に難しい。ボールは数ピクセルしかなく、
    かつラグビーでは大半の時間を選手の手中で過ごすため画像上で分離できない。
    ここでは「空中で実際に検出できたとき」と「その直後に受け取った選手が
    持っている間」だけを出力し、根拠を失ったら素直に lost を返す。
    位置を捏造しないことを優先している（誤った座標は下流の分析を壊すため）。
    """

    def __init__(self, dt: float, carry_hold_sec: float = 1.5, carry_radius_m: float = 3.0,
                 confirm_frames: int = 3):
        self.dt = dt
        self.carry_hold = max(int(carry_hold_sec / dt), 1)
        self.carry_radius = carry_radius_m
        self.confirm_frames = confirm_frames
        self.state = BallState()
        self._last: tuple[float, float] | None = None
        self._since_real = 10 ** 6            # 最後に実検出できてからのフレーム数
        self._carrier: int | None = None
        # 未確定の候補: [x, y, 連続一致数]
        self._pending: list[list[float]] = []
        # ボールはキックで 25 m/s 程度まで出る
        self.gate_m = 25.0 * dt + 1.5

    def _confirm(self, cands: list[Detection]) -> Detection | None:
        """連続フレームで一貫して動く候補だけをボールとして確定する。

        俯瞰映像のボールは数ピクセルしかなく、芝のノイズと大きさで区別できない。
        単発のブロブを採用すると数十メートル外れた座標を出してしまうので、
        「前フレームの候補から物理的に妥当な距離しか動いていない」ことが
        `confirm_frames` 回続いたものだけを信用する。
        """
        nxt: list[list[float]] = []
        confirmed: Detection | None = None

        for d in cands:
            hit = None
            for p in self._pending:
                if float(np.hypot(d.pitch_x - p[0], d.pitch_y - p[1])) <= self.gate_m:
                    hit = p
                    break
            count = (hit[2] + 1) if hit else 1
            nxt.append([d.pitch_x, d.pitch_y, count])
            if count >= self.confirm_frames and confirmed is None:
                confirmed = d

        # 候補は数フレームで消える（追従できないノイズを溜め込まない）
        self._pending = [p for p in nxt if p[2] < self.confirm_frames * 3]
        return confirmed

    def step(self, dets: list[Detection], tracks: list[Track]) -> BallState:
        cands = [d for d in dets if d.kind == "ball"]

        best = None
        if self._last is not None and self._since_real <= self.carry_hold:
            # 追跡中は直前位置の近傍だけを見る
            in_gate = [
                d for d in cands
                if float(np.hypot(d.pitch_x - self._last[0],
                                  d.pitch_y - self._last[1])) <= self.gate_m
            ]
            if in_gate:
                best = min(in_gate, key=lambda d: np.hypot(d.pitch_x - self._last[0],
                                                           d.pitch_y - self._last[1]))
            self._pending = []
        else:
            # 未捕捉のときは、時間的に一貫した候補が現れるまで採用しない
            best = self._confirm(cands)

        if best is not None:
            self._last = (best.pitch_x, best.pitch_y)
            self._since_real = 0
            self._carrier = None
            self.state = BallState(best.pitch_x, best.pitch_y, "flight", None, 0.7)
            return self.state

        self._since_real += 1

        # 実検出から一定時間内なら「見失った地点で受け取った選手」が保持中と見なす。
        # 毎フレーム最近傍を選び直すと、ボールが選手から選手へ延々と乗り移って
        # 際限なく漂流するため、キャリアは一度決めたら固定して追い続ける。
        if self._since_real <= self.carry_hold and tracks:
            if self._carrier is None and self._last is not None:
                lx, ly = self._last
                near = min(tracks, key=lambda t: np.hypot(t.pitch_xy[0] - lx,
                                                          t.pitch_xy[1] - ly))
                if float(np.hypot(near.pitch_xy[0] - lx,
                                  near.pitch_xy[1] - ly)) <= self.carry_radius:
                    self._carrier = near.track_id

            if self._carrier is not None:
                cur = next((t for t in tracks if t.track_id == self._carrier), None)
                if cur is not None:
                    cx, cy = cur.pitch_xy
                    self._last = (cx, cy)
                    self.state = BallState(cx, cy, "carried", cur.track_id, 0.35)
                    return self.state

        self._carrier = None
        self.state = BallState(None, None, "lost", None, 0.0)
        return self.state
