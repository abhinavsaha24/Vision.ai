"""
Deep learning models for financial time series prediction.

Models:
  - LSTMPredictor: LSTM-based sequence model
  - TransformerPredictor: Lightweight temporal attention model

Both follow the sklearn-like interface: fit(X, y), predict_proba(X)
Falls back gracefully if PyTorch is not installed.
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Check PyTorch availability
# ------------------------------------------------------------------

_HAS_TORCH = False

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset

    _HAS_TORCH = True
except ImportError:
    logger.warning("PyTorch not installed — deep learning models unavailable")


def is_torch_available() -> bool:
    return _HAS_TORCH


# ==================================================================
# Sequence preparation
# ==================================================================


def create_sequences(X: np.ndarray, y: np.ndarray, seq_len: int = 30):
    """Slide a window of `seq_len` over X to produce 3-D input (samples, seq_len, features)."""
    Xs, ys = [], []
    for i in range(seq_len, len(X)):
        Xs.append(X[i - seq_len : i])
        ys.append(y[i])
    return np.array(Xs, dtype=np.float32), np.array(ys, dtype=np.float32)


# ==================================================================
# LSTM Model
# ==================================================================

if _HAS_TORCH:

    class _LSTMNet(nn.Module):

        def __init__(
            self,
            input_size: int,
            hidden_size: int = 64,
            num_layers: int = 2,
            dropout: float = 0.3,
        ):
            super().__init__()
            self.lstm = nn.LSTM(
                input_size,
                hidden_size,
                num_layers,
                batch_first=True,
                dropout=dropout if num_layers > 1 else 0,
            )
            self.head = nn.Sequential(
                nn.Dropout(dropout),
                nn.Linear(hidden_size, 32),
                nn.ReLU(),
                nn.Linear(32, 1),
                nn.Sigmoid(),
            )

        def forward(self, x):
            # x: (batch, seq_len, features)
            out, _ = self.lstm(x)
            last = out[:, -1, :]
            return self.head(last).squeeze(-1)

    class _TransformerNet(nn.Module):

        def __init__(
            self,
            input_size: int,
            d_model: int = 64,
            nhead: int = 4,
            num_layers: int = 2,
            dropout: float = 0.3,
        ):
            super().__init__()
            self.proj = nn.Linear(input_size, d_model)
            encoder_layer = nn.TransformerEncoderLayer(
                d_model=d_model,
                nhead=nhead,
                dim_feedforward=d_model * 4,
                dropout=dropout,
                batch_first=True,
            )
            self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
            self.head = nn.Sequential(
                nn.Dropout(dropout),
                nn.Linear(d_model, 32),
                nn.ReLU(),
                nn.Linear(32, 1),
                nn.Sigmoid(),
            )

        def forward(self, x):
            x = self.proj(x)
            x = self.encoder(x)
            cls = x[:, -1, :]
            return self.head(cls).squeeze(-1)

else:
    _LSTMNet = None
    _TransformerNet = None


class LSTMPredictor:
    """LSTM-based classifier with sklearn-like interface."""

    def __init__(
        self,
        seq_len: int = 30,
        hidden_size: int = 64,
        num_layers: int = 2,
        dropout: float = 0.3,
        epochs: int = 30,
        batch_size: int = 64,
        lr: float = 1e-3,
        patience: int = 5,
    ):
        if not _HAS_TORCH:
            raise ImportError("PyTorch is required for LSTMPredictor")

        self.seq_len = seq_len
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.dropout = dropout
        self.epochs = epochs
        self.batch_size = batch_size
        self.lr = lr
        self.patience = patience

        self.model = None
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    def fit(self, X: np.ndarray, y: np.ndarray):
        """Train on 2-D arrays (samples, features)."""
        X_seq, y_seq = create_sequences(X, y, self.seq_len)

        n_feat = X_seq.shape[2]
        self.model = _LSTMNet(
            n_feat, self.hidden_size, self.num_layers, self.dropout
        ).to(self.device)

        # Train/val split (90/10)
        split = int(len(X_seq) * 0.9)
        X_train, X_val = X_seq[:split], X_seq[split:]
        y_train, y_val = y_seq[:split], y_seq[split:]

        train_ds = TensorDataset(torch.tensor(X_train), torch.tensor(y_train))
        train_dl = DataLoader(train_ds, batch_size=self.batch_size, shuffle=False)

        opt = torch.optim.Adam(self.model.parameters(), lr=self.lr)
        criterion = nn.BCELoss()

        best_loss = float("inf")
        patience_count = 0

        for epoch in range(self.epochs):
            self.model.train()
            for xb, yb in train_dl:
                xb, yb = xb.to(self.device), yb.to(self.device)
                pred = self.model(xb)
                loss = criterion(pred, yb)
                opt.zero_grad()
                loss.backward()
                opt.step()

            # Validation
            self.model.eval()
            with torch.no_grad():
                val_pred = self.model(torch.tensor(X_val).to(self.device))
                val_loss = criterion(
                    val_pred, torch.tensor(y_val).to(self.device)
                ).item()

            if val_loss < best_loss:
                best_loss = val_loss
                patience_count = 0
            else:
                patience_count += 1
                if patience_count >= self.patience:
                    logger.info("LSTM early stopping at epoch %s", epoch + 1)
                    break

        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Return P(class=1) for 2-D input."""
        if self.model is None:
            raise RuntimeError("Model not trained")

        X_seq, _ = create_sequences(X, np.zeros(len(X)), self.seq_len)
        self.model.eval()
        with torch.no_grad():
            preds = self.model(torch.tensor(X_seq).to(self.device))

        proba = preds.cpu().numpy()
        # Pad beginning to match original length
        pad = np.full(self.seq_len, 0.5)
        return np.concatenate([pad, proba])

    def predict(self, X: np.ndarray, threshold: float = 0.5) -> np.ndarray:
        return (self.predict_proba(X) >= threshold).astype(int)


class TransformerPredictor:
    """Transformer-based classifier with sklearn-like interface."""

    def __init__(
        self,
        seq_len: int = 30,
        d_model: int = 64,
        nhead: int = 4,
        num_layers: int = 2,
        dropout: float = 0.3,
        epochs: int = 30,
        batch_size: int = 64,
        lr: float = 1e-3,
        patience: int = 5,
    ):
        if not _HAS_TORCH:
            raise ImportError("PyTorch is required for TransformerPredictor")

        self.seq_len = seq_len
        self.d_model = d_model
        self.nhead = nhead
        self.num_layers = num_layers
        self.dropout = dropout
        self.epochs = epochs
        self.batch_size = batch_size
        self.lr = lr
        self.patience = patience

        self.model = None
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    def fit(self, X: np.ndarray, y: np.ndarray):
        X_seq, y_seq = create_sequences(X, y, self.seq_len)

        n_feat = X_seq.shape[2]
        self.model = _TransformerNet(
            n_feat, self.d_model, self.nhead, self.num_layers, self.dropout
        ).to(self.device)

        split = int(len(X_seq) * 0.9)
        X_train, X_val = X_seq[:split], X_seq[split:]
        y_train, y_val = y_seq[:split], y_seq[split:]

        train_ds = TensorDataset(torch.tensor(X_train), torch.tensor(y_train))
        train_dl = DataLoader(train_ds, batch_size=self.batch_size, shuffle=False)

        opt = torch.optim.Adam(self.model.parameters(), lr=self.lr)
        criterion = nn.BCELoss()

        best_loss = float("inf")
        patience_count = 0

        for epoch in range(self.epochs):
            self.model.train()
            for xb, yb in train_dl:
                xb, yb = xb.to(self.device), yb.to(self.device)
                pred = self.model(xb)
                loss = criterion(pred, yb)
                opt.zero_grad()
                loss.backward()
                opt.step()

            self.model.eval()
            with torch.no_grad():
                val_pred = self.model(torch.tensor(X_val).to(self.device))
                val_loss = criterion(
                    val_pred, torch.tensor(y_val).to(self.device)
                ).item()

            if val_loss < best_loss:
                best_loss = val_loss
                patience_count = 0
            else:
                patience_count += 1
                if patience_count >= self.patience:
                    logger.info("Transformer early stopping at epoch %s", epoch + 1)
                    break

        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if self.model is None:
            raise RuntimeError("Model not trained")

        X_seq, _ = create_sequences(X, np.zeros(len(X)), self.seq_len)
        self.model.eval()
        with torch.no_grad():
            preds = self.model(torch.tensor(X_seq).to(self.device))

        proba = preds.cpu().numpy()
        pad = np.full(self.seq_len, 0.5)
        return np.concatenate([pad, proba])

    def predict(self, X: np.ndarray, threshold: float = 0.5) -> np.ndarray:
        return (self.predict_proba(X) >= threshold).astype(int)
