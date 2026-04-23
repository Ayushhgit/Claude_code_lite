# Iris Dataset End-to-End ML Example

This folder contains a minimal end‑to‑end (E2E) example of training a machine‑learning model on the classic **Iris** dataset using scikit‑learn.

## Folder structure
```
 e2e/
 ├─ data/          # (optional) place for raw data files
 ├─ models/        # saved trained model(s)
 ├─ src/           # source code
 │   ├─ train.py   # script to train and save the model
 │   ├─ evaluate.py# script to load the model and evaluate it
 │   └─ __init__.py
 ├─ requirements.txt  # python dependencies
 └─ run_all.bat    # convenience batch file to run training + evaluation
```

## How to run
1. **Install dependencies**
   ```bat
   pip install -r requirements.txt
   ```
2. **Train the model**
   ```bat
   python src\train.py
   ```
   This will create `models/model.joblib`.
3. **Evaluate the model**
   ```bat
   python src\evaluate.py
   ```

The scripts use the built‑in Iris dataset from scikit‑learn, so no external data files are required.
