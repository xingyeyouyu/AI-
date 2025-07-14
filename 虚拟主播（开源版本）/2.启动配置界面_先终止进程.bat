@echo off
chcp 65001 >nul
echo Terminating all Python processes...
taskkill /f /im python.exe >nul 2>&1
taskkill /f /im pythonw.exe >nul 2>&1
taskkill /f /im ffplay.exe >nul 2>&1

echo Waiting for processes to terminate...
timeout /t 2 /nobreak >nul

echo Starting configuration interface...
start "" python webui.py

echo Configuration interface started, please visit http://127.0.0.1:5000/
echo After modifying the configuration, please restart the virtual host program
timeout /t 5 