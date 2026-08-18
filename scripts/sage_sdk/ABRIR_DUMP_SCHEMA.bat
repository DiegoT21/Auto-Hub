@echo off
REM Doble clic aqui. SOLO LECTURA - inventariar LYL CONSTRUCTIONS SUPPLY INC 2025
REM Pack: 2026-08-17-schema-b  (incluye lineas ApplyToSalesLines + CSV cruce)
cd /d "%~dp0"
echo.
echo Lanzador ABRIR_DUMP_SCHEMA - pack 2026-08-17-schema-b
echo Empresa: LYL CONSTRUCTIONS SUPPLY INC 2025
echo.
cmd /k "run_dump_schema.bat"
