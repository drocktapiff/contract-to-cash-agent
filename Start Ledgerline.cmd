@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1
if not exist ".web-venv\Scripts\python.exe" (
  echo Ledgerline needs its Python environment before first launch.
  echo In Git Bash, from this project folder, run:
  echo   py -3.13 -m venv .web-venv
  echo   source .web-venv/Scripts/activate
  echo   python -m pip install -r requirements-web.txt
  echo Then follow docs\WINDOWS_LAUNCHER.md for the frontend and public runtime.
  pause
  popd
  exit /b 1
)
".web-venv\Scripts\python.exe" -m contract_to_cash.web.windows_launcher %*
set "LEDGERLINE_EXIT=%ERRORLEVEL%"
if not "%LEDGERLINE_EXIT%"=="0" pause
popd
exit /b %LEDGERLINE_EXIT%
