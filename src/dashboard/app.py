"""Streamlit dashboard for the AI trading system."""

import streamlit as st
import pandas as pd
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.data_collection.fetcher import DataFetcher
from src.feature_engineering.indicators import FeatureEngineer
from src.model_training.trainer import ModelTrainer
from src.backtesting.engine import BacktestEngine

st.set_page_config(
    page_title="AI Trading System",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for a professional look
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #1f77b4;
        margin-bottom: 1rem;
    }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        margin: 0.5rem 0;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<p class="main-header">📈 AI Trading System Dashboard</p>', unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.header("Configuration")
    symbol = st.text_input("Symbol", value="AAPL", help="Stock ticker symbol")
    period = st.selectbox(
        "Data Period",
        options=["1mo", "3mo", "6mo", "1y", "2y"],
        index=3,
    )
    st.divider()
    st.caption("Select a page from the tabs below")

# Main tabs
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Market Data",
    "📐 Features",
    "🤖 Model",
    "🔄 Backtest",
    "📋 Summary",
])

with tab1:
    st.subheader("Market Data")
    if st.button("Fetch Data", key="fetch"):
        with st.spinner("Fetching data..."):
            fetcher = DataFetcher()
            df = fetcher.fetch(symbol, period=period)
            if df is not None and not df.empty:
                st.line_chart(df["close"])
                st.dataframe(df.tail(20), use_container_width=True)
            else:
                st.error("No data found. Check symbol and connection.")

with tab2:
    st.subheader("Feature Engineering")
    if st.button("Generate Features", key="features"):
        with st.spinner("Generating features..."):
            fetcher = DataFetcher()
            df = fetcher.fetch(symbol, period=period)
            if df is not None and not df.empty:
                engineer = FeatureEngineer()
                features_df = engineer.add_all_indicators(df)
                st.success(f"Generated {len(features_df.columns)} features")
                st.dataframe(features_df.tail(20), use_container_width=True)
            else:
                st.error("No data found.")

with tab3:
    st.subheader("Model Training & Prediction")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Train Model", key="train"):
            with st.spinner("Training model..."):
                trainer = ModelTrainer()
                metrics = trainer.train_from_symbol(symbol, period=period)
                st.success("Model trained!")
                st.json(metrics)
    with col2:
        if st.button("Get Predictions", key="predict"):
            with st.spinner("Generating predictions..."):
                trainer = ModelTrainer()
                predictions = trainer.predict_from_symbol(symbol, period=period, horizon=5)
                st.success("Predictions ready!")
                st.json(predictions)

with tab4:
    st.subheader("Backtesting")
    initial_capital = st.number_input("Initial Capital ($)", value=100000.0, min_value=1000.0)
    if st.button("Run Backtest", key="backtest"):
        with st.spinner("Running backtest..."):
            engine = BacktestEngine(initial_capital=initial_capital)
            results = engine.run_from_symbol(symbol, period=period)
            st.success("Backtest complete!")
            col1, col2, col3, col4 = st.columns(4)
            total_ret = results.get("total_return", 0) * 100
            col1.metric("Total Return", f"{total_ret:.2f}%")
            col2.metric("Sharpe Ratio", f"{results.get('sharpe_ratio', 0):.2f}")
            col3.metric("Total Trades", results.get("num_trades", 0))
            col4.metric("Win Rate", f"{results.get('win_rate', 0) * 100:.1f}%")

with tab5:
    st.subheader("Pipeline Summary")
    st.markdown("""
    **Modules:**
    - **Data Collection**: Fetches OHLCV data via yfinance
    - **Feature Engineering**: Technical indicators (SMA, RSI, MACD, Bollinger)
    - **Model Training**: Random Forest classifier for direction prediction
    - **Backtesting**: Event-driven backtest with metrics
    - **API Server**: FastAPI REST endpoints
    - **Dashboard**: This Streamlit UI

    **Quick Start:**
    ```bash
    pip install -r requirements.txt
    python -m src.api.main          # API on :8000
    streamlit run src/dashboard/app.py  # Dashboard on :8501
    ```
    """)
