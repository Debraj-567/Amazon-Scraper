@echo off
title Amazon Scraper Cloudflare 24/7 Tunnel
cd /d "%~dp0"
echo =======================================================
echo   AMAZON SCRAPER - 24/7 CLOUDFLARE PUBLIC TUNNEL
echo =======================================================
echo.
echo Starting Cloudflare Tunnel on Port 5050...
echo (This tunnel will stay alive for 5-6+ hours continuously with NO timeouts)
echo.
cloudflared.exe tunnel --url http://127.0.0.1:5050
pause
