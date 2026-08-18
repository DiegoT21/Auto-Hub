# Conexion temporal a backup MySQL

Este proyecto ya puede trabajar contra dos fuentes:

- `normalized_tables`: el demo SQLite actual (`facturas`, `facturas_detalle`, `clientes`).
- `canonical_view`: una vista MySQL que adapta la BD real/de backup al formato que Auto-Hub necesita.

Para el backup visto en MySQL Workbench (`adminposper`, tablas `opermv` y `operti`), la ruta recomendada es crear una vista llamada `vw_autohub_invoice_lines`. Asi no amarramos la app a nombres internos de PsKloud y luego, cuando llegue la conexion real del cliente, solo se ajusta la vista o el config.

## Columnas que debe exponer la vista

Auto-Hub espera estas columnas:

```sql
factura_id
numero_factura
fecha_emision
subtotal
itbms_factura
total_factura
cliente_codigo
cliente_nombre
ruc
linea
descripcion
cantidad
precio_unitario
tasa_itbms
total_linea
```

## Vista para el backup `adminposper`

El SQL listo esta en `scripts/sql/adminposper_autohub_view.sql`.

```sql
CREATE OR REPLACE VIEW adminposper.vw_autohub_invoice_lines AS
SELECT
    CAST(t.documento AS UNSIGNED) AS factura_id,
    TRIM(t.documento) AS numero_factura,
    t.emision AS fecha_emision,
    CAST(t.totneto AS DECIMAL(12, 2)) AS subtotal,
    CAST(t.totimpuest AS DECIMAL(12, 2)) AS itbms_factura,
    CAST(t.totalfinal AS DECIMAL(12, 2)) AS total_factura,
    TRIM(t.codcliente) AS cliente_codigo,
    TRIM(t.nombrecli) AS cliente_nombre,
    TRIM(COALESCE(NULLIF(t.rif, ''), NULLIF(t.nit, ''), 'CF')) AS ruc,
    ROW_NUMBER() OVER (
        PARTITION BY t.id_empresa, t.agencia, t.tipodoc, t.documento
        ORDER BY m.fechayhora, m.pid
    ) AS linea,
    TRIM(m.nombre) AS descripcion,
    CAST(m.cantidad AS DECIMAL(12, 4)) AS cantidad,
    CAST(m.preciofin AS DECIMAL(12, 4)) AS precio_unitario,
    CAST(m.timpueprc / 100 AS DECIMAL(8, 4)) AS tasa_itbms,
    CAST(m.montoneto AS DECIMAL(12, 2)) AS total_linea
FROM adminposper.opermv m
JOIN adminposper.operti t
  ON m.id_empresa = t.id_empresa
 AND m.agencia = t.agencia
 AND m.tipodoc = t.tipodoc
 AND m.documento = t.documento
WHERE t.tipodoc = 'FAC';
```

## Config de prueba

Usa `config/config.mysql-backup.example.json` como base. Para probar el backup temporal:

1. Copia `config/config.mysql-backup.example.json` a un archivo local, por ejemplo `config/config.mysql-backup.local.json`.
2. Ajusta `database.user` y `database.password`.
3. Crea la vista `vw_autohub_invoice_lines`.
4. Abre la app apuntando a ese config y usa "Importar" desde PsKloud.

El demo SQLite queda intacto mientras `config/config.json` siga usando `"driver": "sqlite"`.

```powershell
$env:AUTOHUB_CONFIG = "C:\Users\diego\OneDrive\Desktop\Posper\Sage + PsKloud\config\config.mysql-backup.local.json"
python app\main.py
```

## Inspeccionar columnas del backup

Antes de completar la vista, ejecuta:

```powershell
python scripts\inspect_mysql_backup.py --config config\config.mysql-backup.local.json --tables opermv,operti
```

Ese comando imprime columnas y 5 filas de muestra por tabla. Con eso se reemplazan los `TODO_*` de la vista.
