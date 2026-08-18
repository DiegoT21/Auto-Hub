@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM ============================================================
REM Auto-Hub - prueba Sage 50 SDK (SOLO LECTURA)
REM Ejecutar con: ABRIR_PRUEBA.bat  (la ventana NO se cierra sola)
REM ============================================================

echo.
echo === Auto-Hub Sage SDK Probe ===
echo Carpeta: %CD%
echo.

REM --- Application ID desde archivo app_id.txt ---
REM Abre app_id.txt con Bloc de notas y pega el ID en UNA sola linea.
if not exist "app_id.txt" (
  echo ERROR: Falta app_id.txt
  echo Crea el archivo app_id.txt en esta carpeta y pega el Application ID.
  echo.
  pause
  exit /b 13
)

set /p SAGE_APP_ID=<app_id.txt
if "%SAGE_APP_ID%"=="" (
  echo ERROR: app_id.txt esta vacio. Pega el Application ID ahi.
  pause
  exit /b 13
)

echo Application ID: configurado
echo.

REM --- Rutas tipicas del SDK ---
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
  echo ERROR: No se encontro Sage.Peachtree.API.dll
  pause
  exit /b 10
)

echo SDK: %API_DIR%
echo.

set "CSC="
if exist "%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe" (
  set "CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
)

if not defined CSC (
  echo ERROR: No se encontro csc.exe de .NET Framework 4.x
  pause
  exit /b 11
)

echo Compilando ProbeSageSdk.cs ...
"%CSC%" /nologo /platform:x86 /t:exe /out:ProbeSageSdk.exe ^
  /r:"%API_DIR%\Sage.Peachtree.API.dll" ^
  /r:"%API_DIR%\Sage.Peachtree.API.Resolver.dll" ^
  ProbeSageSdk.cs

if errorlevel 1 (
  echo ERROR: fallo la compilacion.
  pause
  exit /b 12
)

REM Nota: cada vez que recompilas, Sage puede pedir autorizar de nuevo.
REM Si ya autorizaste y solo quieres probar otra vez sin recompilar:
REM   ProbeSageSdk.exe "LYL CONST CIA de PRUEBA"

echo.
echo Ejecutando prueba ...
echo Si Sage pide autorizar la app -^> Si / Allow
echo.

if "%~1"=="" (
  ProbeSageSdk.exe "LYL CONST CIA de PRUEBA" "%SAGE_APP_ID%"
) else (
  ProbeSageSdk.exe %*
)

echo.
echo Codigo de salida: %ERRORLEVEL%
echo.
pause
