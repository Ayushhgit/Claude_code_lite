import os
from pathlib import Path

import joblib
from sklearn.datasets import load_iris
from sklearn.svm import SVC
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

def main():
    # Load Iris dataset
    iris = load_iris()
    X, y = iris.data, iris.target

    # Split into train and test sets
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    # Train an SVC model with scaling for better accuracy
    model = make_pipeline(StandardScaler(), SVC(kernel='rbf', C=1.0, gamma='scale'))
    model.fit(X_train, y_train)

    # Evaluate on test set
    y_pred = model.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    print(f"Test accuracy: {acc:.4f}")

    # Ensure the models directory exists
    models_dir = Path(__file__).resolve().parents[1] / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    # Save the trained model
    model_path = models_dir / "model.joblib"
    joblib.dump(model, model_path)
    print(f"Model saved to {model_path}")

if __name__ == "__main__":
    main()
