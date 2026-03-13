# Vision AI

Vision AI is an AI-powered cryptocurrency trading research platform that combines real-time market data, machine learning predictions, sentiment analysis, technical indicators, and trading strategies into a single integrated system.

The system features a professional quant trading dashboard designed to give researchers and traders institutional-grade visibility into market conditions, AI signals, and active portfolio strategies.

---

## 🚀 Features

* **Real-Time Market Data**: Live BTC price charts, volume histograms, and order book depth streamed via Binance WebSockets.
* **AI Signal Predictions**: Machine learning models continuously predict short-term price movements alongside confidence scoring.
* **Market Regime Detection**: Classifies current market conditions (trend, volatility, risk state) to dynamically adapt active trading strategies.
* **Sentiment Analysis**: Aggregates and scores crypto market news using NLP (FinBERT) from multiple sources including CryptoPanic, NewsAPI, and Finnhub.
* **Strategy Breakdown**: Monitors active strategies (e.g., Momentum, Mean Reversion) and visualizes multi-factor signal strength.
* **Paper Trading Portfolio**: Risk-free execution engine that tracks performance metrics, win rates, and drawdowns.

---

## 🏗️ System Architecture

The platform follows a decoupled architecture:
1. **Data Ingestion Layer**: Fetches historical data (REST) and live tick data (WebSockets) while aggregating global financial news.
2. **Feature Engineering**: Calculates over 50 technical indicators and custom quantitative features based on the raw data.
3. **ML Pipeline**: Uses tree-based models and NLP transformers to predict future price horizons and assign signal confidence.
4. **Quant Engine**: Fuses AI signals with market regime classification to dynamically select the optimal trading strategy.
5. **Execution Loop**: Simulated paper trading execution that records transactions and manages virtual portfolio risk.
6. **Frontend Dashboard**: A React-based, low-latency UI that presents all metrics in a highly visual, institutional-style dark theme.

---

## 🛠️ Tech Stack

### Backend
* **Python** (Core Logic)
* **FastAPI** (REST API)
* **LightGBM** (Machine Learning)
* **FinBERT** (NLP Sentiment)
* **pandas & NumPy** (Data Processing)

### Frontend
* **React** (UI Framework)
* **lightweight-charts** (TradingView canvas charts)
* **WebSocket streams** (Real-time updates)

### Data Sources
* **Binance** (Price & Orderbook)
* **Finnhub** (Market News)
* **NewsAPI** (Global Headlines)
* **CryptoPanic** (Crypto News)
* **CoinGecko** (Trending Tokens)
* **Glassnode** (On-chain signals)

---

## ⚙️ Installation

### 1. Clone the repository
```bash
git clone https://github.com/abhinavsaha24/vision-ai.git
cd vision-ai
```

### 2. Set up the Python Backend
Create a virtual environment and install the dependencies:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Set up the React Frontend
Navigate to the dashboard directory and install node modules:
```bash
cd ai-trading-dashboard
npm install
```

---

## 🔐 Environment Variables

The project uses `.env` files to securely load API keys. 

1. Copy the example file to create your local `.env`:
```bash
cp .env.example .env
```
2. Open `.env` and fill in your keys (all except Binance are strictly necessary for full functionality, though CoinGecko and basic Binance endpoints work without keys):

```ini
HF_TOKEN=your_huggingface_token
FINNHUB_KEY=your_finnhub_key
NEWSAPI_KEY=your_newsapi_key
CRYPTOPANIC_TOKEN=your_cryptopanic_token
BINANCE_API_KEY=optional_binance_key
BINANCE_SECRET=optional_binance_secret
```
*Note: The `.env` file is excluded from git to prevent accidental key leaks.*

---

## 🏃‍♂️ Running the Project

You need two terminal windows to run both the backend API and the frontend UI.

### Running the Backend
In your first terminal (from the project root, with venv activated):
```bash
python -m src.database.init_database
python -m src.api.main
```
The FastAPI backend will start on `http://localhost:10000`.

### Running the Frontend
In your second terminal:
```bash
cd ai-trading-dashboard
npm start
```
The React development server will open the dashboard in your browser.

---

## 🔮 Future Improvements

* **Live Brokerage Execution**: Wiring the execution engine directly to Binance/Bybit API for live trading.
* **Deep Reinforcement Learning**: Adding RL agents (PPO/DQN) for dynamic portfolio weight optimization.
* **Options Pricing & Volatility Surface**: Expanding asset classes to include options and derivatives data.
* **Backtesting UI**: Building out a dedicated historical backtesting interface in the standalone dashboard.

---

## 👨‍💻 Author

Created by **Abhinav Saha**

* **GitHub**: [https://github.com/abhinavsaha24](https://github.com/abhinavsaha24)
* **LinkedIn**: [https://linkedin.com/in/abhinavsaha24](https://linkedin.com/in/abhinavsaha24)
* **Contact**: [abhinavsaha24@gmail.com](mailto:abhinavsaha24@gmail.com)
