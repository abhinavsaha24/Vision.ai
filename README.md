# AI Trading System

A modular Python project for AI-driven trading with data collection, feature engineering, model training, backtesting, API server, and dashboard.

## Project Structure

```
ai-trading-system/
├── config/                 # Configuration
├── src/
│   ├── data_collection/    # yfinance: timeframes, pagination, clean chronological data
│   ├── feature_engineering/# Technical + candle/volume/momentum/slope features (no leakage)
│   ├── evaluation/          # Classification & trading metrics (F1, Sharpe, profit factor, etc.)
│   ├── model_training/     # RF + XGBoost + LightGBM, TimeSeriesSplit CV, ensemble
│   ├── backtesting/        # Event-driven backtest; model or RSI signals
│   ├── api/                # FastAPI REST server
│   └── dashboard/          # Streamlit UI
├── scripts/
│   └── run_pipeline.py     # fetch → features → split → train → predict → backtest → report
├── data/                   # Cached data (runtime)
├── models/                 # Saved models (runtime)
├── requirements.txt
└── README.md
```

## Setup

```bash
cd ai-trading-system
pip install -r requirements.txt
```

## Usage

### Run full pipeline (CLI)

```bash
python scripts/run_pipeline.py --symbol AAPL --period 1y
# Optional: --interval 1d|1wk|1mo --test-size 0.2 --target-horizon 5
```

### API server

```bash
python -m src.api.main
# or: uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
```

API docs: http://localhost:8000/docs

**Endpoints:**
- `POST /data/fetch` - Fetch OHLCV data
- `POST /features/generate` - Generate technical indicators
- `POST /model/train` - Train prediction model
- `POST /model/predict` - Get direction predictions
- `POST /backtest/run` - Run backtest

### Dashboard

```bash
streamlit run src/dashboard/app.py
```

Opens at http://localhost:8501

## Modules

| Module | Description |
|--------|-------------|
| **data_collection** | OHLCV via yfinance; configurable interval, pagination, timestamp normalization, chronological |
| **feature_engineering** | Candle structure, volume, momentum, trend slope, SMA/EMA, RSI, MACD, Bollinger; numerically stable, past-only |
| **evaluation** | Accuracy, precision, recall, F1, confusion matrix; Sharpe, win rate, profit factor, max drawdown |
| **model_training** | RF (500 trees, tuned), XGBoost, LightGBM; TimeSeriesSplit CV; ensemble (0.3/0.4/0.3) probability predictions |
| **backtesting** | Event-driven backtest; signals from model probabilities or RSI |
| **api** | FastAPI REST API for data, features, train, predict, backtest |
| **dashboard** | Streamlit UI |

## Configuration

Edit `config/settings.py` for:
- Default symbols and periods
- Model hyperparameters
- Backtest parameters (commission, position size)

## License

MIT
