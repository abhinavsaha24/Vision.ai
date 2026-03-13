"""
Sentiment model wrapper — auto-selects best available model.
"""

from __future__ import annotations

from backend.src.sentiment.nlp_model import create_sentiment_model


class SentimentModel:
    """Wraps the best available sentiment model."""

    def __init__(self):
        self.model = create_sentiment_model()

    def analyze(self, headlines):
        """Analyze sentiment for a list of headline strings."""
        if not headlines:
            return {"score": 0.0, "label": "neutral", "details": []}

        return self.model.analyze(headlines)