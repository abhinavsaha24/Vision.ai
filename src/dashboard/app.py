"""
Streamlit dashboard for Vision-AI trading platform.
Connects to the FastAPI backend for all data.
"""

import streamlit as st
import requests
import pandas as pd
import json
from datetime import datetime

# --------------------------------------------------
# Config
# --------------------------------------------------

API = "http://localhost:10000"

st.set_page_config(
    page_title="Vision-AI Trading Platform",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .main-header {font-size:2.5rem;font-weight:800;background:linear-gradient(90deg,#00d2ff,#7b2ff7);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:1rem}
    .metric-card {background:linear-gradient(135deg,#1a1a2e 0%,#16213e 100%);padding:1.2rem;border-radius:12px;border:1px solid #2a2a4a;margin:0.5rem 0}
    [data-testid="stMetricValue"] {font-size:1.3rem}
</style>
""", unsafe_allow_html=True)


def api_get(path):
    try:
        return requests.get(f"{API}{path}", timeout=10).json()
    except:
        return None


def api_post(path, data=None):
    try:
        return requests.post(f"{API}{path}", json=data or {}, timeout=30).json()
    except:
        return None


# --------------------------------------------------
# Sidebar
# --------------------------------------------------

with st.sidebar:
    st.markdown('<p class="main-header">🧠 Vision-AI</p>', unsafe_allow_html=True)
    st.caption("Professional AI Trading Platform")
    st.divider()

    symbol = st.selectbox("Symbol", ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"])

    st.divider()
    st.subheader("Quick Actions")

    if st.button("🔄 Refresh All", use_container_width=True):
        st.rerun()

    if st.button("🧠 Train Model", use_container_width=True):
        with st.spinner("Training..."):
            result = api_post("/model/train", {"symbol": symbol})
            if result:
                st.success(f"✅ Trained — Accuracy: {result.get('metrics', {}).get('accuracy', 'N/A')}")

    health = api_get("/health")
    if health:
        st.success(f"API: Healthy")
    else:
        st.error("API: Offline")


# --------------------------------------------------
# Main Tabs
# --------------------------------------------------

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 Trading", "📈 Backtest", "🎯 Regime", "💬 Sentiment", "⚠️ Risk", "🔬 Research"
])

# --------------------------------------------------
# Tab 1: Trading Intelligence
# --------------------------------------------------

with tab1:
    st.subheader("AI Trading Intelligence")

    pred = api_post("/model/predict", {"symbol": symbol, "horizon": 5})

    if pred:
        col1, col2, col3, col4 = st.columns(4)

        signal = pred.get("signal", "HOLD")
        signal_color = "🟢" if signal == "BUY" else "🔴" if signal == "SELL" else "🟡"

        col1.metric("Signal", f"{signal_color} {signal}")
        col2.metric("Confidence", f"{pred.get('confidence', 0) * 100:.1f}%")
        col3.metric("Signal Score", f"{pred.get('signal_score', 0):.3f}")
        col4.metric("Position Size", f"{pred.get('position_size', 0):.3f}")

        # Signal breakdown
        st.subheader("Signal Components")
        components = pred.get("components", {})
        if components:
            comp_df = pd.DataFrame([
                {"Signal": k, "Value": "Bullish" if v == 1 else "Bearish" if v == -1 else "Neutral"}
                for k, v in components.items()
            ])
            st.dataframe(comp_df, use_container_width=True, hide_index=True)

        # Predictions
        preds_list = pred.get("predictions", [])
        if preds_list:
            st.subheader("Multi-Step Predictions")
            st.dataframe(pd.DataFrame(preds_list), use_container_width=True, hide_index=True)

        # Strategy
        strategy = pred.get("strategy", {})
        if strategy:
            st.subheader("Strategy")
            st.json(strategy)
    else:
        st.warning("No predictions available — train model first")


# --------------------------------------------------
# Tab 2: Backtesting
# --------------------------------------------------

with tab2:
    st.subheader("Backtesting Engine")

    initial_cap = st.number_input("Initial Capital ($)", value=100000.0, min_value=1000.0)

    if st.button("▶️ Run Backtest", use_container_width=True):
        with st.spinner("Running backtest..."):
            result = api_post("/backtest/run", {
                "symbol": symbol, "initial_capital": initial_cap
            })

            if result and "results" in result:
                r = result["results"]

                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Total Return", f"{r.get('total_return', 0) * 100:.2f}%")
                col2.metric("Sharpe Ratio", f"{r.get('sharpe_ratio', 0):.2f}")
                col3.metric("Sortino Ratio", f"{r.get('sortino_ratio', 0):.2f}")
                col4.metric("Win Rate", f"{r.get('win_rate', 0) * 100:.1f}%")

                col5, col6, col7, col8 = st.columns(4)
                col5.metric("Max Drawdown", f"{r.get('max_drawdown', 0) * 100:.2f}%")
                col6.metric("Profit Factor", f"{r.get('profit_factor', 0):.2f}")
                col7.metric("Calmar Ratio", f"{r.get('calmar_ratio', 0):.2f}")
                col8.metric("Total Trades", r.get("num_trades", 0))

                # Trade history
                trades = r.get("trades", [])
                if trades:
                    st.subheader("Recent Trades")
                    st.dataframe(pd.DataFrame(trades[-20:]), use_container_width=True, hide_index=True)
            else:
                st.error("Backtest failed")


# --------------------------------------------------
# Tab 3: Market Regime
# --------------------------------------------------

with tab3:
    st.subheader("Market Regime Detection")

    sym_api = symbol.replace("USDT", "/USDT")
    regime = api_get(f"/regime/current?symbol={sym_api}")

    if regime:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Trend", regime.get("trend", "--"))
        col2.metric("Volatility", regime.get("volatility", "--"))
        col3.metric("Risk", regime.get("risk", "--"))
        col4.metric("Label", regime.get("label", "--"))
    else:
        st.info("Regime data unavailable")


# --------------------------------------------------
# Tab 4: Sentiment
# --------------------------------------------------

with tab4:
    st.subheader("News Sentiment Analysis")

    sentiment = api_get("/sentiment/current")

    if sentiment:
        col1, col2, col3 = st.columns(3)

        score = sentiment.get("score", 0)
        label = sentiment.get("label", "neutral")
        emoji = "🟢" if label == "bullish" else "🔴" if label == "bearish" else "🟡"

        col1.metric("Score", f"{score:.4f}")
        col2.metric("Label", f"{emoji} {label.title()}")
        col3.metric("News Count", sentiment.get("count", 0))

        # Details
        details = sentiment.get("details", [])
        if details:
            st.subheader("Headlines")
            st.dataframe(pd.DataFrame(details[:15]), use_container_width=True, hide_index=True)
    else:
        st.info("Sentiment data unavailable")


# --------------------------------------------------
# Tab 5: Risk Dashboard
# --------------------------------------------------

with tab5:
    st.subheader("Risk Management Dashboard")

    risk = api_get(f"/risk/status?symbol={sym_api}")

    if risk:
        col1, col2, col3 = st.columns(3)

        risk_level = risk.get("risk_level", "unknown")
        risk_emoji = "🔴" if risk_level == "high" else "🟡" if risk_level == "medium" else "🟢"

        col1.metric("Risk Level", f"{risk_emoji} {risk_level.title()}")
        col2.metric("Risk Score", f"{risk.get('risk_score', 0):.4f}")
        col3.metric("Kill Switch", "🔴 ACTIVE" if risk.get("kill_switch") else "🟢 Off")

        # Factors
        factors = risk.get("factors", {})
        if factors:
            st.subheader("Risk Factors")
            st.json(factors)

        # Events
        events = risk.get("events", [])
        if events:
            st.subheader("Recent Events")
            st.dataframe(pd.DataFrame(events[-10:]), use_container_width=True, hide_index=True)
    else:
        st.info("Risk data unavailable")


# --------------------------------------------------
# Tab 6: Research
# --------------------------------------------------

with tab6:
    st.subheader("Alpha Research")

    importance = api_get("/research/feature-importance")

    if importance and "importance" in importance:
        imp = importance["importance"]

        st.subheader("Feature Importance (Top 20)")
        df_imp = pd.DataFrame([
            {"Feature": k, "Importance": v}
            for k, v in imp.items()
        ])
        st.bar_chart(df_imp.set_index("Feature"))

    # Strategies
    strategies = api_get("/strategies/list")
    if strategies and "strategies" in strategies:
        st.subheader("Active Strategies")
        st.dataframe(pd.DataFrame(strategies["strategies"]), use_container_width=True, hide_index=True)
