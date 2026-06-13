# -*- coding: utf-8 -*-
"""
soccernet_inspect.py
====================
SoccerNet GSR (gamestate) zip を展開して構成・アノテーション形式を確認する。

使い方:
  python soccernet_inspect.py --zip C:\soccernet\gamestate-2024\test.zip
  python soccernet_inspect.py --dir C:\soccernet\gamestate-2024\test   # 展開済みなら

GSR の各シーケンス:
  SNGS-xxx/  ├ img1/*.jpg（フレーム）
             ├ Labels-GameState.json（ピッチ較正＋選手座標・役割/番号/チーム）
             ├ gameinfo.ini / seqinfo.ini
"""
import argparse
import json
import os
import zipfile


def find_first(path, name):
    for root, _, files in os.walk(path):
        if name in files:
            return os.path.join(root, name)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", help="展開する zip")
    ap.add_argument("--dir", help="展開済みディレクトリ")
    args = ap.parse_args()

    base = args.dir
    if args.zip:
        outdir = os.path.dirname(args.zip)
        cand = args.zip[:-4]  # 例: .../test
        if not os.path.isdir(cand) and not any(
                d.startswith("SNGS") for d in os.listdir(outdir)
                if os.path.isdir(os.path.join(outdir, d))):
            print(f"展開中: {args.zip} -> {outdir}")
            with zipfile.ZipFile(args.zip) as z:
                z.extractall(outdir)
        # GSR は zip 直下に SNGS-* を flat 展開する場合がある → 親を自動判定
        base = cand if os.path.isdir(cand) else outdir
    if not base or not os.path.isdir(base):
        print("対象ディレクトリが見つかりません。--zip か --dir を指定してください。")
        return

    # シーケンス一覧
    seqs = sorted([d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))])
    print(f"\nシーケンス数: {len(seqs)}")
    print("例:", seqs[:5])

    # 先頭シーケンスの構成
    if not seqs:
        return
    s0 = os.path.join(base, seqs[0])
    print(f"\n--- {seqs[0]} の中身 ---")
    for item in sorted(os.listdir(s0)):
        p = os.path.join(s0, item)
        if os.path.isdir(p):
            n = len(os.listdir(p))
            print(f"  [dir] {item}/  ({n} files)")
        else:
            print(f"  [file] {item}  ({os.path.getsize(p)//1024} KB)")

    # アノテーション JSON のプレビュー
    jpath = find_first(base, "Labels-GameState.json")
    if not jpath:
        print("\nLabels-GameState.json が見つかりません。")
        return
    print(f"\n--- アノテーション: {jpath} ---")
    with open(jpath, encoding="utf-8") as f:
        data = json.load(f)
    print("トップレベルkey:", list(data.keys()))
    for k in ("images", "annotations", "categories"):
        if k in data:
            print(f"  {k}: {len(data[k])} 件")
    # 選手アノテーションのサンプル（座標・役割・番号・チーム）
    anns = data.get("annotations", [])
    sample = next((a for a in anns if a.get("attributes", {}).get("role")), anns[0] if anns else None)
    if sample:
        print("\nサンプル annotation:")
        for k in ("image_id", "track_id", "supercategory", "category_id",
                  "bbox_image", "bbox_pitch", "attributes"):
            if k in sample:
                print(f"  {k}: {sample[k]}")


if __name__ == "__main__":
    main()
