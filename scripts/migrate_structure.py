"""
Migration script: moves files from old layout to new professional structure.
Rewrites all imports, creates __init__.py files, updates entry points.

Usage: python scripts/migrate_structure.py
"""

import os
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).parent.parent
BACKEND = ROOT / "backend" / "src"

# ───────────────────────────────────────────────────
# File migration map: old_path → new_path (relative to ROOT)
# ───────────────────────────────────────────────────

MIGRATION = {
    # exchange/
    "src/Binance/binance_engine.py":        "backend/src/exchange/binance_engine.py",
    "src/Binance/exchange_adapter.py":      "backend/src/exchange/exchange_adapter.py",
    # execution/
    "src/Execution/execution_engine.py":    "backend/src/execution/execution_engine.py",
    "src/Execution/order_manager.py":       "backend/src/execution/order_manager.py",
    "src/Execution/live_safety.py":         "backend/src/execution/live_safety.py",
    # portfolio/
    "src/Portfolio/portfolio_manager.py":   "backend/src/portfolio/portfolio_manager.py",
    "src/Portfolio/optimizer.py":           "backend/src/portfolio/optimizer.py",
    # risk/
    "src/Risk_manager/risk_manager.py":    "backend/src/risk/risk_manager.py",
    "src/Risk_manager/risk_score.py":      "backend/src/risk/risk_score.py",
    # workers/
    "src/Trading/trading_loop.py":         "backend/src/workers/trading_loop.py",
    # core/
    "src/core/structured_logger.py":       "backend/src/core/structured_logger.py",
    "src/core/health_monitor.py":          "backend/src/core/health_monitor.py",
    "config/settings.py":                  "backend/src/core/config.py",
    # data/
    "src/data_collection/fetcher.py":      "backend/src/data/fetcher.py",
    "src/data_collection/sources.py":      "backend/src/data/sources.py",
    # features/
    "src/feature_engineering/indicators.py":      "backend/src/features/indicators.py",
    "src/feature_engineering/feature_selector.py": "backend/src/features/feature_selector.py",
    # models/
    "src/model_training/trainer.py":       "backend/src/models/trainer.py",
    "src/model_training/deep_models.py":   "backend/src/models/deep_models.py",
    "src/model_training/regime_models.py": "backend/src/models/regime_models.py",
    "src/model_training/model_registry.py":"backend/src/models/model_registry.py",
    "src/prediction/ensemble_model.py":    "backend/src/models/ensemble_model.py",
    "src/prediction/predictor.py":         "backend/src/models/predictor.py",
    "src/regime/regime_detector.py":       "backend/src/models/regime_detector.py",
    # research/
    "src/backtesting/engine.py":           "backend/src/research/backtesting_engine.py",
    "src/evaluation/metrics.py":           "backend/src/research/metrics.py",
    "src/evaluation/walk_forward.py":      "backend/src/research/walk_forward.py",
    "src/quant/alpha_research.py":         "backend/src/research/alpha_research.py",
    "src/quant/signal_engine.py":          "backend/src/research/signal_engine.py",
    "src/quant/confidence_engine.py":      "backend/src/risk/confidence_engine.py",
    # strategy/
    "src/strategy/strategy_engine.py":     "backend/src/strategy/strategy_engine.py",
    "src/strategy/strategy_selector.py":   "backend/src/strategy/strategy_selector.py",
    "src/strategy/momentum_strategy.py":   "backend/src/strategy/momentum.py",
    "src/strategy/mean_reversion.py":      "backend/src/strategy/mean_reversion.py",
    "src/strategy/trend_following.py":     "backend/src/strategy/trend_following.py",
    "src/strategy/volatility_strategy.py": "backend/src/strategy/volatility.py",
    "src/strategy/order_flow_strategy.py": "backend/src/strategy/order_flow.py",
    "src/strategy/pairs_trading.py":       "backend/src/strategy/pairs_trading.py",
    "src/strategy/stat_arb.py":            "backend/src/strategy/stat_arb.py",
    "src/strategy/ai_strategy.py":         "backend/src/strategy/ai_strategy.py",
    # sentiment/
    "src/sentiment/sentiment_engine.py":   "backend/src/sentiment/sentiment_engine.py",
    "src/sentiment/nlp_model.py":          "backend/src/sentiment/nlp_model.py",
    "src/sentiment/news_fetcher.py":       "backend/src/sentiment/news_fetcher.py",
    "src/sentiment/sentiment_model.py":    "backend/src/sentiment/sentiment_model.py",
    # api/
    "src/api/main.py":                     "backend/src/api/main.py",
    "src/api/auth_routes.py":              "backend/src/api/auth_routes.py",
    "src/api/news_service.py":             "backend/src/api/news_service.py",
    "src/api/routes/data.py":              "backend/src/api/routes/data.py",
    "src/api/routes/predictions.py":       "backend/src/api/routes/predictions.py",
    # database/
    "src/database/db.py":                  "backend/src/database/db.py",
    "src/database/init_database.py":       "backend/src/database/init_database.py",
    # auth/
    "src/auth/auth_service.py":            "backend/src/auth/auth_service.py",
    # dashboard (stays mostly in place but under frontend/)
    "src/dashboard/app.py":                "backend/src/dashboard/app.py",
}

# ───────────────────────────────────────────────────
# Import rewrite rules: old_import_prefix → new_import_prefix
# ───────────────────────────────────────────────────

IMPORT_REWRITES = [
    # Exchange
    ("src.Binance.exchange_adapter",     "backend.src.exchange.exchange_adapter"),
    ("src.Binance.binance_engine",       "backend.src.exchange.binance_engine"),
    ("src.Binance.",                      "backend.src.exchange."),
    # Execution
    ("src.Execution.execution_engine",   "backend.src.execution.execution_engine"),
    ("src.Execution.order_manager",      "backend.src.execution.order_manager"),
    ("src.Execution.live_safety",        "backend.src.execution.live_safety"),
    ("src.Execution.",                    "backend.src.execution."),
    # Portfolio
    ("src.Portfolio.portfolio_manager",  "backend.src.portfolio.portfolio_manager"),
    ("src.Portfolio.optimizer",          "backend.src.portfolio.optimizer"),
    ("src.Portfolio.",                    "backend.src.portfolio."),
    # Risk
    ("src.Risk_manager.risk_manager",    "backend.src.risk.risk_manager"),
    ("src.Risk_manager.risk_score",      "backend.src.risk.risk_score"),
    ("src.Risk_manager.",                "backend.src.risk."),
    # Trading → workers
    ("src.Trading.trading_loop",         "backend.src.workers.trading_loop"),
    ("src.Trading.",                      "backend.src.workers."),
    # Core
    ("src.core.structured_logger",       "backend.src.core.structured_logger"),
    ("src.core.health_monitor",          "backend.src.core.health_monitor"),
    ("src.core.",                         "backend.src.core."),
    # Data
    ("src.data_collection.fetcher",      "backend.src.data.fetcher"),
    ("src.data_collection.sources",      "backend.src.data.sources"),
    ("src.data_collection.",             "backend.src.data."),
    # Features
    ("src.feature_engineering.indicators","backend.src.features.indicators"),
    ("src.feature_engineering.feature_selector","backend.src.features.feature_selector"),
    ("src.feature_engineering.",          "backend.src.features."),
    # Models
    ("src.model_training.trainer",       "backend.src.models.trainer"),
    ("src.model_training.deep_models",   "backend.src.models.deep_models"),
    ("src.model_training.regime_models", "backend.src.models.regime_models"),
    ("src.model_training.model_registry","backend.src.models.model_registry"),
    ("src.model_training.",              "backend.src.models."),
    ("src.prediction.ensemble_model",    "backend.src.models.ensemble_model"),
    ("src.prediction.predictor",         "backend.src.models.predictor"),
    ("src.prediction.",                  "backend.src.models."),
    ("src.regime.regime_detector",       "backend.src.models.regime_detector"),
    ("src.regime.",                       "backend.src.models."),
    # Research
    ("src.backtesting.engine",           "backend.src.research.backtesting_engine"),
    ("src.backtesting.",                  "backend.src.research."),
    ("src.evaluation.metrics",           "backend.src.research.metrics"),
    ("src.evaluation.walk_forward",      "backend.src.research.walk_forward"),
    ("src.evaluation.",                   "backend.src.research."),
    ("src.quant.alpha_research",         "backend.src.research.alpha_research"),
    ("src.quant.signal_engine",          "backend.src.research.signal_engine"),
    ("src.quant.confidence_engine",      "backend.src.risk.confidence_engine"),
    ("src.quant.",                        "backend.src.research."),
    # Strategy (same name, just under backend/)
    ("src.strategy.",                     "backend.src.strategy."),
    # Sentiment
    ("src.sentiment.",                    "backend.src.sentiment."),
    # API
    ("src.api.",                          "backend.src.api."),
    # Auth
    ("src.auth.",                         "backend.src.auth."),
    # Database
    ("src.database.",                     "backend.src.database."),
    # Dashboard
    ("src.dashboard.",                    "backend.src.dashboard."),
    # Config
    ("config.settings",                  "backend.src.core.config"),
]

# ───────────────────────────────────────────────────
# Step 1: Create directory structure
# ───────────────────────────────────────────────────

def create_directories():
    dirs = [
        "backend/src/core", "backend/src/data", "backend/src/features",
        "backend/src/models", "backend/src/research", "backend/src/strategy",
        "backend/src/execution", "backend/src/risk", "backend/src/portfolio",
        "backend/src/exchange", "backend/src/sentiment", "backend/src/api/routes",
        "backend/src/workers", "backend/src/database", "backend/src/auth",
        "backend/src/dashboard",
        "frontend", "deployment", "docs",
    ]
    for d in dirs:
        path = ROOT / d
        path.mkdir(parents=True, exist_ok=True)
        print(f"  📁 {d}/")
    
    # Create __init__.py in every package
    for d in dirs:
        if d.startswith("backend/src"):
            init = ROOT / d / "__init__.py"
            if not init.exists():
                init.write_text("")
    
    # Top-level backend/__init__.py and backend/src/__init__.py
    (ROOT / "backend" / "__init__.py").write_text("")
    (ROOT / "backend" / "src" / "__init__.py").write_text("")

    print(f"\n  ✅ Created {len(dirs)} directories")


# ───────────────────────────────────────────────────
# Step 2: Copy files to new locations
# ───────────────────────────────────────────────────

def copy_files():
    copied = 0
    skipped = 0
    for old, new in MIGRATION.items():
        src = ROOT / old
        dst = ROOT / new
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
        else:
            print(f"  ⚠ Source not found: {old}")
            skipped += 1
    
    print(f"\n  ✅ Copied {copied} files ({skipped} not found)")
    return copied


# ───────────────────────────────────────────────────
# Step 3: Rewrite imports in all new files
# ───────────────────────────────────────────────────

def rewrite_imports():
    """Rewrite imports in all Python files under backend/src/."""
    count = 0
    files_modified = 0

    for py_file in BACKEND.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8", errors="replace")
        original = content

        for old, new in IMPORT_REWRITES:
            content = content.replace(old, new)

        if content != original:
            py_file.write_text(content, encoding="utf-8")
            files_modified += 1
            count += len([1 for o, n in IMPORT_REWRITES if o in original])

    # Also rewrite test files
    tests_dir = ROOT / "tests"
    if tests_dir.exists():
        for py_file in tests_dir.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8", errors="replace")
            original = content
            for old, new in IMPORT_REWRITES:
                content = content.replace(old, new)
            if content != original:
                py_file.write_text(content, encoding="utf-8")
                files_modified += 1

    print(f"\n  ✅ Rewrote imports in {files_modified} files")


# ───────────────────────────────────────────────────
# Step 4: Move deployment files
# ───────────────────────────────────────────────────

def move_deployment_files():
    deploy_files = {
        "Dockerfile": "deployment/Dockerfile",
        "docker-compose.yml": "deployment/docker-compose.yml",
        "render.yaml": "deployment/render.yaml",
    }
    moved = 0
    for old, new in deploy_files.items():
        src = ROOT / old
        dst = ROOT / new
        if src.exists():
            shutil.copy2(src, dst)
            moved += 1

    print(f"\n  ✅ Copied {moved} deployment files")


# ───────────────────────────────────────────────────
# Step 5: Copy frontend
# ───────────────────────────────────────────────────

def copy_frontend():
    src = ROOT / "ai-trading-dashboard"
    dst = ROOT / "frontend" / "ai-trading-dashboard"
    if src.exists() and not dst.exists():
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns(
            "node_modules", ".next", "build", ".cache"
        ))
        print(f"\n  ✅ Copied frontend dashboard")
    elif dst.exists():
        print(f"\n  ⏭ Frontend already exists at {dst}")
    else:
        print(f"\n  ⚠ Frontend source not found at {src}")


# ───────────────────────────────────────────────────
# Main
# ───────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Vision AI — Repository Restructure Migration")
    print("=" * 60)

    print("\n📁 Step 1: Creating directory structure...")
    create_directories()

    print("\n📄 Step 2: Copying files to new locations...")
    copy_files()

    print("\n🔄 Step 3: Rewriting imports...")
    rewrite_imports()

    print("\n🚀 Step 4: Copying deployment files...")
    move_deployment_files()

    print("\n🎨 Step 5: Copying frontend...")
    copy_frontend()

    print("\n" + "=" * 60)
    print("  ✅ Migration complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Run tests: python -m pytest tests/ -v")
    print("  2. Start API:  python -m backend.src.api.main")
    print("  3. Verify:     curl localhost:10000/health")


if __name__ == "__main__":
    main()
