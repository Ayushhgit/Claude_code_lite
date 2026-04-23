@echo off


REM Install required packages

pip install -r requirements.txt


REM Train the Iris model

python src\train.py

REM Evaluate the Iris model

python src\evaluate.py


REM Train the Wine model

python src\train_wine.py

REM Evaluate the Wine model

python src\evaluate_wine.py


pause