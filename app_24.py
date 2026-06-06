"""
app_24.py
=========
Pitch Log v24 — 試合全体ビュー（Match Momentum & Key Moments）

90分（前後半）を1枚で俯瞰する全画面版。
ロジックは match_momentum.render_momentum() に集約（app_22/23 と共有）。

入力: match_phases_summary.csv  (build_match_phases.py が生成・リポジトリ同梱)

Run
---
  streamlit run app_24.py
"""
import streamlit as st
import match_momentum

st.set_page_config(page_title="Pitch Log — 試合全体", page_icon="⚽",
                   layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
.stApp, body { background:#0e1825 !important; color:#dde8f4 !important; }
h1,h2,h3,h4 { color:#fff !important; }
section[data-testid="stSidebar"] { background:#13202f !important; }
div[data-testid="stMetric"] { background:#1a2e42 !important; border:1px solid #234060 !important;
  border-radius:10px !important; padding:12px 16px !important; }
div[data-testid="stMetricValue"] { color:#5ec4ff !important; }
div[data-testid="stMetricLabel"] p { color:#7aaac8 !important; font-size:.72rem !important;
  text-transform:uppercase; letter-spacing:.06em; }
</style>
""", unsafe_allow_html=True)


def main():
    with st.sidebar:
        st.markdown("## ⚽ Pitch Log — 試合全体")
        st.markdown("**v24 | Match Momentum & Key Moments**")
        st.divider()
        path = st.text_input("フェーズ サマリーCSV", "match_phases_summary.csv")
        st.divider()
        st.caption("Home = Brisbane（青） / Away = Perth（赤）\n\n"
                   "モメンタム = **xT added**（各フェーズ ΔxT）。"
                   "xT は標準の Expected Threat 指標で、恣意的な重みを使わない一般的な指標です。")

    st.markdown("<h2 style='margin-bottom:0'>⚽ 試合モメンタム — Brisbane 0-1 Perth</h2>"
                "<p style='color:#8b949e;margin-top:2px;font-size:.85rem'>"
                "Isuzu UTE A-League 2024-25 R09 | 90分を1枚で俯瞰</p>", unsafe_allow_html=True)
    st.divider()

    match_momentum.render_momentum(path, key_prefix="mom24")


if __name__ == "__main__":
    main()
