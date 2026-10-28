@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto python
py -3 -c "import sys;sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if errorlevel 1 goto python
py -3 section_studio_server.py
goto end
:python
where python >nul 2>nul
if errorlevel 1 goto missing
python -c "import sys;sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if errorlevel 1 goto missing
python section_studio_server.py
goto end
:missing
echo Python 3.10 or newer is required for automatic OpenVSP preparation.
echo Install Python with the Python launcher or Add Python to PATH enabled.
echo You can also open Section_Studio.html for the offline editor.
:end
echo.
echo Section Studio stopped. If an error occurred, keep its text for support.
pause
