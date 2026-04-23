import joblib
from pathlib import Path

from sklearn.datasets import load_wine
from sklearn.svm import SVC
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score


def main():
    """Train an SVC model on the Wine dataset and save it.

    The trained model is saved as ``wine_model.joblib`` in the ``models``
    directory next to the Iris model.
    """
    # Load Wine dataset
    wine = load_wine()
    X, y = wine.data, wine.target

    # Split into train and test sets (same split strategy as the Iris example)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    # Train an SVC model with scaling for better accuracy
    model = make_pipeline(StandardScaler(), SVC(kernel="rbf", C=1.0, gamma="scale"))
    model.fit(X_train, y_train)

    # Evaluate on test set
    y_pred = model.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    print(f"Wine test accuracy: {acc:.4f}")

    # Ensure the models directory exists
    models_dir = Path(__file__).resolve().parents[1] / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    # Save the trained model
    model_path = models_dir / "wine_model.joblib"
    joblib.dump(model, model_path)
    print(f"Wine model saved to {model_path}")


if __name__ == "__main__":
    main()
