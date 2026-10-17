@echo off
rem Test every strategy that is switched on in strategy-lab.yaml, compare them, save the results
rem in reports\strategy-lab\ and open the summary. Research only: nothing is traded.
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src"
set "PYTHONUTF8=1"
if exist ".venv\Scripts\python.exe" (set "PY=.venv\Scripts\python.exe") else (set "PY=py -3")
%PY% -m forex.lab run --open %*
pause
