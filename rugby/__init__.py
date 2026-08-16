"""
rugby — PitchLog v25 : 上空映像から選手・ボールの位置情報を抽出するモジュール群。

パイプライン
------------
    動画 ──▶ [キャリブレーション] ──▶ [検出] ──▶ [追跡] ──▶ [CSV 出力]
            ピッチライン指定で        動く点を      ID を維持    縦=時間
            画像↔メートルを対応づけ   拾い出す      し続ける      横=選手

使い方（最短）
--------------
    from rugby import probe_video, grab_frame, calibrate, process_window, write_csvs
"""

from .pitch_model import (
    PitchSpec, PRESETS, RUGBY_UNION_15, RUGBY_LEAGUE_13, RUGBY_SEVENS, SOCCER,
    Landmark, build_landmarks, landmark_index, pitch_lines,
    PitchLine, build_pitch_line_defs, pitch_line_index,
)
from .calibration import (
    Calibration, calibrate, calibrate_from_lines, calibrate_from_quad,
    quad_from_enclosing_lines, order_quad, line_intersection,
    draw_pitch_overlay, MIN_POINTS,
)
from .detection import Detection, BackgroundDetector, YoloDetector, build_detector
from .tracking import Track, TrackState, MultiObjectTracker, BallTracker, BallState
from .pipeline import VideoInfo, probe_video, grab_frame, process_window, track_summary
from .clip import extract as extract_clip, has_ffmpeg
from .export import assign_slots, to_wide, to_spec_schema, write_csvs
from .physical import PhysicalConfig, compute_kinematics, physical_report, config_summary
from .voronoi import (
    VoronoiCell, compute_cells, cells_for_frame, dominance, dominance_series, pitch_rect,
)
from .animate import PitchRenderer, render_animation

__all__ = [
    "PitchSpec", "PRESETS", "RUGBY_UNION_15", "RUGBY_LEAGUE_13", "RUGBY_SEVENS", "SOCCER",
    "Landmark", "build_landmarks", "landmark_index", "pitch_lines",
    "PitchLine", "build_pitch_line_defs", "pitch_line_index",
    "Calibration", "calibrate", "calibrate_from_lines", "calibrate_from_quad",
    "quad_from_enclosing_lines", "order_quad", "line_intersection",
    "draw_pitch_overlay", "MIN_POINTS",
    "Detection", "BackgroundDetector", "YoloDetector", "build_detector",
    "Track", "TrackState", "MultiObjectTracker", "BallTracker", "BallState",
    "VideoInfo", "probe_video", "grab_frame", "process_window", "track_summary",
    "extract_clip", "has_ffmpeg",
    "assign_slots", "to_wide", "to_spec_schema", "write_csvs",
    "PhysicalConfig", "compute_kinematics", "physical_report", "config_summary",
    "VoronoiCell", "compute_cells", "cells_for_frame", "dominance", "dominance_series",
    "pitch_rect", "PitchRenderer", "render_animation",
]

__version__ = "25.0.0"
