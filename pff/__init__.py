"""
pff — PFF FC（現 Gradient Sports）データを Pitch Log で扱うためのモジュール群。

    from pff import locate, load_meta, load_events, load_tracking_window, normalize

パイプライン
------------
    PFF (30fps, 中心原点メートル)
      → loader   … 区間だけ読む・座標を正規化
      → convert  … 中間形式 → xt_pipeline_22 → Export_GSA (126列)
      → app_22 / app_23 でそのまま読める
"""

from .paths import (
    GameFiles, JAPAN_GAMES, available_games, data_root, dataset_dirs,
    find_csv, find_file, locate,
)
from .loader import (
    MatchMeta, filter_quality, iter_tracking, load_events, load_meta,
    load_roster, load_tracking_window, normalize,
)

__all__ = [
    "GameFiles", "JAPAN_GAMES", "available_games", "data_root", "dataset_dirs",
    "find_csv", "find_file", "locate",
    "MatchMeta", "filter_quality", "iter_tracking", "load_events", "load_meta",
    "load_roster", "load_tracking_window", "normalize",
]

__version__ = "0.1.0"
