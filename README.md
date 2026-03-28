# German Vocab App (Flashcards + Quiz)

An easy app to learn new German words with Russian translations. Works locally on your PC.

## Setup (Windows)

Open PowerShell in this folder and run:

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

If PowerShell blocks activation, run:

```bash
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## What you can do

- Add words (German + Russian + optional notes)
- Study with flashcards
- Take quick quizzes
- Review using a simple spaced-repetition schedule

Your data is saved to `data/vocab.json`.
