@echo off
rem ============================================================
rem  OmniNexus dashboard launcher
rem  - Double-click to start the dev server, browser opens itself
rem  - Close this window = server stops (honest shutdown)
rem  - If the log shows a port other than 5173 (e.g. 5174 is
rem    taken by another tool), open that port instead
rem ============================================================
cd /d "%~dp0dashboard"
echo Starting OmniNexus dashboard ...
echo (browser opens in ~4s; close this window to stop)
start "" cmd /c "timeout /t 4 >nul && start http://localhost:5173/"
pnpm dev
