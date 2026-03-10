import joblib
import numpy as np
import pandas as pd

from pathlib import Path

from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler

import xgboost as xgb
import lightgbm as lgb


class ModelTrainer:

    def __init__(self, model_dir="models"):

        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(exist_ok=True)

        self.scaler = StandardScaler()

        self.rf = RandomForestClassifier(n_estimators=200)

        self.xgb = xgb.XGBClassifier(
            n_estimators=200,
            max_depth=6
        )

        self.lgb = lgb.LGBMClassifier(
            n_estimators=200
        )

        self.feature_names = []

    def train(self, df: pd.DataFrame):

        if "Target_Direction" not in df.columns:
            raise ValueError("Target_Direction column missing")

        X = df.drop(columns=["Target_Direction"])
        y = df["Target_Direction"]

        self.feature_names = list(X.columns)

        X_scaled = self.scaler.fit_transform(X)

        print("Training RandomForest...")
        self.rf.fit(X_scaled, y)

        print("Training XGBoost...")
        self.xgb.fit(X_scaled, y)

        print("Training LightGBM...")
        self.lgb.fit(X_scaled, y)

        return {"status": "ensemble trained"}

    def predict(self, X):

        X_scaled = self.scaler.transform(X)

        rf_prob = self.rf.predict_proba(X_scaled)[:,1]
        xgb_prob = self.xgb.predict_proba(X_scaled)[:,1]
        lgb_prob = self.lgb.predict_proba(X_scaled)[:,1]

        combined = (rf_prob + xgb_prob + lgb_prob) / 3

        return combined

    def save(self, name="trading_model"):

        joblib.dump(self.rf, self.model_dir / f"{name}_rf.joblib")
        joblib.dump(self.xgb, self.model_dir / f"{name}_xgb.joblib")
        joblib.dump(self.lgb, self.model_dir / f"{name}_lgb.joblib")

        joblib.dump(self.scaler, self.model_dir / f"{name}_scaler.joblib")
        joblib.dump(self.feature_names, self.model_dir / f"{name}_features.joblib")

    def load(self, name="trading_model"):

        self.rf = joblib.load(self.model_dir / f"{name}_rf.joblib")
        self.xgb = joblib.load(self.model_dir / f"{name}_xgb.joblib")
        self.lgb = joblib.load(self.model_dir / f"{name}_lgb.joblib")

        self.scaler = joblib.load(self.model_dir / f"{name}_scaler.joblib")
        self.feature_names = joblib.load(self.model_dir / f"{name}_features.joblib")