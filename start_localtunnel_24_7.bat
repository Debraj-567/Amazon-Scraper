@echo off
title 24/7 Amazon Scraper Tunnel (Auto-Reconnect)
cd /d "%~dp0"

echo =======================================================
echo   AMAZON SCRAPER - AUTO-RECONNECT 24/7 TUNNEL
echo   Fixed URL: https://debraj-amazon-scraper.loca.lt
echo   Tunnel IP Password: 223.233.76.52
echo =======================================================
echo.

:loop
echo [%time%] Starting LocalTunnel on port 5050...
npx -y localtunnel --port 5050 --subdomain debraj-amazon-scraper
echo [%time%] Tunnel disconnected! Auto-reconnecting in 2 seconds...
timeout /t 2 /nobreak >nul
goto loop
