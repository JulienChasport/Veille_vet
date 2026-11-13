@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Entrainement du modele (quelques minutes la 1re fois, rapide ensuite grace au cache) ===
python entrainer_modele.py > dernier_entrainement.log 2>&1
type dernier_entrainement.log
if /i "%~1"=="silencieux" exit /b %errorlevel%
pause
