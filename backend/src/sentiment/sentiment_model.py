"""
Sentiment model wrapper — auto-selects
"""

import logging
import random
from typing import Dict, List

logger = logging.getLogger(__name__)

try:
    import torch
    import torch.nn.functional as F
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False


class SentimentModel:
    """
    NLP sentiment engine using FinBERT.
    Parses textual market data (news headlines) and returns a sentiment score (-1 to 1).
    """

    def __init__(self, model_name: str = "ProsusAI/finbert"):
        self.enabled = TRANSFORMERS_AVAILABLE
        self.device = (
            torch.device("cuda" if torch.cuda.is_available() else "cpu")
            if self.enabled
            else None
        )

        if self.enabled:
            logger.info("Loading FinBERT NLP model from %s...", model_name)
            try:
                self.tokenizer = AutoTokenizer.from_pretrained(model_name)
                self.model = AutoModelForSequenceClassification.from_pretrained(
                    model_name
                )
                self.model.to(self.device)
                self.model.eval()
                self._model_loaded = True
            except Exception as e:
                logger.error("Failed to load FinBERT: %s", e)
                self._model_loaded = False
        else:
            logger.warning(
                "transformers library not installed. Sentiment Engine running in mock mode."
            )
            self._model_loaded = False

    def analyze(self, headlines: List[str]) -> Dict:
        """Analyze list of headlines and return aggregate sentiment score."""

        if not headlines:
            return {"score": 0.0, "label": "neutral"}

        if not self._model_loaded:
            # Fallback mock sentiment
            score = round(random.uniform(-1, 1), 4)
            label = (
                "positive"
                if score > 0.1
                else ("negative" if score < -0.1 else "neutral")
            )
            return {"score": score, "label": label}

        try:
            total_score = 0.0
            with torch.no_grad():
                for text in headlines:
                    inputs = self.tokenizer(
                        text,
                        return_tensors="pt",
                        padding=True,
                        truncation=True,
                        max_length=512,
                    )
                    inputs = {k: v.to(self.device) for k, v in inputs.items()}
                    outputs = self.model(**inputs)

                    probs = F.softmax(outputs.logits, dim=-1)[0].cpu().numpy()

                    # FinBERT ProsusAI outputs: [positive, negative, neutral]
                    pos_prob = probs[0]
                    neg_prob = probs[1]

                    # Calculate continuous score: positive probability - negative probability
                    total_score += pos_prob - neg_prob

            avg_score = float(total_score / len(headlines))

            # Map score to labels
            if avg_score > 0.1:
                label = "positive"
            elif avg_score < -0.1:
                label = "negative"
            else:
                label = "neutral"

            return {"score": round(avg_score, 4), "label": label}

        except Exception as e:
            logger.error("Sentiment analysis failed: %s", e)
            return {"score": 0.0, "label": "error"}
