"""
app_top.py
==========
Pitch Log — TOP ハブ

各アプリ(v22/v23/v24/取説)への入口を1枚に集約し、
アプリ比較(VERSIONS) と 変更履歴(CHANGELOG) も同居させる。

Run
---
  streamlit run app_top.py
"""
from pathlib import Path
import streamlit as st

st.set_page_config(page_title="Pitch Log — TOP", page_icon="⚽",
                   layout="wide", initial_sidebar_state="collapsed")

# デプロイURL（Streamlit Cloud）
URL = {
    "v22": "https://pitch-log-22.streamlit.app/",
    "v23": "https://pitch-log-23.streamlit.app/",
    "v24": "https://pitch-log-24.streamlit.app/",   # ※未デプロイなら share.streamlit.io で作成
    "manual": "https://pitch-log-manual.streamlit.app/",
    "github": "https://github.com/itsapieceofcake4-max/pitch-log",
}

st.markdown("""
<style>
.stApp, body { background:#0e1825 !important; color:#dde8f4 !important; }
h1,h2,h3,h4 { color:#fff !important; }
a { color:#5ec4ff !important; text-decoration:none; }
.card { background:#1a2e42; border:1px solid #234060; border-radius:14px;
  padding:20px 22px; height:100%; }
.card h3 { margin:0 0 .3em; }
.card p { color:#9abcda; font-size:.86rem; line-height:1.6; }
.badge { display:inline-block; background:#0f2540; color:#5ec4ff; font-size:.72rem;
  padding:2px 9px; border-radius:10px; margin-bottom:8px; }
.gobtn { display:inline-block; margin-top:12px; background:#2563eb; color:#fff !important;
  padding:8px 18px; border-radius:8px; font-weight:700; font-size:.9rem; }
.gobtn:hover { background:#1d4ed8; }
</style>
""", unsafe_allow_html=True)

st.markdown("<h1>⚽ Pitch Log — TOP</h1>"
            "<p style='color:#8b949e;margin-top:-6px'>"
            "サッカー戦術分析プラットフォーム｜アプリを選んで開始</p>",
            unsafe_allow_html=True)
st.divider()

# ── アプリ選択カード ──────────────────────────────────────────────────────────
cards = [
    ("v22", "🎬 シーンビューア", "30秒シーン",
     "22選手＋ボールのアニメ再生、xTヒートマップ、xTタイムライン、ゾーン評価。基本の可視化。"),
    ("v23", "📊 VAEP / 守備分析", "30秒シーン＋",
     "v22の全機能＋VAEP（攻撃/守備）、オフボールラン、守備ブレイクダウン、Δ xT。深掘り分析。"),
    ("v24", "📈 試合全体モメンタム", "試合全体90分",
     "xT addedベースのモメンタム、ピンチ/チャンス/ゴール抽出、区間選択でCSV。試合を俯瞰。"),
    ("manual", "📖 取扱説明書", "ドキュメント",
     "各アプリの使い方・指標の意味・追加可能カラムのカタログ。"),
]
cols = st.columns(4, gap="medium")
for col, (key, title, badge, desc) in zip(cols, cards):
    with col:
        st.markdown(
            f"<div class='card'><span class='badge'>{badge}</span>"
            f"<h3>{title}</h3><p>{desc}</p>"
            f"<a class='gobtn' href='{URL[key]}' target='_blank'>開く →</a></div>",
            unsafe_allow_html=True)

st.caption("※ v24 が開けない場合は未デプロイです（share.streamlit.io で app_24.py をデプロイ）。"
           "ローカルなら `streamlit run app_24.py`。")
st.markdown(f"🔗 [GitHub リポジトリ]({URL['github']})")
st.divider()

# ── VERSIONS / CHANGELOG ─────────────────────────────────────────────────────
ROOT = Path(__file__).parent


def show_md(path: Path, fallback: str):
    if path.exists():
        st.markdown(path.read_text(encoding="utf-8"))
    else:
        st.info(fallback)


tab_v, tab_c = st.tabs(["📋 アプリ比較（VERSIONS）", "🕒 変更履歴（CHANGELOG）"])
with tab_v:
    show_md(ROOT / "docs" / "VERSIONS.md", "docs/VERSIONS.md が見つかりません。")
with tab_c:
    show_md(ROOT / "CHANGELOG.md", "CHANGELOG.md が見つかりません。")
