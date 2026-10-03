# Extractor PsKloud → G Core: arreglos pendientes

> Revisión del 3 de octubre de 2026, cruzando PsKloud (`admin000002`, tablas `operti` / `opermv`) contra Sage 50 (`LYL CONSTRUCTIONS SUPPLY INC 2025-2026`) desde el 3 de septiembre de 2026.
> El Extractor no está en este repo: corre del lado de PsKloud y publica en la cola de G Core (Ledger Bridge) que AutoHub consume.

## Estado al 3 de octubre de 2026, 18:05

- **Cursor del Extractor: corregido.** El Extractor re-publicó lo que faltaba. AutoHub (`C:\AutoHub`) recibió 25 facturas re-publicadas, las marcó "Ya estaba en Sage. No se duplica." y confirmó las 25 a G Core.
- **Cruce PsKloud vs Sage** (facturas `FAC` desde el 3 de septiembre): 451 en PsKloud, 438 en Sage y registradas en `state/sage_sent.json`. No queda ninguna factura sin explicación:
  - 7 en espera de artículos en Sage: `DO14CP` (`*0008089`, `*0008112`, `*0008211`, `C0003441`, `C0003453`), `S-021` (`*0008118`), `CONSTV-018` (`C0003378`).
  - `00011232`: falta `INS-002` en Sage (no está en la cola de AutoHub; se carga a mano cuando exista).
  - 5 con datos incoherentes en PsKloud, para revisión de contabilidad (ver punto 4).
  - `*0008233` está en Sage con la versión vieja (+0.99); se corrige cuando exista `DO14CP`.
- Los artículos no se pueden crear por SDK (ninguna factory de artículos tiene `Create`); hay que crearlos en Sage, en **Maintain → Inventory Items**, con el mismo código de PsKloud.
- **Usar solo `C:\AutoHub\AutoHub.exe`.** La instalación vieja (`Desktop\Checkpoint Sage\apk\AutoHub-AnyDesk\AutoHub`) no tiene el registro de lo cargado el 3 de octubre: intentó recargar 26 facturas re-publicadas y Sage las rechazó con "Reference number is not unique" (no se duplicó nada).

Pendiente del punto 1: agregar la reconciliación periódica, para detectar a tiempo si vuelve a faltar algo.

## Resumen (diagnóstico original)

AutoHub carga bien lo que recibe. El problema principal es que **el Extractor no publica todas las facturas en G Core**. Desde el 28 de septiembre casi ninguna factura de Río Abajo llega a la cola. El 3 de octubre se cargaron a mano en Sage 72 facturas que G Core nunca entregó, o que fallaron y no se reintentaron. Mientras el Extractor no se corrija, las facturas nuevas van a seguir faltando.

## 1. Cursor (watermark) compartido entre sucursales — CORREGIDO el 3 de octubre

**Síntoma.** Cada día llegan todas las facturas de Coronado (`C…`). De Río Abajo (`*…`) solo llegan las que se emiten antes de la primera factura de Coronado de ese día; después de esa no llega ninguna más. Las de ADI (`000…`) también se pierden.

**Evidencia.**
- El 3 de octubre llegó `*0008308` (08:15:35) y, 22 segundos después, `C0003477` (08:15:57). Después de esa hora no llegó ninguna factura `*…` del día (`*0008309` a `*0008314`).
- Entre el 28 de septiembre y el 3 de octubre faltaban en G Core 59 facturas ($18,746.85): `*0008249`–`*0008264`, `*0008267`–`*0008274`, `*0008276`–`*0008287`, `*0008291`–`*0008293`, `*0008297`–`*0008307`, `*0008309`–`*0008314`, más las ADI `00011230`, `00011231`, `00011232`.

**Causa probable.** El cursor de "última factura publicada" se guarda en una sola variable para todas las sucursales y se compara como texto. En ASCII `*` < `0` < `C`, así que en cuanto se publica una factura `C…` el cursor queda por encima de todas las `*…` y `000…` del mismo día, y esas se saltan. Al día siguiente la fecha cambia y vuelve a pasar lo mismo.

**Arreglo.**
- Usar un cursor por sucursal / serie (`agencia` + prefijo del documento), o un cursor único que no dependa del número de documento: `fechayhora` + clave completa (`id_empresa:agencia:tipodoc:documento`), o `seq_nodo`.
- Nunca comparar números de documento como texto entre series distintas.
- Comparar con `>=` en el tiempo y deduplicar por clave para no perder facturas creadas en el mismo segundo.
- Agregar una reconciliación periódica: contar facturas `FAC` por día en `operti` contra lo publicado y re-publicar las que falten.

## 2. Re-publicación (backfill) de lo que faltó — HECHA el 3 de octubre

Las facturas que faltaban hasta el 3 de octubre **ya están en Sage** y registradas en `state/sage_sent.json` de AutoHub (por `factura_id` y por `numero_factura`). Si el Extractor las vuelve a publicar, AutoHub las marca como "Omitidas — Ya en Sage" y no las duplica. Se puede re-publicar desde el 28 de septiembre sin riesgo.

## 3. Datos del payload

| Problema | Ejemplo | Qué debería mandar el Extractor |
|---|---|---|
| `dsctounit` viene lleno aunque `preciounit` ya tiene el descuento aplicado (`preciofin` = `preciounit`) | `*0008017`, `*0008034` | Mandar `preciofin` por línea, o `dsctounit = 0` cuando el descuento ya está en el precio |
| Líneas informativas "ORDEN DE COMPRA: …" con código `00` y precio 0 | `00011222`, `00011224`, `00011227`–`00011229` | Marcarlas como informativas (o mandar el número de orden en un campo de cabecera) |
| El payload no trae dirección del cliente | todos los de `state/cloud_inbox` | Mandar `direccion` de `operti` como `cliente_direccion`; AutoHub la usa al crear el cliente en Sage |

AutoHub ya tolera los dos primeros casos (ver "Cambios en AutoHub"), pero lo correcto es que el dato venga limpio.

## 4. Documentos que no se publican o vienen incoherentes

- **Notas de crédito y débito (`N/C`, `N/D`).** No llegan a G Core y AutoHub hoy solo procesa `FAC`. Del 3 de septiembre al 3 de octubre hubo 7 N/C y 4 N/D ($1,514.49). Hay que definir si se publican y cómo se cargan en Sage (Credit Memo).
- **`estatusdoc`.** Hay que mandarlo en el payload. Observado: `2` = pagada, `0` = crédito sin pago (ADI), `1` = crédito con pago parcial, y aparece en facturas con devoluciones.
- **Facturas incoherentes en PsKloud.** El Extractor debería validarlas y marcarlas en vez de publicarlas mal:
  - `C0003358` y `C0003363`: cabecera sin líneas en `opermv`.
  - `C0003387` y `C0003407`: las líneas suman mucho más que `totalfinal` (1,379 contra 257.09; 427 contra 66.73).
  - `*0008203`: todas las líneas con `cntdevuelt = cantidad`.

## Cambios en AutoHub (este commit)

`scripts/sage_sdk/RunSageHost.ps1`:
- Omite las líneas con código `00` y precio 0 (texto de orden de compra) y agrega su texto a la nota de la factura en Sage, en vez de dejar la factura en espera por "falta item 00".
- No agrega la línea de descuento cuando la suma bruta de las líneas (`cantidad × precio_unitario`) ya es igual al `subtotal` de la factura, porque el descuento ya está en el precio.

## Pendientes del lado de AutoHub

- Las facturas que fallan al **crear el cliente** no entran en `sage_failed.json` y no se reintentan. Las 11 del 25–26 de septiembre fallaron con una versión anterior ("Last name, Company name or Address line 1 is required"), ya corregida, y se cargaron a mano.
- Faltan artículos en Sage para: `DO14CP` (`*0008089`, `*0008112`, `*0008211`, `C0003441`, `C0003453`, `*0008233`), `S-021` (`*0008118`), `CONSTV-018` (`C0003378`), `INS-002` (`00011232`). `643266` ya se creó y `C0003466` entró el 3 de octubre.
- El portable (`AutoHub.exe`) trae su propia copia de `RunSageHost.ps1`; hay que regenerarlo desde este repo para no volver a la versión anterior en una actualización.
