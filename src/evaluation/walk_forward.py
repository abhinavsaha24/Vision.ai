import numpy as np


class WalkForwardValidator:

    def __init__(self, train_size=0.7, step_size=0.1):

        self.train_size = train_size
        self.step_size = step_size

    def run(self, df, feature_cols, target_col, model):

        n = len(df)

        train_window = int(n * self.train_size)

        step = int(n * self.step_size)

        results = []

        start = 0

        while start + train_window + step <= n:

            train = df.iloc[start:start + train_window]

            test = df.iloc[start + train_window:start + train_window + step]

            X_train = train[feature_cols]
            y_train = train[target_col]

            X_test = test[feature_cols]
            y_test = test[target_col]

            model.fit(X_train, y_train)

            preds = model.predict(X_test)

            accuracy = (preds == y_test).mean()

            results.append(accuracy)

            start += step

        return {
            "mean_accuracy": np.mean(results),
            "std_accuracy": np.std(results),
            "scores": results
        }