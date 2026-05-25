"""
app_manual.py
=============
Pitch Log ドキュメント ビューア（Streamlit Cloud 公開用）

docs/ 配下の HTML ドキュメント（取扱説明書・カラムカタログ等）を
Streamlit アプリとして配信する薄いラッパー。

Run
---
  streamlit run app_manual.py
"""

from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# ── ページ設定 ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Pitch Log — ドキュメント",
    page_icon="📖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── ベーススタイル ──────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
      .stApp { background-color: #0e1825; }
      .main .block-container { padding: 0 !important; max-width: 100% !important; }
      header[data-testid="stHeader"] { background: transparent; }
      footer { visibility: hidden; }
      #MainMenu { visibility: hidden; }
      section[data-testid="stSidebar"] { background-color: #13202f; }
      section[data-testid="stSidebar"] * { color: #b0c8e0; }
      section[data-testid="stSidebar"] h1,
      section[data-testid="stSidebar"] h2,
      section[data-testid="stSidebar"] h3 { color: #e8f2ff !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ── ドキュメント一覧 ────────────────────────────────────────────────────────
DOCS_DIR = Path(__file__).parent / "docs"

DOCS = {
    "📖 取扱説明書 (v22 / v23 使い方)": {
        "file": "pitch-log-manual.html",
        "desc": "v22 / v23 の機能・操作・指標の意味を網羅した取説",
    },
    "📊 追加可能カラム カタログ": {
        "file": "feature-catalog.html",
        "desc": "GSA説明変数として CSV に追加できる全カラム候補一覧",
    },
}

# ── サイドバー ──────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 📚 Pitch Log Docs")
    st.markdown("ドキュメントを選択してください。")
    st.divider()

    doc_choice = st.radio(
        "ドキュメント",
        list(DOCS.keys()),
        label_visibility="collapsed",
    )

    st.caption(DOCS[doc_choice]["desc"])
    st.divider()

    st.markdown(
        """
        ### 🔗 関連アプリ

        - [v22 ビジュアライザ](https://pitch-log-22.streamlit.app/)
        - [v23 VAEP 分析](https://pitch-log-23.streamlit.app/)
        - [GitHub リポジトリ](https://github.com/itsapieceofcake4-max/pitch-log)

        ---

        ### 🖨 印刷

        ブラウザの **Ctrl+P** で
        モノクロ印刷用にレイアウトが
        自動調整されます。

        ---

        Pitch Log — Documentation
        """
    )


# ── HTML 読み込み・表示 ──────────────────────────────────────────────────
html_file = DOCS_DIR / DOCS[doc_choice]["file"]

if not html_file.exists():
    st.error(f"ドキュメントが見つかりません: `{html_file}`")
    st.info(
        "リポジトリの `docs/` 配下を確認してください。\n\n"
        "GitHub: https://github.com/itsapieceofcake4-max/pitch-log/tree/main/docs"
    )
    st.stop()

with open(html_file, encoding="utf-8") as f:
    html_content = f.read()

# iframe 内でフル HTML をレンダリング
components.html(html_content, height=6000, scrolling=True)
