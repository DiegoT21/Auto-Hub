@echo off
cd /d "%~dp0.."

if not exist config\config.json if exist config\config.example.json (
  copy /y config\config.example.json config\config.json >nul
)
if not exist config\connections.json if exist config\connections.example.json (
  copy /y config\connections.example.json config\connections.json >nul
)

if not exist .venv\Scripts\pythonw.exe (
  python -m venv .venv
  .venv\Scripts\python.exe -m pip install -r requirements.txt
)

.venv\Scripts\python.exe scripts\setup_branding.py >nul 2>&1

if not exist data\pskloud_demo.db (
  .venv\Scripts\python.exe scripts\seed_database.py
)
