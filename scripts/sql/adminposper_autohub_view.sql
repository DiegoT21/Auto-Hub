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
FROM adminposper.operti t
JOIN adminposper.opermv m
  ON m.id_empresa = t.id_empresa
 AND m.agencia = t.agencia
 AND m.tipodoc = t.tipodoc
 AND m.documento = t.documento
WHERE t.tipodoc = 'FAC';
