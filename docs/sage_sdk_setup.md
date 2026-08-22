# Sage 50 SDK — empresa de prueba

## Empresa seleccionada

| Campo | Valor |
|-------|--------|
| **Nombre** | `LYL CONSTRUCTIONS SUPPLY INC 2025-2026` |
| **Ruta datos** | `C:\Sage\Peachtree\Company\LYLCONSTRUCTIONSSUP1` |
| **SDK** | `C:\Archivos de programa (x86)\Sage\Peachtree\API\Sage.Peachtree.API.dll` |

Usar **solo esta empresa** para pruebas hasta validar importación de facturas.

## Orden de pruebas (AnyDesk / PC L&L)

1. **Application ID** — poner el ID de `sdk.50us@sage.com` en `scripts\sage_sdk\app_id.txt` (una sola línea).
2. **Always Allow** — al abrir la empresa, Sage pide Allow → elegir **Always Allow**.
3. **Cliente de prueba** — `ABRIR_WRITE_TEST.bat` crea `AUTOHUB-TEST` (si aún no existe).
4. **Factura de prueba** — `ABRIR_WRITE_INVOICE.bat` crea 1 sales invoice contra `AUTOHUB-TEST` con líneas de `sample_invoice.json`.

## Prueba rápida de lectura (probe)

1. Copiar la carpeta `scripts\sage_sdk\` a la PC del cliente (o clonar el repo ahí).
2. Cerrar Sage si prefieres probar apertura limpia (o dejarlo abierto).
3. Ejecutar **`run_probe.bat`** / **`ABRIR_PRUEBA.bat`** como usuario normal (no hace falta admin).
4. Si Sage muestra **“Allow access?”** / autorizar aplicación → **Sí / Always Allow**.
5. Resultado esperado:
   - Lista de compañías
   - `Autorizacion: Granted`
   - `OK — Empresa abierta via SDK.`

## Prueba de escritura: cliente

1. Ejecutar **`ABRIR_WRITE_TEST.bat`** (ventana que no se cierra sola).
2. Si pide autorización → **Always Allow** en Sage al abrir `LYL CONSTRUCTIONS SUPPLY INC 2025-2026`.
3. Esperado: `Autorizacion: Granted` y `OK - Cliente guardado`.
4. Verificar en Sage: **Customers & Sales → Customers** → ID `AUTOHUB-TEST`.

## Prueba de escritura: factura (PsKloud → Sage)

Puente hacia el inyector futuro (backoffice / Auto-Hub SDK). Hoy **no** consume `consumedAt` ni mapea `cliente_codigo` real: fuerza cliente Sage `AUTOHUB-TEST`.

### Datos de muestra

`sample_invoice.json` = array outbox-compatible `[{ "sentAt", "record" }, ...]` con **una factura** (todas sus líneas) desde `adminposper.autohub_v_facturas`.

Regenerar desde MySQL local (opcional):

```bat
python scripts\sage_sdk\export_sample_invoice.py 3117
```

Query equivalente:

```sql
SELECT * FROM adminposper.autohub_v_facturas
WHERE factura_id = 3117
ORDER BY linea;
```

### Cómo correrla en la PC Sage

1. Asegurar `app_id.txt`, cliente `AUTOHUB-TEST` y `sample_invoice.json` en `scripts\sage_sdk\`.
2. Doble clic **`ABRIR_WRITE_INVOICE.bat`** (o `run_write_invoice.bat`).
3. Si Sage pide acceso → cerrar/abrir **LYL CONSTRUCTIONS SUPPLY INC 2025-2026** → **Always Allow**.
4. Resultado esperado en consola:
   - `Autorizacion: Granted`
   - `OK - Factura guardada`
5. Verificar en Sage: **Customers & Sales → Sales Invoices**
   - Cliente `AUTOHUB-TEST`
   - Reference / nota con prefijo `AH` / texto `AH-TEST` (borrar a mano si hace falta)

GL de línea: `UsualSalesAccountReference` del cliente plantilla/`AUTOHUB-TEST` (mismo criterio que el write de cliente; default Auto-Hub Excel era `4100`).

API: `Sage.Peachtree.API` (US). No usar `TOSalesInvoice` (Canadá). Si `Create`/líneas difieren por versión, el script vuelca métodos/props por reflexión.

## Si falla

| Mensaje | Qué hacer |
|---------|-----------|
| `No se encontro la empresa` | Verificar nombre exacto en Select Company |
| `Autorizacion: Denied` | Autorizar en Sage o pedir Application ID a Sage |
| `Could not load assembly Sage.Peachtree.Domain` | Ejecutar en PC con Sage instalado; proyecto debe ser **x86** |
| `no existe cliente AUTOHUB-TEST` | Correr primero `ABRIR_WRITE_TEST.bat` |
| `falta sample_invoice.json` | Regenerar con `export_sample_invoice.py` o copiar el sample del repo |
| Application ID | Para compañías reales hace falta ID de `sdk.50us@sage.com` |

## Config en Auto-Hub

Ver `config/sage_sdk.json` — ahí queda registrada la empresa de prueba para cuando integremos el paso SDK en la app.
