@echo off
REM Doble clic aqui. La ventana no se cierra sola.
REM Pack factura: 2026-08-17-g  (necesita run_write_invoice.bat + WriteTestInvoice.cs nuevos)
cd /d "%~dp0"
echo.
echo Lanzador ABRIR_WRITE_INVOICE - pack 2026-08-17-g
echo.
cmd /k "run_write_invoice.bat"
