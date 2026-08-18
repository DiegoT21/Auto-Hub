# Analisis de EjemploFacturaSage.sql

Archivo analizado:

`C:\Users\diego\Downloads\EjemploFacturaSage\EjemploFacturaSage.sql`

## Resumen

El archivo no es un CSV de importacion de Sage. Es un dump MySQL de la base `adminposper`.

Contiene 2 tablas principales:

- `operti`: encabezado de documentos/facturas.
- `opermv`: lineas o movimientos de los documentos/facturas.

Conteo aproximado de registros insertados:

- `operti`: 11,328 registros.
- `opermv`: 16,468 registros.

Conteo por tipo de documento:

`operti`:

- `FAC`: 3,116
- `PRE`: 5,422
- `REC`: 2,402
- `N/C`: 361
- `N/D`: 6
- `NOT`: 8
- `ESP`: 11
- `PED`: 2

`opermv`:

- `FAC`: 6,143
- `PRE`: 10,276
- `NOT`: 14
- `ESP`: 30
- `PED`: 5

## Relacion entre tablas

Las facturas se identifican principalmente con:

- `id_empresa`
- `agencia`
- `tipodoc`
- `documento`

Para facturas reales se usa:

```sql
tipodoc = 'FAC'
```

Relacion sugerida:

```sql
operti.id_empresa = opermv.id_empresa
AND operti.agencia = opermv.agencia
AND operti.tipodoc = opermv.tipodoc
AND operti.documento = opermv.documento
```

## Campos importantes en `operti`

`operti` parece ser el encabezado de factura.

Campos relevantes:

- `documento`: numero interno de documento.
- `tipodoc`: tipo de documento, por ejemplo `FAC`.
- `codcliente`: codigo del cliente.
- `nombrecli`: nombre del cliente.
- `rif`: RUC/RIF del cliente.
- `nit`: posible identificador adicional.
- `direccion`: direccion del cliente.
- `telefonos`: telefono.
- `emision`: fecha de emision.
- `vence`: fecha de vencimiento.
- `totbruto`: total bruto.
- `totneto`: subtotal/neto.
- `totalfinal`: total final de la factura.
- `totimpuest`: total de impuesto.
- `impuesto1`: impuesto 1.
- `estatusdoc`: estatus del documento.
- `vendedor`: vendedor.
- `almacen`: almacen.
- `documentofiscal`: numero fiscal/documento fiscal.
- `idvalidacion`: identificador de validacion fiscal.
- `fechayhora`: fecha y hora de registro.

## Campos importantes en `opermv`

`opermv` parece ser el detalle o lineas de factura.

Campos relevantes:

- `documento`: numero de documento relacionado con `operti`.
- `tipodoc`: tipo de documento.
- `grupo`: grupo del articulo/servicio.
- `subgrupo`: subgrupo.
- `codigo`: codigo de producto o servicio.
- `pid`: identificador/product id.
- `nombre`: descripcion del producto o servicio.
- `costounit`: costo unitario.
- `preciounit`: precio unitario.
- `preciofin`: precio final.
- `cantidad`: cantidad.
- `montoneto`: monto neto de la linea.
- `montototal`: monto total de la linea.
- `fechadoc`: fecha del documento.
- `timpueprc`: porcentaje de impuesto.
- `impu_mto`: monto de impuesto por linea, aunque en los ejemplos aparece en 0.
- `vendedor`: vendedor.
- `emisor`: usuario/emisor.
- `unidad`: unidad.
- `notas`: notas de linea.
- `cuentacont`: cuenta contable, aunque en los ejemplos aparece vacia.
- `baseimpo1`: base imponible.
- `fechayhora`: fecha y hora de registro.

## Query base sugerida

Esta consulta extrae facturas con su detalle:

```sql
SELECT
    h.id_empresa,
    h.agencia,
    h.tipodoc,
    h.documento,
    h.documentofiscal,
    h.idvalidacion,
    h.emision,
    h.vence,
    h.codcliente,
    h.nombrecli,
    h.rif,
    h.nit,
    h.direccion,
    h.telefonos,
    h.vendedor,
    h.almacen,
    h.totneto,
    h.totimpuest,
    h.totalfinal,
    h.estatusdoc,
    d.codigo,
    d.nombre AS descripcion,
    d.cantidad,
    d.preciounit,
    d.montoneto,
    d.montototal,
    d.timpueprc,
    d.impu_mto,
    d.cuentacont,
    d.unidad
FROM operti h
JOIN opermv d
  ON h.id_empresa = d.id_empresa
 AND h.agencia = d.agencia
 AND h.tipodoc = d.tipodoc
 AND h.documento = d.documento
WHERE h.tipodoc = 'FAC'
ORDER BY h.emision, h.documento;
```

## Mapeo inicial hacia el hub

Mapeo probable desde este dump hacia el formato de exportacion:

- `Invoice Number`: `operti.documento` o `operti.documentofiscal`
- `Date`: `operti.emision`
- `Customer ID`: `operti.codcliente`
- `Customer Name`: `operti.nombrecli`
- `RUC`: `operti.rif`
- `Description`: `opermv.nombre`
- `Quantity`: `opermv.cantidad`
- `Unit Price`: `opermv.preciounit`
- `Line Amount`: `opermv.montoneto`
- `Tax Code`: derivado de `opermv.timpueprc`
- `Tax Amount`: preferiblemente calculado desde `montoneto * (timpueprc / 100)` o tomado de `operti.totimpuest` a nivel encabezado.
- `Invoice Total`: `operti.totalfinal`
- `GL Account`: pendiente; `opermv.cuentacont` existe pero aparece vacio en ejemplos.

## Observaciones importantes

- `operti` y `opermv` parecen ser tablas del sistema origen o una base administrativa, no una plantilla CSV directa de Sage.
- `tipodoc = 'FAC'` identifica facturas. `PRE` parece presupuesto/proforma.
- `documento` es el numero interno del documento.
- `documentofiscal` puede ser mas importante que `documento` si Sage necesita el numero fiscal real.
- `opermv.impu_mto` aparece en 0 en muestras, aunque `operti.totimpuest` si trae impuesto total. Conviene recalcular impuesto por linea usando `timpueprc`.
- `estatusdoc` debe confirmarse: hay facturas con `estatusdoc = 0` y otras con `2`. Antes de exportar a Sage hay que saber cuales estatus son validos.
- `cuentacont` existe, pero en las muestras viene vacio. Si Sage exige cuenta contable, probablemente debe salir de una regla de negocio/configuracion, no de este dump.

## Preguntas para la reunion

- Para Sage, usan `documento` o `documentofiscal` como numero de factura?
- Que valores de `estatusdoc` se deben exportar?
- Exportan solo `tipodoc = 'FAC'`?
- Como manejan facturas anuladas o notas de credito (`N/C`)?
- Sage necesita lineas de producto o solo asiento contable resumido?
- Que cuenta contable debe ir por producto/servicio si `cuentacont` esta vacio?
- El impuesto debe ir por linea o solo como total de factura?
- El RUC valido es `rif` o combinan `rif` + `nit`?
