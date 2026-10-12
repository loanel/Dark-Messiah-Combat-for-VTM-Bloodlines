@echo off
rem Dark Messiah Combat for VTM Bloodlines installer. Checks for Python, numpy and Pillow, then runs install.py (offline, nothing is downloaded).
rem   install.bat                 install or repair
rem   install.bat --uninstall     remove Dark Messiah Combat
setlocal
cd /d "%~dp0"
set "PY="
py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python 3 was not found. Install it from python.org or the Microsoft Store, then run this again.
  goto end
)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" || (
  echo Python 3.8 or newer is needed.
  goto end
)
%PY% -c "import numpy, PIL" >nul 2>nul || (
  echo Python is missing numpy and/or Pillow. Install them with:
  echo     %PY% -m pip install numpy pillow
  echo then run this again.
  goto end
)
%PY% install.py %*
:end
echo.
pause
