@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo === Auto-Hub Sage SDK - ESCRITURA de prueba ===
echo Carpeta: %CD%
echo SOLO empresa: LYL CONSTRUCTIONS SUPPLY INC 2025-2026
echo Crea cliente: AUTOHUB-TEST
echo.

if not exist "app_id.txt" (
  echo ERROR: falta app_id.txt con el Application ID
  pause
  exit /b 13
)

set /p SAGE_APP_ID=<app_id.txt
if "%SAGE_APP_ID%"=="" (
  echo ERROR: app_id.txt vacio
  pause
  exit /b 13
)

echo Application ID: configurado
echo.

set "API_DIR="
if exist "%ProgramFiles(x86)%\Sage\Peachtree\API\Sage.Peachtree.API.dll" (
  set "API_DIR=%ProgramFiles(x86)%\Sage\Peachtree\API"
)
if not defined API_DIR if exist "C:\Program Files (x86)\Sage\Peachtree\API\Sage.Peachtree.API.dll" (
  set "API_DIR=C:\Program Files (x86)\Sage\Peachtree\API"
)

if not defined API_DIR (
  echo ERROR: no se encontro el SDK API
  pause
  exit /b 10
)

set "CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
if not exist "%CSC%" (
  echo ERROR: falta csc.exe .NET 4.x
  pause
  exit /b 11
)

echo Compilando WriteTestCustomer.cs ...
"%CSC%" /nologo /platform:x86 /t:exe /out:WriteTestCustomer.exe ^
  /r:"%API_DIR%\Sage.Peachtree.API.dll" ^
  /r:"%API_DIR%\Sage.Peachtree.API.Resolver.dll" ^
  WriteTestCustomer.cs

if errorlevel 1 (
  echo ERROR: fallo la compilacion.
  pause
  exit /b 12
)

echo.
echo Ejecutando escritura de prueba...
echo Si pide Always Allow en Sage -^> aceptar
echo.
WriteTestCustomer.exe "LYL CONSTRUCTIONS SUPPLY INC 2025-2026" "%SAGE_APP_ID%"
echo.
echo Codigo de salida: %ERRORLEVEL%
pause
