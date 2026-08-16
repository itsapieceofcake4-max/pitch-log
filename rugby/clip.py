"""
rugby/clip.py
=============
長い試合映像から、解析したい時間帯だけを小さなファイルへ切り出す。

なぜ必要か
----------
ラグビーの試合映像は 80 分＋で、1080p なら **2〜6GB** になる。一方 Streamlit を
クラウドへ置いた場合、アップロードはファイル全体をメモリに載せるため GB 級の
ファイルは通らない。

解析自体は 30 秒窓しか使わないので、**先に必要な部分だけ切り出せば数十 MB** に
収まり、クラウドでも扱える。ここはその切り出しを行う。

方式
----
- **ffmpeg があれば再エンコードなし**（`-c copy`）で切り出す。ほぼ一瞬で終わり、
  画質も劣化しない。キーフレーム境界に丸められるため、開始位置は指定より
  わずかに前になることがある（解析には影響しない範囲）。
- ffmpeg が無ければ OpenCV で読み書きする。確実だが再エンコードのぶん遅い。

    python -m rugby.clip --video match.mp4 --start 1830 --duration 30 --out scene.mp4
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

import cv2

from .pipeline import probe_video


def has_ffmpeg() -> bool:
    """ffmpeg が PATH にあるか。"""
    return shutil.which("ffmpeg") is not None


def _fmt_hhmmss(sec: float) -> str:
    h, rem = divmod(max(sec, 0.0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


def extract_ffmpeg(
    video: str | Path, start_sec: float, duration_sec: float, out_path: str | Path,
    reencode: bool = False,
) -> Path:
    """ffmpeg で切り出す。既定は再エンコードなし（高速・無劣化）。

    Raises
    ------
    RuntimeError : ffmpeg が失敗した場合。
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if reencode:
        # 開始位置を正確に合わせたい場合。入力の後に -ss を置くと厳密になる。
        cmd = [
            "ffmpeg", "-y", "-i", str(video),
            "-ss", _fmt_hhmmss(start_sec), "-t", f"{duration_sec:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-an", str(out_path),
        ]
    else:
        # -ss を入力の前に置くと高速シークになる（キーフレーム単位）
        cmd = [
            "ffmpeg", "-y", "-ss", _fmt_hhmmss(start_sec), "-i", str(video),
            "-t", f"{duration_sec:.3f}", "-c", "copy", "-an", str(out_path),
        ]

    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if r.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
        tail = (r.stderr or "")[-400:]
        raise RuntimeError(f"ffmpeg での切り出しに失敗しました:\n{tail}")
    return out_path


def extract_opencv(
    video: str | Path, start_sec: float, duration_sec: float, out_path: str | Path,
    progress=None,
) -> Path:
    """OpenCV で切り出す（ffmpeg が無い環境向け）。再エンコードされる。"""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    info = probe_video(video)
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise FileNotFoundError(f"動画を開けません: {video}")

    writer = cv2.VideoWriter(
        str(out_path), cv2.VideoWriter_fourcc(*"mp4v"), info.fps,
        (info.width, info.height),
    )
    if not writer.isOpened():
        cap.release()
        raise RuntimeError("出力ファイルを作成できませんでした。")

    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(start_sec, 0.0) * 1000.0)
        n = int(duration_sec * info.fps)
        for i in range(n):
            ok, frame = cap.read()
            if not ok:
                break
            writer.write(frame)
            if progress and (i % 25 == 0 or i == n - 1):
                progress((i + 1) / n, f"切り出し中 {i + 1}/{n} フレーム")
    finally:
        writer.release()
        cap.release()

    if out_path.stat().st_size == 0:
        raise RuntimeError("切り出し結果が空でした。開始位置を確認してください。")
    return out_path


def extract(
    video: str | Path, start_sec: float, duration_sec: float, out_path: str | Path,
    progress=None,
) -> tuple[Path, str]:
    """利用できる手段で切り出す。戻り値は (出力パス, 使った方式)。"""
    if has_ffmpeg():
        try:
            return extract_ffmpeg(video, start_sec, duration_sec, out_path), "ffmpeg"
        except Exception:
            pass                                  # 失敗したら OpenCV へ落とす
    return extract_opencv(video, start_sec, duration_sec, out_path, progress), "opencv"


def main() -> None:
    import io
    import sys

    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(
        description="長い試合映像から解析したい時間帯だけを切り出す")
    ap.add_argument("--video", required=True, help="元の試合映像")
    ap.add_argument("--start", type=float, required=True, help="開始位置（秒）")
    ap.add_argument("--duration", type=float, default=30.0, help="長さ（秒）")
    ap.add_argument("--out", required=True, help="出力 mp4")
    ap.add_argument("--reencode", action="store_true",
                    help="開始位置を厳密に合わせる（遅いが正確）")
    args = ap.parse_args()

    src = Path(args.video)
    info = probe_video(src)
    print(f"元映像 : {src.name}  {info.duration_sec / 60:.1f} 分  "
          f"{src.stat().st_size / 1e6:.0f} MB")

    if args.reencode and has_ffmpeg():
        out = extract_ffmpeg(src, args.start, args.duration, args.out, reencode=True)
        how = "ffmpeg(再エンコード)"
    else:
        out, how = extract(src, args.start, args.duration, args.out,
                           progress=lambda f, m: print(f"  [{f*100:5.1f}%] {m}", end="\r"))
    print()
    print(f"切り出し: {out}  {out.stat().st_size / 1e6:.1f} MB  （{how}）")
    print(f"          {args.start:.1f} 秒から {args.duration:.1f} 秒間")


if __name__ == "__main__":
    main()
