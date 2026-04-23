import joblib
from pathlib import Path
from sklearn.datasets import load_iris
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split

def main():
    # Load the saved model
    model_path = Path(__file__).resolve().parents[1] / "models" / "model.joblib"
    if not model_path.is_file():
        raise FileNotFoundError(f"Model file not found at {model_path}. Run train.py first.")
    model = joblib.load(model_path)

    # Load Iris dataset and split (same random_state as training)
    iris = load_iris()
    X, y = iris.data, iris.target
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    # Predict and evaluate
    y_pred = model.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    print(f"Loaded model test accuracy: {acc:.4f}")

if __name__ == "__main__":
    main()
