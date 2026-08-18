@echo off
cd /d "%~dp0.."
call .venv\Scripts\activate.bat
python scripts\run_sage_simulator.py fill-db
echo.
echo Excel generado en output\sage_simulator\
pause
