import logging

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

logger = logging.getLogger(__name__)


class TimeSeriesLSTM(nn.Module):
    def __init__(self, input_size, hidden_size=64, num_layers=2, dropout=0.2):
        super(TimeSeriesLSTM, self).__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0,
        )
        self.fc1 = nn.Linear(hidden_size, 32)
        self.relu = nn.ReLU()
        self.dropout = nn.Dropout(dropout)
        self.out = nn.Linear(32, 1)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        # x shape: (batch, seq_len, features)
        lstm_out, _ = self.lstm(x)
        # Take the output of the last time step
        last_out = lstm_out[:, -1, :]
        x = self.fc1(last_out)
        x = self.relu(x)
        x = self.dropout(x)
        x = self.out(x)
        return self.sigmoid(x)


class PyTorchLSTMModel:
    def __init__(
        self,
        input_size,
        seq_len=10,
        hidden_size=64,
        num_layers=2,
        epochs=20,
        batch_size=64,
        lr=0.001,
    ):
        self.seq_len = seq_len
        self.epochs = epochs
        self.batch_size = batch_size
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        self.model = TimeSeriesLSTM(
            input_size=input_size, hidden_size=hidden_size, num_layers=num_layers
        )
        self.model.to(self.device)

        self.criterion = nn.BCELoss()
        self.optimizer = optim.Adam(self.model.parameters(), lr=lr)

        self._is_fitted = False

    def _create_sequences(self, X, y=None):
        """Convert 2D array to 3D sequences of (samples, seq_len, features)"""
        # Note: In real production, this requires the time series to be chronological
        # Since trainer might shuffle or pass generic X, we do a sliding window
        xs = []
        ys = []
        for i in range(len(X) - self.seq_len):
            xs.append(X[i : (i + self.seq_len)])
            if y is not None:
                ys.append(y[i + self.seq_len - 1])

        if not xs:  # fallback if too short
            return np.zeros((1, self.seq_len, X.shape[1])), (
                np.zeros(1) if y is not None else None
            )

        if y is not None:
            return np.array(xs), np.array(ys)
        return np.array(xs)

    def fit(self, X, y):
        # Create sequences
        X_seq, y_seq = self._create_sequences(X, y)

        if len(X_seq) == 0:
            logger.warning("Not enough data to train LSTM")
            return

        dataset = TensorDataset(torch.FloatTensor(X_seq), torch.FloatTensor(y_seq))
        loader = DataLoader(dataset, batch_size=self.batch_size, shuffle=True)

        self.model.train()
        for epoch in range(self.epochs):
            total_loss = 0
            for batch_X, batch_y in loader:
                batch_X, batch_y = batch_X.to(self.device), batch_y.to(self.device)

                self.optimizer.zero_grad()
                outputs = self.model(batch_X).squeeze()

                # Handle batch_size=1 edgecase where squeeze removes batch dim
                if len(outputs.shape) == 0:
                    outputs = outputs.unsqueeze(0)

                loss = self.criterion(outputs, batch_y)
                loss.backward()
                self.optimizer.step()

                total_loss += loss.item()

            if epoch % 5 == 0:
                logger.debug("LSTM Epoch %s Loss: %.4f", epoch, total_loss / len(loader))

        self._is_fitted = True
        return self

    def predict_proba(self, X):
        """Return array shape (n_samples, 2) to match sklearn api"""
        if not self._is_fitted:
            # Return dummy 0.5 if not fitted
            return np.ones((len(X), 2)) * 0.5

        # Due to sequence requirement, the first (seq_len) predictions are tricky.
        # We will pad the beginning with the first row to keep array size same as X
        X_padded = np.vstack([np.repeat([X[0]], self.seq_len, axis=0), X])
        X_seq = self._create_sequences(X_padded)

        self.model.eval()
        with torch.no_grad():
            tensor_X = torch.FloatTensor(X_seq).to(self.device)
            outputs = self.model(tensor_X).squeeze().cpu().numpy()

        if len(outputs.shape) == 0:
            outputs = np.array([outputs])

        # Slice back to original length just in case padding math was slightly off
        outputs = outputs[-len(X) :]

        # Scikit-learn proba format: [prob_class_0, prob_class_1]
        probs = np.zeros((len(X), 2))
        probs[:, 1] = outputs
        probs[:, 0] = 1.0 - outputs
        return probs
