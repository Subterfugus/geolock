@echo off
rem Start GeoLock and open it in the browser.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m geolock serve %*
pause
