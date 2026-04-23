# End‑to‑End Machine Learning Pipeline

This repository demonstrates a simple end‑to‑end machine learning workflow that trains, evaluates, and saves models for two classic datasets: the Boston Housing dataset and the Wine Quality dataset.

## Project Structure
```
├── e2e/
│   ├── README.md            # This file
│   ├── requirements.txt     # Python dependencies
│   ├── run_all.bat          # Batch script to run everything
│   ├── data/                # Raw data (if any)
│   ├── models/              # Trained model artifacts
│   │   ├── model.joblib
│   │   └── wine_model.joblib
│   └── src/
│       ├── __init__.py
│       ├── train.py
│       ├── train_housing.py
│       ├── train_wine.py
│       ├── evaluate.py
│       ├── evaluate_wine.py
│       └── experiment.py
```

## Getting Started
1. **Install dependencies**
   ```bash
   pip install -r e2e/requirements.txt
   ```
2. **Run the full pipeline**
   ```bash
   cd e2e
   run_all.bat
   ```
   This will:
   - Train the housing model (`train_housing.py`)
   - Train the wine model (`train_wine.py`)
   - Evaluate both models and print metrics
   - Save the trained models to `e2e/models/`

## Scripts Overview
- `train.py` – Generic training helper.
- `train_housing.py` – Trains a regression model on the Boston Housing dataset.
- `train_wine.py` – Trains a classification model on the Wine Quality dataset.
- `evaluate.py` – Generic evaluation helper.
- `evaluate_wine.py` – Evaluates the wine model.
- `experiment.py` – Example script showing how to load a model and make predictions.

## Customization
Feel free to modify the hyperparameters in `train_housing.py` or `train_wine.py`. The models are saved using `joblib` for easy re‑loading.

## License
MIT © 2026
