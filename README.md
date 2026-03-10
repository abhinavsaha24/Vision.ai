# Vision-AI 

Vision-AI is an AI-powered quantitative trading dashboard for crypto markets.

Features:
• Real-time crypto market data
• AI trading predictions
• Strategy backtesting engine
• Portfolio simulation
• Risk management system
• Trading dashboard with charts

Tech Stack:
Python
FastAPI
React
Scikit-Learn
LightGBM
XGBoost
CCXT
WebSockets

Architecture:
Frontend → React Dashboard
Backend → FastAPI ML API
Data → Binance + ML pipeline

Goal:
Build a research-grade quant trading platform similar to hedge-fund tools    
************backend************
https://vision-ai-5qm1.onrender.com/    

**********frontend********
https://vision-ai-omega-umber.vercel.app/

Vision-AI — AI Quantitative Trading Platform
Overview

Vision-AI is a full-stack AI-powered quantitative trading platform designed to analyze financial markets, generate predictive signals, simulate strategies, and eventually execute automated trades.

The system combines machine learning, quantitative finance, real-time market data, and a modern trading dashboard to create a research-grade trading environment similar to platforms used by professional quant firms.

Vision-AI integrates:

real-time crypto market data

machine learning prediction models

algorithmic trading strategies

portfolio analytics

backtesting engine

risk management system

interactive trading dashboard

The long-term goal is to evolve Vision-AI into a fully automated AI-driven trading infrastructure capable of real-time strategy execution and portfolio optimization.

System Architecture
React Dashboard (Frontend)
        │
        ▼
FastAPI Trading API
        │
        ▼
Strategy Engine
        │
 ┌──────────────┬──────────────┬──────────────┐
 ▼              ▼              ▼
Market Data   AI Models     News Sentiment
(Binance WS)  (ML Pipeline) (NLP Engine)
        │
        ▼
Risk Management
        │
        ▼
Execution Engine
        │
        ▼
Exchange Gateway (Binance)
Current Progress
Frontend (React Trading Dashboard)

Implemented:

Candlestick trading chart

Order book visualization

Portfolio panel

Watchlist

Risk dashboard

PnL analytics

Strategy performance panel

Trade history

AI prediction panel

Market timeline

News feed

Deployment:

Frontend hosted on Vercel
Backend (FastAPI)

Implemented API services:

GET  /health
POST /data/fetch
POST /features/generate
POST /model/train
POST /model/predict
POST /backtest/run

Backend includes:

feature engineering engine

model training pipeline

prediction service

backtesting system

strategy engine

risk manager

portfolio manager

Deployment:

Backend deployable on Render
Machine Learning Pipeline

Current model:

RandomForest

Planned ensemble:

RandomForest
XGBoost
LightGBM
LSTM
Transformer models

The AI system will combine predictions using ensemble voting and probability aggregation to generate high-confidence trading signals.

Strategy Engine

Currently implemented strategies:

AI prediction strategy
Momentum strategy
Mean reversion strategy

Future strategies:

Trend following
Volatility breakout
Market regime switching
Liquidity detection
Order flow imbalance

These strategies will be combined using multi-strategy voting mechanisms similar to professional quant funds.

Real-Time Market Data

Vision-AI uses Binance WebSocket streams to obtain real-time market data:

BTCUSDT price feed
order book depth
candlestick streams

Future data integrations:

Derivatives market data
on-chain analytics
macro indicators
alternative data
News Sentiment Engine

Planned integrations:

CryptoPanic API
NewsAPI
Twitter sentiment
GDELT data

Natural language processing will convert news into bullish / bearish sentiment signals used by the strategy engine.

Risk Management System

Implemented controls:

maximum position size
maximum drawdown limits
daily loss limits
max open trades

Future improvements:

dynamic position sizing
portfolio optimization
volatility adjusted risk
Trading Execution

Current execution:

paper trading simulation

Future execution system:

exchange API integration
order management system
risk throttling
latency optimized execution

Advanced architecture:

FastAPI research layer
C++ low latency execution engine
exchange gateway
Security

Vision-AI will include secure authentication.

Planned features:

user signup / login
JWT authentication
secure API endpoints
user database

Sensitive keys are stored using environment variables.

Required environment variables:

BINANCE_API_KEY
BINANCE_SECRET
SECRET_KEY
DATABASE_URL
REACT_APP_API

Exchange API keys must always:

disable withdrawals
enable IP restrictions
be stored securely
Database

Current database:

SQLite

Future upgrade:

PostgreSQL

Stored data:

users
trades
predictions
portfolio history
system logs

Folder Structure

vision-ai
│
├── ai-trading-dashboard
│
├── src
│   ├── api
│   ├── auth
│   ├── backtesting
│   ├── data_collection
│   ├── feature_engineering
│   ├── model_training
│   ├── prediction
│   ├── strategy
│   ├── execution
│   ├── portfolio
│   ├── risk
│   ├── sentiment
│   ├── regime
│   └── quant
│
├── models
├── scripts
├── config
├── data
├── logs
│
├── requirements.txt
├── render.yaml
├── LICENSE
└── README.md
Development Setup

Clone the repository:

git clone https://github.com/username/vision-ai.git
cd vision-ai

Create virtual environment:

python -m venv venv
source venv/bin/activate

Install dependencies:

pip install -r requirements.txt

Start backend server:

uvicorn src.api.main:app --reload

Run frontend:

cd ai-trading-dashboard
npm install
npm start
Deployment

Frontend:

Vercel

Backend:

Render

Future production infrastructure:

Docker
Kubernetes
AWS / GCP
Roadmap
Phase 1 — Platform Stabilization

fix websocket stability

stabilize API endpoints

improve dashboard UI

strengthen error handling

Phase 2 — AI System Expansion

ensemble ML models

market regime detection

AI confidence scoring

Phase 3 — Real-Time Trading Engine

streaming data pipeline

strategy orchestration

advanced backtesting

Phase 4 — Production Infrastructure

authentication system

PostgreSQL database

monitoring & logging

Phase 5 — Advanced Quant Platform

C++ execution engine

low latency order management

portfolio optimization

reinforcement learning trading agents

Current Completion Status
Prototype System        ✔ Complete
Research Platform       ✔ Complete
Stable Trading Engine   In Progress
Production Platform     Planned

Estimated completion:
≈ 65%
Disclaimer

Vision-AI is a research and educational project.

Automated trading involves financial risk.
Always perform extensive testing before using real capital.

Author
Abhinav Saha
Software Developer | Quant Research Enthusiast

GitHub
LinkedIn

Next Step (Recommended)

The next major upgrades that will significantly improve Vision-AI are:

market regime AI
news sentiment engine
order flow analytics
liquidity detection
portfolio optimization

