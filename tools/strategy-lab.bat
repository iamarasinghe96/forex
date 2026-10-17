@echo off
rem Strategy lab menu: test strategies on historical prices with the paper bot's rules.
rem Research only: nothing is traded and the live bot is not touched.
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src"
set "PYTHONUTF8=1"
if exist ".venv\Scripts\python.exe" (set "PY=.venv\Scripts\python.exe") else (set "PY=py -3")
%PY% -m forex.lab menu
pause
