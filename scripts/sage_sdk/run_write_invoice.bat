@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo === Auto-Hub Sage SDK - ESCRITURA factura de prueba ===
echo VERSION esperada en consola: 2026-08-17-g
echo Carpeta: %CD%
echo SOLO empresa: LYL CONSTRUCTIONS SUPPLY INC 2025-2026
echo Cliente: C SUAREZ TORRE 1
echo Sample: sample_invoice.json
echo.

if not exist "WriteTestInvoice.cs" (
  echo ERROR: falta WriteTestInvoice.cs - copia el archivo NUEVO a esta carpeta
  pause
  exit /b 15
)

for %%F in ("WriteTestInvoice.cs") do echo WriteTestInvoice.cs fecha: %%~tF

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

if not exist "sample_invoice.json" (
  echo ERROR: falta sample_invoice.json
  pause
  exit /b 14
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
if not defined API_DIR if exist "C:\Archivos de programa (x86)\Sage\Peachtree\API\Sage.Peachtree.API.dll" (
  set "API_DIR=C:\Archivos de programa (x86)\Sage\Peachtree\API"
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

set "WEBEXT=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\System.Web.Extensions.dll"
if not exist "%WEBEXT%" (
  echo ERROR: falta System.Web.Extensions.dll
  pause
  exit /b 11
)

del /f /q WriteTestInvoice.exe 2>nul

echo Compilando WriteTestInvoice.cs ...
"%CSC%" /nologo /platform:x86 /t:exe /out:WriteTestInvoice.exe ^
  /r:"%API_DIR%\Sage.Peachtree.API.dll" ^
  /r:"%API_DIR%\Sage.Peachtree.API.Resolver.dll" ^
  /r:"%WEBEXT%" ^
  WriteTestInvoice.cs

if errorlevel 1 (
  echo ERROR: fallo la compilacion.
  pause
  exit /b 12
)

echo.
echo Ejecutando escritura de factura de prueba...
echo Si pide Always Allow en Sage -^> aceptar
echo.
WriteTestInvoice.exe "LYL CONSTRUCTIONS SUPPLY INC 2025-2026" "%SAGE_APP_ID%" "sample_invoice.json"
echo.
echo Codigo de salida: %ERRORLEVEL%
pause
