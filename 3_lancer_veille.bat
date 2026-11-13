@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Par defaut : mois precedent. Pour 7 jours : remplacez --last-month par --days 7
rem Lancement planifie : 3_lancer_veille.bat silencieux  (n'ouvre pas le rapport, pas de pause)
python veille_vet.py --last-month > dernier_lancement.log 2>&1
if /i "%~1"=="silencieux" exit /b %errorlevel%
type dernier_lancement.log
for /f "delims=" %%f in ('dir /b /o-d rapports\*.html 2^>nul') do (
  start "" "rapports\%%f"
  goto :fin
)
:fin
pause
