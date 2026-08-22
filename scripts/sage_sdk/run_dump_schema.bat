@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo === Auto-Hub Sage SDK - DUMP SCHEMA (SOLO LECTURA) ===
echo VERSION esperada: 2026-08-17-schema-b
echo Empresa: LYL CONSTRUCTIONS SUPPLY INC 2025-2026
echo Incluye: lineas ApplyToSalesLines + customers_crosswalk_template.csv
echo Carpeta: %CD%
echo.

if not exist "DumpSageSchema.cs" (
  echo ERROR: falta DumpSageSchema.cs
  pause
  exit /b 15
)

for %%F in ("DumpSageSchema.cs") do echo DumpSageSchema.cs fecha: %%~tF

if not exist "app_id.txt" (
  echo ERROR: falta app_id.txt
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

del /f /q DumpSageSchema.exe 2>nul

echo Compilando DumpSageSchema.cs ...
"%CSC%" /nologo /platform:x86 /t:exe /out:DumpSageSchema.exe ^
  /r:"%API_DIR%\Sage.Peachtree.API.dll" ^
  /r:"%API_DIR%\Sage.Peachtree.API.Resolver.dll" ^
  /r:"%WEBEXT%" ^
  DumpSageSchema.cs

if errorlevel 1 (
  echo ERROR: fallo la compilacion.
  pause
  exit /b 12
)

echo.
echo Ejecutando dump (lectura)...
echo Si pide Always Allow en Sage -^> aceptar
echo.
DumpSageSchema.exe "LYL CONSTRUCTIONS SUPPLY INC 2025-2026" "%SAGE_APP_ID%"
echo.
echo Codigo de salida: %ERRORLEVEL%
echo.
echo Si salio OK, copia la carpeta dump\ de vuelta a tu PC.
pause
