@echo off
rem The previous-day high/low study (the video's numbers) on the historical prices; saves the
rem report in reports\strategy-lab\ and opens it. Research only: nothing is traded.
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src"
set "PYTHONUTF8=1"
if exist ".venv\Scripts\python.exe" (set "PY=.venv\Scripts\python.exe") else (set "PY=py -3")
%PY% -m forex.lab study --open
pause
