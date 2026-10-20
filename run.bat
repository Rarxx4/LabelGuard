@echo off
rem Starts LabelGuard. Double-click this file, or run  .\run.bat  in a terminal.
rem Keep this window open while you use the app - closing it stops LabelGuard.
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
    echo Creating virtual environment and installing packages - first run only, takes a few minutes...
    python -m venv .venv || (echo Python 3.11 or newer is required: https://www.python.org/downloads/ & pause & exit /b 1)
    .venv\Scripts\python.exe -m pip install -r requirements.txt || (pause & exit /b 1)
)

if not exist .env (
    copy .env.example .env >nul
    echo Created .env - open it and paste your Gemini key after GEMINI_API_KEY=
    echo You can also paste the key in the app's sidebar, or use Offline demo mode.
)

rem Skip Streamlit's one-time "enter your email" question, which otherwise waits in this window.
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
    if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
    (echo [general]& echo email = "") > "%USERPROFILE%\.streamlit\credentials.toml"
)

echo.
echo Starting LabelGuard - your browser will open at http://localhost:8501
echo Keep this window open while using the app. Press Ctrl+C here to stop it.
echo.
.venv\Scripts\python.exe -m streamlit run app.py
pause
