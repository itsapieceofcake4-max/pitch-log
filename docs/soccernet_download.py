# -*- coding: utf-8 -*-
"""
soccernet_download.py
=====================
SoccerNet データ取得スクリプト。

事前準備:
  1) NDA フォーム提出（映像DLに必要なパスワードがメールで届く）:
     https://docs.google.com/forms/d/e/1FAIpQLSfYFqjZNm4IgwGnyJXDPk2Ko_lZcbVtYX73w5lf6din5nxfmA/viewform
  2) pip install SoccerNet
  3) 映像を取る場合のみ、環境変数 SOCCERNET_PASSWORD に受領パスワードを設定。

使い方（例）:
  set SOCCERNET_PASSWORD=xxxxx        # 映像を取るときだけ
  python soccernet_download.py --dir D:\soccernet --tracking
  python soccernet_download.py --dir D:\soccernet --gamestate
  python soccernet_download.py --dir D:\soccernet --video      # 要パスワード

注意:
  - トラッキング/ゲーム状態の座標・アノテーションはパスワード不要。
  - 放送映像本体（*.mkv）だけ NDA パスワードが必要。
  - 容量が大きいので保存先 --dir は空き容量のあるドライブを指定する。
"""
import argparse
import os
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="保存先ディレクトリ")
    ap.add_argument("--tracking", action="store_true", help="トラッキング(tracking-2023)を取得")
    ap.add_argument("--gamestate", action="store_true", help="ゲーム状態復元(GSR)を取得")
    ap.add_argument("--video", action="store_true", help="放送映像(*.mkv)を取得（要パスワード）")
    ap.add_argument("--splits", nargs="+", default=["train", "valid", "test"],
                    help="取得split（既定: train valid test）")
    args = ap.parse_args()

    try:
        from SoccerNet.Downloader import SoccerNetDownloader
    except ImportError:
        sys.exit("SoccerNet 未インストール。`pip install SoccerNet` を実行してください。")

    dl = SoccerNetDownloader(LocalDirectory=args.dir)
    pw = os.environ.get("SOCCERNET_PASSWORD")
    if pw:
        dl.password = pw

    if args.tracking:
        # 放送由来トラッキング（座標・アノテーション）。パスワード不要。
        dl.downloadDataTask(task="tracking-2023",
                            split=["train", "test", "challenge"])

    if args.gamestate:
        # Game State Reconstruction（ミニマップ座標＋役割/番号）。
        # ※ task名は sn-gamestate リポジトリの "gamestate-2024" を使用。
        dl.downloadDataTask(task="gamestate-2024",
                            split=["train", "valid", "test", "challenge"])

    if args.video:
        if not pw:
            sys.exit("映像取得には SOCCERNET_PASSWORD（NDA受領パスワード）が必要です。")
        # 軽量版224p。HQが必要なら 1_720p.mkv / 2_720p.mkv に変更。
        dl.downloadGames(files=["1_224p.mkv", "2_224p.mkv"], split=args.splits)

    print("done.")


if __name__ == "__main__":
    main()
