@echo off
chcp 65001 >nul
rem ===========================================================================
rem  Manual run of combined_main.py  (double-click when the report is missing)
rem  All decision logic (anchor / EOD gate / idempotency) lives in the Python.
rem  Batch text is ASCII on purpose: cmd.exe mis-parses a non-BOM UTF-8 file.
rem  The Korean progress messages you see come from combined_main.py itself.
rem ===========================================================================
cd /d "%~dp0"

echo ============================================================
echo   OHNEUL-UI KOSPI  -  manual report build
echo ============================================================
echo.
echo Running combined_main.py ... (option-chain fetch: up to 1-2 min)
echo.

"venv\Scripts\python.exe" combined_main.py
set RC=%ERRORLEVEL%

echo.
if "%RC%"=="0" goto ok
if "%RC%"=="3" goto pending
if "%RC%"=="2" goto noprice
goto other

:ok
echo [OK] Report is ready. Opening it in the browser...
powershell -NoProfile -Command "$f = Get-ChildItem -Path 'reports\20*-*-*.html' | Sort-Object LastWriteTime -Descending | Select-Object -First 1; if ($f) { Start-Process $f.FullName } else { Write-Host '  (no report file found under reports\)' }"
goto end

:pending
echo [WAIT] KRX Open API has not published that trading day's option EOD yet.
echo        It usually posts during the morning. Re-run this file a bit later.
goto end

:noprice
echo [ERROR] No index price in cache to anchor the report (Naver fetch may have failed).
echo         Check your network connection and try again.
goto end

:other
echo [ERROR] Unexpected exit code %RC%. See the log above.
goto end

:end
echo.
pause
