"""
app_manual.py
=============
Pitch Log 取扱説明書 ビューア（Streamlit Cloud 公開用）

docs/pitch-log-manual.html を Streamlit アプリとして配信する薄いラッパー。
share.streamlit.io にデプロイすることで、社内・外問わずブラウザで参照できる。

Run
---
  streamlit run app_manual.py
"""

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# ── ページ設定 ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Pitch Log — 取扱説明書",
    page_icon="📖",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── ベーススタイル（余白・背景を取説に合わせる） ────────────────────────────
st.markdown(
    """
    <style>
      .stApp { background-color: #0e1825; }
      .main .block-container { padding: 0 !important; max-width: 100% !important; }
      header[data-testid="stHeader"] { background: transparent; }
      footer { visibility: hidden; }
      #MainMenu { visibility: hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── HTML 読み込み ──────────────────────────────────────────────────────────
HTML_PATH = Path(__file__).parent / "docs" / "pitch-log-manual.html"

if not HTML_PATH.exists():
    st.error(f"取扱説明書ファイルが見つかりません: `{HTML_PATH}`")
    st.info(
        "リポジトリの `docs/pitch-log-manual.html` を確認してください。\n\n"
        "GitHub: https://github.com/itsapieceofcake4-max/pitch-log/blob/main/docs/pitch-log-manual.html"
    )
    st.stop()

with open(HTML_PATH, encoding="utf-8") as f:
    html_content = f.read()

# ── 表示（iframe 内でフル HTML をレンダリング） ────────────────────────────
# height は十分に大きく取り、scrolling=True で内部スクロールさせる
components.html(html_content, height=6000, scrolling=True)

# ── サイドバー（補助情報・コンパクト） ──────────────────────────────────────
with st.sidebar:
    st.markdown("## 📖 Pitch Log 取扱説明書")
    st.markdown(
        """
        本書は v22 / v23 の使い方をまとめた取扱説明書です。

        ---

        **関連リンク**

        - [v22 アプリ](https://pitch-log-22.streamlit.app/) — ピッチビジュアライザ
        - [v23 アプリ](https://pitch-log-23.streamlit.app/) — VAEP 貢献度分析
        - [GitHub リポジトリ](https://github.com/itsapieceofcake4-max/pitch-log)
        - [HTML 単体表示](https://raw.githack.com/itsapieceofcake4-max/pitch-log/main/docs/pitch-log-manual.html)

        ---

        **印刷したい場合**

        ブラウザの印刷機能 (Ctrl+P) を使うと、
        モノクロ印刷用にレイアウトが自動調整されます。

        ---

        Pitch Log — v22 / v23 Manual
        """
    )
