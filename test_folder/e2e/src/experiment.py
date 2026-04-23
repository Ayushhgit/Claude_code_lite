import joblib
from pathlib import Path

from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.svm import SVC
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier


def evaluate_model(name, model, X_train, X_test, y_train, y_test):
    model.fit(X_train, y_train)
    preds = model.predict(X_test)
    acc = accuracy_score(y_test, preds)
    print(f"{name} accuracy: {acc:.4f}")
    return acc


def main():
    iris = load_iris()
    X, y = iris.data, iris.target
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    results = {}
    # Logistic Regression with scaling
    lr = make_pipeline(StandardScaler(), LogisticRegression(max_iter=500, C=1.0))
    results['LogisticRegression'] = evaluate_model('LogisticRegression', lr, X_train, X_test, y_train, y_test)

    # SVC with different C values
    for C in [0.5, 1.0, 5.0, 10.0]:
        svc = make_pipeline(StandardScaler(), SVC(kernel='rbf', C=C, gamma='scale'))
        results[f'SVC_C={C}'] = evaluate_model(f'SVC_C={C}', svc, X_train, X_test, y_train, y_test)

    # Random Forest
    rf = RandomForestClassifier(n_estimators=300, random_state=42)
    results['RandomForest'] = evaluate_model('RandomForest', rf, X_train, X_test, y_train, y_test)

    # Gradient Boosting
    gb = GradientBoostingClassifier(random_state=42)
    results['GradientBoosting'] = evaluate_model('GradientBoosting', gb, X_train, X_test, y_train, y_test)

    # AdaBoost with DecisionTree
    from sklearn.ensemble import AdaBoostClassifier
    from sklearn.tree import DecisionTreeClassifier
    ada = AdaBoostClassifier(base_estimator=DecisionTreeClassifier(max_depth=3), n_estimators=200, random_state=42)
    results['AdaBoost'] = evaluate_model('AdaBoost', ada, X_train, X_test, y_train, y_test)

    # Voting Classifier (SVC + GradientBoosting)
    from sklearn.ensemble import VotingClassifier
    svc_best = make_pipeline(StandardScaler(), SVC(kernel='rbf', C=1.0, gamma='scale'))
    voting = VotingClassifier(estimators=[('svc', svc_best), ('gb', gb)], voting='soft')
    results['Voting'] = evaluate_model('Voting', voting, X_train, X_test, y_train, y_test)
    # Choose best model
    best_name = max(results, key=results.get)
    best_acc = results[best_name]
    print(f"Best model: {best_name} with accuracy {best_acc:.4f}")

    # Save best model
    models_dir = Path(__file__).resolve().parents[1] / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    best_model = None
    # Re-train best model on full training data (using same split for simplicity)
    if best_name.startswith('LogisticRegression'):
        best_model = lr
    elif best_name.startswith('SVC'):
        # extract C
        C_val = float(best_name.split('=')[1])
        best_model = make_pipeline(StandardScaler(), SVC(kernel='rbf', C=C_val, gamma='scale'))
    elif best_name == 'RandomForest':
        best_model = rf
    elif best_name == 'GradientBoosting':
        best_model = gb
    else:
        best_model = lr
    best_model.fit(X_train, y_train)
    model_path = models_dir / "model.joblib"
    joblib.dump(best_model, model_path)
    print(f"Saved best model to {model_path}")

if __name__ == "__main__":
    main()
