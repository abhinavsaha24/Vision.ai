# Vision AI — System Architecture

## Overview

Vision AI is an institutional-grade algorithmic trading platform built for crypto markets. The system combines advanced ML models, quantitative signal engines, and robust execution infrastructure into a modular, production-ready platform.

---

## Architecture Diagram

```mermaid
graph TB
    subgraph Frontend["Frontend (Vercel)"]
        REACT[React Dashboard]
    end

    subgraph API["API Layer"]
        FASTAPI[FastAPI Server]
        AUTH[Auth Service]
    end

    subgraph Core["Core Trading Engine"]
        STRAT[Strategy Engine — 9 strategies + stat arb]
        EXEC[Execution Engine — market / limit / TWAP / VWAP]
        RISK[Risk Manager — VaR, drawdown, kill switch]
        PORT[Portfolio Manager — Kelly, MV, RP, HRP]
    end

    subgraph ML["ML Pipeline"]
        FEAT[Feature Engine — 60+ indicators]
        MODELS[Model Ensemble — RF + XGB + LGB + LSTM + Transformer]
        REGIME[Regime Detector — HMM + GMM]
    end

    subgraph Exchange["Exchange Layer"]
        ADAPTER{Exchange Adapter}
        PAPER[Paper Adapter]
        BINANCE[Binance Adapter via ccxt]
        ORDERS[Order Manager]
    end

    subgraph Infra["Infrastructure"]
        LOGGER[Structured Logger — JSON + correlation IDs]
        HEALTH[Health Monitor — component checks]
        REDIS[(Redis Cache)]
        PG[(PostgreSQL)]
    end

    REACT --> FASTAPI
    FASTAPI --> AUTH
    FASTAPI --> Core
    FASTAPI --> ML

    STRAT --> EXEC
    EXEC --> RISK
    RISK --> PORT
    EXEC --> ORDERS
    ORDERS --> ADAPTER
    ADAPTER --> PAPER
    ADAPTER --> BINANCE

    FEAT --> MODELS
    MODELS --> REGIME

    Core --> LOGGER
    Core --> HEALTH
    FASTAPI --> REDIS
    ORDERS --> PG
```

---

## Module Map

| Module | Path | Responsibility |
|---|---|---|
| Core | `backend/src/core/` | Config, structured logging, health monitoring |
| Data | `backend/src/data/` | Market data ingestion, caching, normalization |
| Features | `backend/src/features/` | 60+ technical indicators and feature selection |
| Models | `backend/src/models/` | ML training, ensemble, regime detection, model registry |
| Research | `backend/src/research/` | Backtesting, alpha research, walk-forward validation |
| Strategy | `backend/src/strategy/` | 10 signal strategies including stat arb |
| Execution | `backend/src/execution/` | Order execution, order management, live safety |
| Risk | `backend/src/risk/` | Risk scoring, limits, VaR, kill switch |
| Portfolio | `backend/src/portfolio/` | Position tracking, optimization (Kelly, MV, RP, HRP) |
| Exchange | `backend/src/exchange/` | Abstract adapter — paper and Binance implementations |
| Sentiment | `backend/src/sentiment/` | FinBERT NLP, multi-source news aggregation |
| API | `backend/src/api/` | FastAPI REST endpoints (28+ routes) |
| Workers | `backend/src/workers/` | Background trading loop |
| Database | `backend/src/database/` | PostgreSQL persistence layer |
| Auth | `backend/src/auth/` | JWT authentication service |

---

## Deployment

| Component | Platform | Config |
|---|---|---|
| Frontend | Vercel | `frontend/ai-trading-dashboard/` |
| Backend API | Render / Docker | `deployment/Dockerfile` |
| Database | PostgreSQL 15 | `deployment/docker-compose.yml` |
| Cache | Redis 7 | `deployment/docker-compose.yml` |

### Quick Start

```bash
# Development
python -m backend.src.api.main

# Docker
cd deployment && docker-compose up --build

# Tests
python -m pytest tests/ -v
```

---

## API Endpoints (28+)

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | System health |
| `/health/detailed` | GET | Component-level health |
| `/data/fetch` | POST | Fetch market data |
| `/features/generate` | POST | Generate features |
| `/model/train` | POST | Train ML models |
| `/model/predict` | POST | AI prediction + quant signals |
| `/model/registry` | GET | Model version history |
| `/backtest/run` | POST | Run backtest |
| `/portfolio/status` | GET | Portfolio state |
| `/portfolio/performance` | GET | Performance metrics |
| `/regime/current` | GET | Market regime |
| `/sentiment/current` | GET | News sentiment |
| `/risk/status` | GET | Risk dashboard |
| `/strategies/list` | GET | Available strategies |
| `/paper-trading/start` | POST | Start paper trading |
| `/paper-trading/stop` | POST | Stop paper trading |
| `/paper-trading/status` | GET | Paper trading metrics |
| `/live-trading/preflight` | GET | Safety pre-flight checks |
| `/live-trading/enable` | POST | Enable live trading |
| `/orders/active` | GET | Active orders |
| `/orders/history` | GET | Order history |
| `/news` | GET | Aggregated news |
| `/market-intelligence` | GET | Trending tokens |
| `/research/feature-importance` | GET | Feature importance |
