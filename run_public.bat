@echo off
rem Double-click to put Food Match online through a free Cloudflare tunnel.
rem The https://....trycloudflare.com link appears in this window.
rem Keep the window open while people use the site; close it (or press Ctrl+C) to stop.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_public.ps1"
pause
