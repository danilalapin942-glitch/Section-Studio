@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
set "SectionStudioScript=%~f1"
if not defined SectionStudioScript set /p "SectionStudioScript=Path to downloaded .vspscript file: "
set "SectionStudioScript=%SectionStudioScript:"=%"
if not exist "%SectionStudioScript%" (
  echo Script file was not found.
  pause
  exit /b 1
)
for %%F in ("%SectionStudioScript%") do set "SectionStudioScript=%%~fF"
set "SectionStudioExe=%SECTION_STUDIO_VSP_EXE%"
if not defined SectionStudioExe set /p "SectionStudioExe=Path to OpenVSP vspscript.exe: "
set "SectionStudioExe=%SectionStudioExe:"=%"
if not exist "%SectionStudioExe%" (
  echo OpenVSP executable was not found.
  pause
  exit /b 1
)
for %%F in ("%SectionStudioExe%") do set "SectionStudioExe=%%~fF"
for %%F in ("%SectionStudioExe%") do set "SectionStudioExeName=%%~nxF"
if /I not "%SectionStudioExeName%"=="vspscript.exe" goto wrong_exe
for %%F in ("%SectionStudioScript%") do set "SectionStudioDir=%%~dpF"
set "SectionStudioLog=%TEMP%\SectionStudio_%RANDOM%_%RANDOM%.log"
pushd "%SectionStudioDir%"
if errorlevel 1 (
  echo Cannot open the script directory.
  pause
  exit /b 1
)
"%SectionStudioExe%" -script "%SectionStudioScript%" > "%SectionStudioLog%" 2>&1
set "SectionStudioNativeExit=%errorlevel%"
type "%SectionStudioLog%"
if not "%SectionStudioNativeExit%"=="0" goto failed
findstr /C:"SECTION_STUDIO_ERROR" "%SectionStudioLog%" >nul
if not errorlevel 1 goto failed
findstr /C:"SECTION_STUDIO_WARNING:" "%SectionStudioLog%" >nul
if not errorlevel 1 echo GEOMETRY WARNING: inspect the VSP3 before using it.
findstr /C:"SECTION_STUDIO_SAVED:" "%SectionStudioLog%" >nul
if errorlevel 1 goto failed
echo.
echo The new file is in: "%SectionStudioDir%"
echo Open the file named after SECTION_STUDIO_SAVED in OpenVSP.
popd
pause
exit /b 0
:failed
echo.
echo Export did not confirm success. Native exit code: %SectionStudioNativeExit%
echo Log: "%SectionStudioLog%"
popd
pause
exit /b 1
:wrong_exe
echo Select vspscript.exe from the complete OpenVSP folder, not vsp.exe.
pause
exit /b 1
