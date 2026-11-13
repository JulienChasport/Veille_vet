@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Installation de la veille veterinaire ===
where python >nul 2>nul
if errorlevel 1 (
  echo Python n'est pas installe. Installez-le depuis https://www.python.org/downloads/
  echo en cochant "Add python.exe to PATH", puis relancez ce fichier.
  pause
  exit /b 1
)
python -m pip install --upgrade scikit-learn joblib
if errorlevel 1 ( echo Echec de l'installation. & pause & exit /b 1 )
echo.
echo Installation terminee. Etape suivante : 2_entrainer.bat
pause
