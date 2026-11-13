@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Preparation des corrections ===
python preparer_corrections.py
if errorlevel 1 ( pause & exit /b 1 )
echo.
where git >nul 2>nul
if errorlevel 1 (
  echo Git n'est pas installe : envoyez simplement le contenu du dossier "corrections" a Julien.
  pause
  exit /b 0
)
git remote get-url origin >nul 2>nul
if errorlevel 1 (
  echo Pas de depot distant configure : envoyez le dossier "corrections" a Julien.
  pause
  exit /b 0
)
git add corrections
git commit -m "Corrections de matieres"
git pull --rebase
git push
echo.
echo Corrections envoyees.
pause
