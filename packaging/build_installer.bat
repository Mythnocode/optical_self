@echo off
setlocal
rem ================================================================
rem  Build OpticalMLPlatform: PyInstaller onedir + Inno Setup installer
rem  Run from the repo root (or anywhere; paths are absolute below).
rem ================================================================

set "ENV_PY=D:\anacondanew\envs\optical\python.exe"
set "ISCC=C:\Users\qingxue\AppData\Local\Programs\Inno Setup 6\ISCC.exe"
set "SPEC=%~dp0optical_ml.spec"
set "ISS=%~dp0installer.iss"

if not exist "%ENV_PY%" (
    echo [ERROR] Python not found: %ENV_PY%
    exit /b 1
)
if not exist "%ISCC%" (
    echo [ERROR] ISCC not found: %ISCC%
    echo Install Inno Setup 6 and update the ISCC line in this script.
    exit /b 1
)

echo [1/2] Building with PyInstaller (onedir) ...
"%ENV_PY%" -m PyInstaller --noconfirm --clean "%SPEC%"
if errorlevel 1 goto :error

echo [2/2] Compiling installer with ISCC ...
"%ISCC%" "%ISS%"
if errorlevel 1 goto :error

echo.
echo Build complete: dist\OpticalMLPlatform (app dir)
echo Installer:       dist\installer\OpticalMLPlatform_Setup_v1.5.6.exe
exit /b 0

:error
echo [ERROR] Build failed. See output above.
exit /b 1
