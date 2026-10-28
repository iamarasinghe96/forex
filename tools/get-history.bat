@echo off
rem One-off: download Dukascopy hourly prices (2012 to today) for the strategy lab into
rem data\dukascopy-history.sqlite3. Needs Node.js. Safe to run again: finished pairs are skipped.
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src"
set "PYTHONUTF8=1"
if exist ".venv\Scripts\python.exe" (set "PY=.venv\Scripts\python.exe") else (set "PY=py -3")
%PY% -m forex.lab get-history
pause
