"""
NLP sentiment model for financial text analysis.

Primary: FinBERT (ProsusAI/finbert) for financial sentiment
Fallback: Keyword-based rule model when transformers unavailable
"""

from __future__ import annotations

import logging
from typing import Dict, List

import numpy as np

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Check transformers availability
# ------------------------------------------------------------------

_HAS_TRANSFORMERS = False
try:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    _HAS_TRANSFORMERS = True
except ImportError:
    logger.warning("transformers/torch not installed — using rule-based sentiment")


# ==================================================================
# FinBERT Sentiment Model
# ==================================================================


class FinBERTSentimentModel:
    """Financial sentiment analysis using FinBERT (lazy-loaded)."""

    MODEL_NAME = "ProsusAI/finbert"

    def __init__(self):
        if not _HAS_TRANSFORMERS:
            raise ImportError("transformers and torch required for FinBERT")

        # Lazy load — don't download 400MB model at startup
        self.tokenizer = None
        self.model = None
        self._loaded = False
        self.labels = ["positive", "negative", "neutral"]

    def _ensure_loaded(self):
        """Load FinBERT model on first use."""
        if self._loaded:
            return
        try:
            logger.info("Loading FinBERT model (first use)...")
            self.tokenizer = AutoTokenizer.from_pretrained(self.MODEL_NAME)
            self.model = AutoModelForSequenceClassification.from_pretrained(
                self.MODEL_NAME
            )
            self.model.eval()
            self._loaded = True
            logger.info("FinBERT model loaded successfully")
        except Exception as e:
            logger.error("FinBERT load failed: %s", e)
            raise

    def analyze(self, texts: List[str]) -> Dict:
        """Analyze sentiment for a batch of texts."""
        if not texts:
            return {"score": 0.0, "label": "neutral", "details": []}

        self._ensure_loaded()

        details = []
        scores = []

        # Process in batches of 16
        batch_size = 16
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]

            inputs = self.tokenizer(
                batch,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=128,
            )

            with torch.no_grad():
                outputs = self.model(**inputs)
                probs = torch.nn.functional.softmax(outputs.logits, dim=-1)

            for j, text in enumerate(batch):
                p = probs[j].numpy()
                label_idx = np.argmax(p)

                sentiment_score = float(p[0] - p[1])  # positive - negative
                scores.append(sentiment_score)

                details.append(
                    {
                        "text": text[:100],
                        "label": self.labels[label_idx],
                        "positive": round(float(p[0]), 4),
                        "negative": round(float(p[1]), 4),
                        "neutral": round(float(p[2]), 4),
                        "score": round(sentiment_score, 4),
                    }
                )

        aggregate_score = float(np.mean(scores)) if scores else 0.0

        return {
            "score": round(aggregate_score, 4),
            "label": (
                "bullish"
                if aggregate_score > 0.1
                else "bearish" if aggregate_score < -0.1 else "neutral"
            ),
            "count": len(texts),
            "details": details,
        }


# ==================================================================
# Rule-based Fallback
# ==================================================================


class RuleSentimentModel:
    """Simple keyword-based sentiment as fallback."""

    BULLISH_WORDS = {
        "bull",
        "bullish",
        "surge",
        "soar",
        "rally",
        "breakout",
        "moon",
        "profit",
        "gain",
        "rise",
        "up",
        "growth",
        "positive",
        "higher",
        "buy",
        "long",
        "support",
        "recover",
        "bounce",
        "strong",
        "outperform",
        "upgrade",
        "beat",
        "exceed",
        "record",
    }

    BEARISH_WORDS = {
        "bear",
        "bearish",
        "crash",
        "dump",
        "sell",
        "selloff",
        "plunge",
        "loss",
        "drop",
        "fall",
        "down",
        "decline",
        "negative",
        "lower",
        "short",
        "resistance",
        "weak",
        "fail",
        "miss",
        "downgrade",
        "risk",
        "fear",
        "panic",
        "liquidation",
        "bankrupt",
    }

    def analyze(self, texts: List[str]) -> Dict:
        """Keyword-based sentiment scoring."""
        if not texts:
            return {"score": 0.0, "label": "neutral", "details": []}

        details = []
        scores = []

        for text in texts:
            words = set(text.lower().split())
            bull_count = len(words & self.BULLISH_WORDS)
            bear_count = len(words & self.BEARISH_WORDS)
            total = bull_count + bear_count

            if total == 0:
                score = 0.0
                label = "neutral"
            else:
                score = (bull_count - bear_count) / total
                label = (
                    "positive" if score > 0 else "negative" if score < 0 else "neutral"
                )

            scores.append(score)
            details.append(
                {
                    "text": text[:100],
                    "label": label,
                    "score": round(score, 4),
                }
            )

        aggregate_score = float(np.mean(scores)) if scores else 0.0

        return {
            "score": round(aggregate_score, 4),
            "label": (
                "bullish"
                if aggregate_score > 0.1
                else "bearish" if aggregate_score < -0.1 else "neutral"
            ),
            "count": len(texts),
            "details": details,
        }


# ==================================================================
# Factory function
# ==================================================================


def create_sentiment_model():
    """Create best available sentiment model."""
    if _HAS_TRANSFORMERS:
        try:
            return FinBERTSentimentModel()
        except Exception as e:
            logger.warning("FinBERT failed to load: %s — using rule-based fallback", e)

    return RuleSentimentModel()
