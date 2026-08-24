"""
app_home.py
===========
Pitch Log — 全アプリの入口（マルチページ）

Streamlit Community Cloud の**非公開アプリは 1 つまで**なので、
アプリごとに別デプロイにすると限定公開にできるのが 1 つだけになってしまう。
ここで 1 本にまとめ、**1 つの URL・1 つの非公開枠**で全部を使えるようにする。

    streamlit run app_home.py

デプロイ時のメインファイルにもこれを指定する。
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

st.set_page_config(
    page_title="Pitch Log",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

from rugby import theme                                    # noqa: E402

theme.inject()


def home() -> None:
    """入口。どのアプリを使うかを選んでもらう。"""
    theme.header("Causal analysis for football  ·  因果でたどる選手の貢献")

    st.markdown(
        "左のメニューからアプリを選んでください。"
        "**重い抽出は手元の PC、閲覧はどこからでも**という作りにしてあります。"
    )

    c1, c2 = st.columns(2)
    with c1:
        theme.section("🏉 ラグビー映像トラッキング", "app_25")
        st.markdown(
            "トラッキングデータが無い競技向け。**上空映像だけ**から選手の位置を\n"
            "時系列データに起こします。\n\n"
            "- ピッチを 4 本の線で囲むだけでキャリブレーション\n"
            "- 走行距離・速度・スプリント、ボロノイによる空間支配\n"
            "- 2D タクティカルマップ（MP4）の書き出し"
        )
        st.caption(
            "長い試合映像はアプリ内で 40 秒に切り出してから使います"
            "（クラウドでは数 GB のアップロードができないため）。"
        )
    with c2:
        theme.section("⚽ PFF シーンブラウザ", "app_26")
        st.markdown(
            "PFF FC（FIFA World Cup 2022）のデータから、解析したいシーンを\n"
            "選んで書き出します。\n\n"
            "- 日本戦 4 試合のゴール・決定機を一覧から選択\n"
            "- 俯瞰 2D で 22 人＋ボールを再生\n"
            "- **425 指標**（X 物理量 / 中間Y / 最終Y）を付けて出力"
        )
        st.caption(
            "PFF の実データが無い環境では、書き出した CSV を読み込むモードで動きます。"
        )

    st.divider()
    theme.section("使い分け", "データの重さで扱いが変わります")
    st.markdown(
        """
| | 入力 | 会社 PC から見るには |
|---|---|---|
| **ラグビー** | 試合映像（数 GB） | 切り出した 40 秒クリップ（数十 MB）をアップロード |
| **PFF** | PFF データセット（数 GB・権利あり） | 書き出した CSV（1MB 未満）をアップロード |

どちらも「抽出は手元、閲覧はクラウド」という同じ形です。
手順は `docs/DEPLOY.md` を参照してください。
"""
    )


PAGES = [
    st.Page(home, title="ホーム", icon="🏠", default=True),
    st.Page("app_26.py", title="PFF シーンブラウザ", icon="⚽"),
    st.Page("app_25.py", title="ラグビー映像トラッキング", icon="🏉"),
]

st.navigation(PAGES).run()
