-- Vista canonica para Auto-Hub sobre tablas PsKloud (operti / opermv).
-- Se ejecuta en la base activa (admin000002, adminposper, etc.).

DROP VIEW IF EXISTS autohub_v_facturas;

CREATE VIEW autohub_v_facturas AS
SELECT
    CONCAT(h.id_empresa, ':', h.agencia, ':', h.tipodoc, ':', h.documento) AS factura_id,
    COALESCE(
        NULLIF(TRIM(h.documentofiscal), ''),
        CONCAT('FAC-', LPAD(TRIM(TRIM(LEADING '0' FROM TRIM(h.documento))), 8, '0'))
    ) AS numero_factura,
    DATE(h.emision) AS fecha_emision,
    h.totneto AS subtotal,
    h.totimpuest AS itbms_factura,
    h.totalfinal AS total_factura,
    TRIM(h.codcliente) AS cliente_codigo,
    TRIM(h.nombrecli) AS cliente_nombre,
    TRIM(h.rif) AS ruc,
    d.origen AS linea,
    TRIM(d.nombre) AS descripcion,
    d.cantidad,
    d.preciounit AS precio_unitario,
    CASE
        WHEN d.timpueprc >= 1 THEN d.timpueprc / 100
        ELSE d.timpueprc
    END AS tasa_itbms,
    d.montoneto AS total_linea,
    TRIM(d.almacen) AS sucursal_codigo,
    TRIM(COALESCE(a.nombre, '')) AS sucursal_nombre,
    CASE TRIM(d.almacen)
        WHEN '01' THEN 'ADI SUPPLY'
        WHEN '02' THEN 'CORONADO'
        WHEN '03' THEN 'RIO ABAJO'
        ELSE TRIM(COALESCE(NULLIF(TRIM(a.nombre), ''), 'SIN SUCURSAL'))
    END AS sucursal
FROM operti h
JOIN opermv d
  ON h.id_empresa = d.id_empresa
 AND h.agencia = d.agencia
 AND h.tipodoc = d.tipodoc
 AND h.documento = d.documento
LEFT JOIN almacene a
  ON a.id_empresa = d.id_empresa
 AND a.agencia = d.agencia
 AND TRIM(a.codigo) = TRIM(d.almacen)
WHERE h.tipodoc = 'FAC'
  AND h.totalfinal > 0
  AND TRIM(h.estatusdoc) IN ('0', '2')
  AND d.cantidad > 0;
