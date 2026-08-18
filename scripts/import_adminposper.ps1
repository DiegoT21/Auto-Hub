# Importa EjemploFacturaSage.sql en MySQL (schema adminposper).
# Uso: .\scripts\import_adminposper.ps1
# Te pedira la contraseña de root (o la que uses en Workbench).

$ErrorActionPreference = "Stop"

$mysql = "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe"
$sqlFile = Join-Path $env:USERPROFILE "Downloads\EjemploFacturaSage\EjemploFacturaSage.sql"
$dbName = "adminposper"

if (-not (Test-Path $mysql)) {
    Write-Error "No se encontro mysql.exe. Ajusta la ruta en el script."
}
if (-not (Test-Path $sqlFile)) {
    Write-Error "No se encontro el backup: $sqlFile"
}

$user = Read-Host "Usuario MySQL [root]"
if ([string]::IsNullOrWhiteSpace($user)) { $user = "root" }
$secure = Read-Host "Contrasena MySQL" -AsSecureString
$plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
)

Write-Host "`nCreando schema $dbName ..."
& $mysql -u $user -p$plain -e "CREATE DATABASE IF NOT EXISTS ``$dbName`` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

Write-Host "Importando $sqlFile (puede tardar 1-3 min) ..."
cmd /c "`"$mysql`" -u $user -p$plain $dbName < `"$sqlFile`""
if ($LASTEXITCODE -ne 0) {
    Write-Error "La importacion fallo. Revisa usuario/contrasena o importa desde Workbench."
}

Write-Host "`nVerificando tablas ..."
& $mysql -u $user -p$plain $dbName -e @"
SELECT 'operti' AS tabla, COUNT(*) AS registros FROM operti
UNION ALL
SELECT 'opermv', COUNT(*) FROM opermv
UNION ALL
SELECT 'FAC (operti)', COUNT(*) FROM operti WHERE tipodoc = 'FAC';
"@

Write-Host "`nListo. En Workbench refresca Schemas y abre adminposper."
