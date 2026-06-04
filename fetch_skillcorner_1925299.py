"""
fetch_skillcorner_1925299.py
==============================
Match : Brisbane Roar FC 0-1 Perth Glory FC
Date  : 2024-12-21
Source: SkillCorner Open Data (GitHub)

Downloads 4 files into  skillcorner_1925299/
  - 1925299_match.json               (match metadata, team/player IDs)
  - 1925299_phases_of_play.csv       (133 KB  — goal frame detection)
  - 1925299_dynamic_events.csv       (4.77 MB — event data)
  - 1925299_tracking_extrapolated.jsonl  (large — 22-player positions @ 10 fps)

Usage
-----
  python fetch_skillcorner_1925299.py
"""

import sys
import requests
from pathlib import Path

MATCH_ID = "1925299"
OUT_DIR  = Path(f"skillcorner_{MATCH_ID}")
OUT_DIR.mkdir(exist_ok=True)

# tracking JSONL is Git LFS → use media URL; others use raw URL
RAW   = f"https://raw.githubusercontent.com/SkillCorner/opendata/master/data/matches/{MATCH_ID}/"
MEDIA = f"https://media.githubusercontent.com/media/SkillCorner/opendata/master/data/matches/{MATCH_ID}/"

FILES = {
    f"{MATCH_ID}_match.json":                  RAW,
    f"{MATCH_ID}_phases_of_play.csv":           RAW,
    f"{MATCH_ID}_dynamic_events.csv":           RAW,
    f"{MATCH_ID}_tracking_extrapolated.jsonl":  MEDIA,
}

CHUNK = 4 * 1024 * 1024   # 4 MB per chunk


def download(filename: str, base: str) -> None:
    url = base + filename
    dst = OUT_DIR / filename

    if dst.exists() and dst.stat().st_size > 200:
        print(f"  [skip] {filename}  (already downloaded)")
        return

    print(f"  [↓]  {filename}")
    print(f"       {url}")

    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            total   = int(r.headers.get("content-length", 0))
            written = 0
            with open(dst, "wb") as f:
                for chunk in r.iter_content(chunk_size=CHUNK):
                    f.write(chunk)
                    written += len(chunk)
                    if total > 0:
                        pct = written / total * 100
                        mb  = written / 1024 / 1024
                        print(f"\r       {pct:5.1f}%  {mb:7.1f} MB", end="", flush=True)
            print()
        print(f"       → {dst}  ({dst.stat().st_size / 1024 / 1024:.1f} MB)")

    except requests.HTTPError as e:
        print(f"\n  [ERROR] {e}")
        if dst.exists():
            dst.unlink()
        sys.exit(1)


if __name__ == "__main__":
    print("=" * 60)
    print(f"  SkillCorner Data Fetcher - Match {MATCH_ID}")
    print(f"  Brisbane Roar FC 0-1 Perth Glory FC  (2024-12-21)")
    print("=" * 60)
    print(f"\n  Output directory: {OUT_DIR.resolve()}\n")

    for fname, base_url in FILES.items():
        download(fname, base_url)

    print("\n  All files downloaded.")
    print(f"\n  Next step:")
    print(f"    python convert_skillcorner_to_pipeline.py")
