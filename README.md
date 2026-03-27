# Vision AI

Vision AI is an AI-powered cryptocurrency trading research platform that combines real-time market data, machine learning predictions, sentiment analysis, technical indicators, and trading strategies into a single integrated system.

The system features a professional quant trading dashboard designed to give researchers and traders institutional-grade visibility into market conditions, AI signals, and active portfolio strategies.

---

## 🚀 Features

- **Real-Time Market Data**: Live BTC price charts, volume histograms, and order book depth streamed via Binance WebSockets.
- **AI Signal Predictions**: Machine learning models continuously predict short-term price movements alongside confidence scoring.
- **Market Regime Detection**: Classifies current market conditions (trend, volatility, risk state) to dynamically adapt active trading strategies.
- **Sentiment Analysis**: Aggregates and scores crypto market news using NLP (FinBERT) from multiple sources including CryptoPanic, NewsAPI, and Finnhub.
- **Strategy Breakdown**: Monitors active strategies (e.g., Momentum, Mean Reversion) and visualizes multi-factor signal strength.
- **Paper Trading Portfolio**: Risk-free execution engine that tracks performance metrics, win rates, and drawdowns.

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

- **Python** (Core Logic)
- **FastAPI** (REST API)
- **LightGBM** (Machine Learning)
- **FinBERT** (NLP Sentiment)
- **pandas & NumPy** (Data Processing)

### Frontend

- **React** (UI Framework)
- **lightweight-charts** (TradingView canvas charts)
- **WebSocket streams** (Real-time updates)

### Data Sources

- **Binance** (Price & Orderbook)
- **Finnhub** (Market News)
- **NewsAPI** (Global Headlines)
- **CryptoPanic** (Crypto News)
- **CoinGecko** (Trending Tokens)
- **Glassnode** (On-chain signals)

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
cd frontend
npm install
```

---

## 🔐 Environment Variables

The project uses `.env` files to securely load API keys.

1. Copy the example file to create your local `.env`:

```bash
cp .env.example .env
```

2. Open `.env` and fill in values. Production and local containers use DB component variables as the single source of truth:

```ini
# Core runtime
API_PORT=8080
LOG_LEVEL=INFO
ALLOW_PUBLIC_SIGNUP=false
AUTH_LOCKOUT_THRESHOLD=5
AUTH_LOCKOUT_WINDOW_SECONDS=300
AUTH_LOCKOUT_DURATION_SECONDS=900
MFA_STEP_UP_ENABLED=false
MFA_TOTP_SECRET=base32_totp_secret_when_enabled
SESSION_COOKIE_NAME=vision_ai_token
SESSION_COOKIE_MAX_AGE_SECONDS=604800
# SESSION_COOKIE_SECURE=true

# Database (single source of truth)
DB_HOST=localhost
DB_PORT=5432
DB_NAME=vision_core
DB_USER=vision
DB_PASSWORD=change_me

# Optional override (if set, this takes precedence)
# DATABASE_URL=postgresql://vision:change_me@localhost:5432/vision_core

# Optional data/news integrations
HF_TOKEN=your_huggingface_token
FINNHUB_KEY=your_finnhub_key
NEWSAPI_KEY=your_newsapi_key
CRYPTOPANIC_TOKEN=your_cryptopanic_token
BINANCE_API_KEY=optional_binance_key
BINANCE_SECRET=optional_binance_secret
```

_Note: The `.env` file is excluded from git to prevent accidental key leaks._

---

## 🏃‍♂️ Running the Project

Canonical production-like local run (recommended):

```bash
docker compose -f deployment/docker-compose.quant.yml up --build
```

This starts API + trading + risk + execution workers with Redis and Postgres, and exposes API on `http://localhost:8080`.

Alternative local development mode (without Docker) uses two terminal windows.

### One-Command Run Profiles (Second Pass)

PowerShell run profiles are available for reliable mode switching:

```powershell
# Local-only mode (backend + frontend)
./scripts/start_local_dev.ps1

# Public demo mode (backend + frontend + two localtunnel sessions)
./scripts/start_public_demo.ps1

# Stop all processes started by the scripts above
./scripts/stop_demo_sessions.ps1
```

What these profiles enforce:

- Local mode keeps API and WS on loopback.
- Public demo mode creates separate public URLs for frontend and backend, then injects backend `wss://` endpoint into frontend startup to keep realtime channels live.
- PIDs are tracked in `.runtime/` for deterministic shutdown.

### Running the Backend

In your first terminal (from the project root, with venv activated):

```bash
python -m backend.src.platform.api_service
```

The FastAPI backend will start on `http://localhost:8080`.

### Running the Frontend

In your second terminal:

```bash
cd frontend
npm install
npm run dev
```

The React development server will open the dashboard in your browser.

Set frontend runtime env in `frontend/.env.local`:

```ini
NEXT_PUBLIC_API_URL=http://localhost:8080
NEXT_PUBLIC_WS_URL=ws://localhost:8080
```

For public demos, do not hardcode localhost WS URL in frontend startup. Use `scripts/start_public_demo.ps1` so frontend receives the tunnel-based backend `wss://` URL automatically.

---

## Production Deploy Quickstart (Render + Vercel)

### Backend (Render)

1. Build command:

```bash
pip install -r requirements.txt
```

2. Start command:

```bash
uvicorn backend.src.api.main:app --host 0.0.0.0 --port 8080
```

3. Required env vars:

```ini
JWT_SECRET=<min_32_chars>
ENVIRONMENT=production
DB_HOST=<db-host>
DB_PORT=5432
DB_NAME=vision_core
DB_USER=vision
DB_PASSWORD=<strong-password>
SESSION_COOKIE_SECURE=true
ALLOW_PUBLIC_SIGNUP=false
AUTH_LOCKOUT_THRESHOLD=5
AUTH_LOCKOUT_WINDOW_SECONDS=300
AUTH_LOCKOUT_DURATION_SECONDS=900
TRADING_MODE=paper
LIVE_TRADING_ENABLED=false
CORS_ALLOWED_ORIGINS=https://<your-vercel-domain>,https://*.vercel.app
CORS_ALLOW_ORIGIN_REGEX=https://.*\.vercel\.app
WS_REQUIRE_ORIGIN_HEADER=true
WS_ALLOW_QUERY_TOKEN=false
```

### Frontend (Vercel)

Set:

```ini
NEXT_PUBLIC_API_URL=https://<your-render-backend>.onrender.com
NEXT_PUBLIC_WS_URL=wss://<your-render-backend>.onrender.com
# Keep query-token websocket fallback disabled unless migrating legacy clients:
# NEXT_PUBLIC_WS_QUERY_TOKEN_FALLBACK=false
```

### Readiness checks

After deploy, validate:

- `/health`
- `/system/readiness` (authenticated)
- authenticated websocket using Authorization/cookie/subprotocol auth

---

## Institutional Microservices Stack (New)

The repository now includes a production-oriented, event-driven architecture that separates API, trading engine, risk engine, and execution engine into independently scalable services.

## Institutional Architecture Artifacts

Execution-grade planning and governance documents are available under `docs/`:

- `docs/blackrock_architecture_blueprint.md`
- `docs/blackrock_phase_execution_tracker.md`
- `docs/blackrock_controls_evidence_matrix.md`
- `docs/blackrock_validation_playbook.md`
- `docs/blackrock_raci_matrix.md`
- `docs/institutional_transformation_master_plan_2026_03_27.md`

- Canonical API service: `backend.src.api.main:app`
- Trading worker: `backend.src.platform.workers.trading_engine`
- Risk worker: `backend.src.platform.workers.risk_engine`
- Execution worker: `backend.src.platform.workers.execution_engine`
- Queue: Redis Streams (`events.trading`, `events.execution`)
- Durable storage: PostgreSQL

Use the dedicated local compose stack:

```bash
docker compose -f deployment/docker-compose.quant.yml up --build
```

Detailed runbook and deployment notes:

- `docs/institutional_microservices_refactor.md`
- `deployment/Dockerfile.quant`
- `fly.toml`

Institutional readiness baseline scoring can be generated via:

```bash
python scripts/institutional_readiness_assessor.py --repo . --output data/institutional_readiness_report.json
```

---

## ✅ CI/CD Quality Gates

GitHub Actions workflow: `.github/workflows/ci.yml`

The pipeline runs on every push/PR and fails on any error in:

- Backend tests: `pytest -q`
- Python dependency health: `pip check`
- Python security audit: `pip_audit`
- Frontend lint: `npm run lint`
- Frontend build: `npm run build`
- Frontend route smoke tests: `npm run test:routes`
- Frontend security audit: `npm audit --omit=dev --audit-level=moderate`

Repository release workflow and branch model are documented in:

- `docs/release_branching_strategy.md`

---

## 🔮 Future Improvements

- **Live Brokerage Execution**: Wiring the execution engine directly to Binance/Bybit API for live trading.
- **Deep Reinforcement Learning**: Adding RL agents (PPO/DQN) for dynamic portfolio weight optimization.
- **Options Pricing & Volatility Surface**: Expanding asset classes to include options and derivatives data.
- **Backtesting UI**: Building out a dedicated historical backtesting interface in the standalone dashboard.

---

## 👨‍💻 Author

Created by **Abhinav Saha**

- **GitHub**: [https://github.com/abhinavsaha24](https://github.com/abhinavsaha24)
- **LinkedIn**: [https://linkedin.com/in/abhinavsaha24](https://linkedin.com/in/abhinavsaha24)
- **Contact**: [abhinavsaha24@gmail.com](mailto:abhinavsaha24@gmail.com)
