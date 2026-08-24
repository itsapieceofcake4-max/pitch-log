"""
pff/paths.py
============
PFF FC データセットの所在を解決する。

配布 ZIP が分割されていると、`Tracking Data` と `Event Data` が別フォルダに
散らばる（実際 001 にイベント・メタ・ロスター、002 にトラッキングが入っていた）。
ここでは複数のルート候補を横断して、game_id ごとに実在するファイルを探す。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# 既定のデータ置き場。環境変数 PFF_DATA_ROOT で上書きできる。
DEFAULT_ROOT = Path(r"C:\Users\User\Desktop\pitch-log\World Cup2022")

SUBDIRS = ("Tracking Data", "Event Data", "Metadata", "Rosters")


def data_root() -> Path:
    return Path(os.environ.get("PFF_DATA_ROOT", str(DEFAULT_ROOT)))


def dataset_dirs(root: Path | str | None = None) -> list[Path]:
    """`Tracking Data` などを含むディレクトリを列挙する。

    分割 ZIP の展開でネストしていても拾えるよう、3 階層まで下りて探す。
    """
    root = Path(root) if root else data_root()
    if not root.exists():
        return []

    found: list[Path] = []
    if any((root / s).is_dir() for s in SUBDIRS):
        found.append(root)
    for depth in (1, 2, 3):
        pattern = "/".join(["*"] * depth)
        for cand in root.glob(pattern):
            if cand.is_dir() and any((cand / s).is_dir() for s in SUBDIRS):
                if cand not in found:
                    found.append(cand)
    return found


def find_file(kind: str, game_id: int | str,
              root: Path | str | None = None) -> Path | None:
    """種別と game_id からファイルを探す。見つからなければ None。

    kind : "tracking" | "event" | "metadata" | "roster"
    """
    names = {
        "tracking": ("Tracking Data", f"{game_id}.jsonl.bz2"),
        "event": ("Event Data", f"{game_id}.json"),
        "metadata": ("Metadata", f"{game_id}.json"),
        "roster": ("Rosters", f"{game_id}.json"),
    }
    if kind not in names:
        raise ValueError(f"未知の種別: {kind}")
    sub, fname = names[kind]

    for d in dataset_dirs(root):
        p = d / sub / fname
        if p.exists():
            return p
    return None


def find_csv(name: str, root: Path | str | None = None) -> Path | None:
    """`players.csv` など、データセット直下の CSV を探す。"""
    for d in dataset_dirs(root):
        p = d / name
        if p.exists():
            return p
    return None


@dataclass
class GameFiles:
    """1 試合ぶんのファイル一式。"""

    game_id: int
    tracking: Path | None
    event: Path | None
    metadata: Path | None
    roster: Path | None

    @property
    def complete(self) -> bool:
        """変換に必要な 4 点が揃っているか。"""
        return all((self.tracking, self.event, self.metadata, self.roster))

    @property
    def missing(self) -> list[str]:
        return [k for k in ("tracking", "event", "metadata", "roster")
                if getattr(self, k) is None]


def locate(game_id: int | str, root: Path | str | None = None) -> GameFiles:
    """game_id からファイル一式を解決する。"""
    return GameFiles(
        game_id=int(game_id),
        tracking=find_file("tracking", game_id, root),
        event=find_file("event", game_id, root),
        metadata=find_file("metadata", game_id, root),
        roster=find_file("roster", game_id, root),
    )


def available_games(root: Path | str | None = None) -> list[int]:
    """トラッキングが存在する game_id の一覧。"""
    ids: set[int] = set()
    for d in dataset_dirs(root):
        td = d / "Tracking Data"
        if not td.is_dir():
            continue
        for p in td.glob("*.jsonl.bz2"):
            stem = p.name.split(".")[0]
            if stem.isdigit():
                ids.add(int(stem))
    return sorted(ids)


# 日本代表の 4 試合（引き継ぎ資料で確定済み）
JAPAN_GAMES: dict[int, str] = {
    3821: "日本 vs ドイツ (2-1)",
    3836: "日本 vs コスタリカ (0-1)",
    3854: "日本 vs スペイン (2-1)",
    10506: "日本 vs クロアチア (PK負け)",
}
