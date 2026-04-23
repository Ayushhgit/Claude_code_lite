import joblib
from pathlib import Path
from sklearn.datasets import load_wine
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split

def main():
    """Load the saved wine model and evaluate it on the test split of the Wine dataset.

    The model is expected to be saved as ``wine_model.joblib`` in the ``models``
    directory (next to the Iris model). This mirrors ``evaluate.py`` but for the
    Wine dataset.
    """
    # Path to the saved wine model
    model_path = Path(__file__).resolve().parents[1] / "models" / "wine_model.joblib"
    if not model_path.is_file():
        raise FileNotFoundError(f"Wine model file not found at {model_path}. Run train_wine.py first.")
    model = joblib.load(model_path)

    # Load Wine dataset and split using the same random_state as training
    wine = load_wine()
    X, y = wine.data, wine.target
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    # Predict and evaluate
    y_pred = model.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    print(f"Wine model test accuracy: {acc:.4f}")

if __name__ == "__main__":
    main()
