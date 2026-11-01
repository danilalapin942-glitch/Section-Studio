@echo off
setlocal DisableDelayedExpansion
if not exist "%~dp0studio_bootstrap.py" goto extract
if not exist "%~dp0section_studio_server.py" goto extract
pushd "%~dp0"
if errorlevel 1 goto folder_error
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if not defined SECTION_STUDIO_PYTHON goto bundled
set "STUDIO_PYTHON=%SECTION_STUDIO_PYTHON:"=%"
if exist "%STUDIO_PYTHON%" goto check_path
echo SECTION_STUDIO_PYTHON does not point to a Python executable.
goto missing
:bundled
set "STUDIO_PYTHON=%~dp0runtime\python\python.exe"
if exist "%STUDIO_PYTHON%" goto check_path
set "STUDIO_PYTHON=%~dp0..\runtime\python\python.exe"
if exist "%STUDIO_PYTHON%" goto check_path
set "STUDIO_PYTHON=%~dp0..\..\runtime\python\python.exe"
if exist "%STUDIO_PYTHON%" goto check_path
goto launcher
:check_path
"%STUDIO_PYTHON%" -c "import sys;sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if errorlevel 1 goto launcher
"%STUDIO_PYTHON%" -u "%~dp0studio_bootstrap.py" %*
set "STUDIO_EXIT=%errorlevel%"
goto finish
:launcher
where py >nul 2>nul
if errorlevel 1 goto python
py -3 -c "import sys;sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if errorlevel 1 goto python
py -3 -u "%~dp0studio_bootstrap.py" %*
set "STUDIO_EXIT=%errorlevel%"
goto finish
:python
where python >nul 2>nul
if errorlevel 1 goto missing
python -c "import sys;sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if errorlevel 1 goto missing
python -u "%~dp0studio_bootstrap.py" %*
set "STUDIO_EXIT=%errorlevel%"
goto finish
:missing
echo Python 3.10 or newer is required. Install Python with launcher or PATH enabled.
echo You can also set SECTION_STUDIO_PYTHON to the full path of python.exe.
set "STUDIO_EXIT=1"
goto finish
:extract
echo Extract the entire ZIP to a normal folder before starting Section Studio.
echo studio_bootstrap.py and section_studio_server.py must be beside this launcher.
pause
exit /b 2
:folder_error
echo Cannot open the Section Studio folder.
pause
exit /b 2
:finish
echo.
if "%STUDIO_EXIT%"=="0" goto stopped
echo Section Studio failed. Read the error above and the printed launch.log path.
goto paused
:stopped
echo Section Studio stopped.
:paused
popd
pause
exit /b %STUDIO_EXIT%
