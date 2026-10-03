# Auto-Hub — Resumen técnico y operativo

> PsKloud → Sage 50 US · Documento de referencia  
> Repo: https://github.com/DiegoT21/Auto-Hub  
> Última actualización: agosto 2026

---

## Qué es

**Auto-Hub** es una aplicación de escritorio para Windows que lleva facturas de **PsKloud** (u otras fuentes) hacia **Sage 50 US**. No es un servicio en la nube: corre en la PC de Sage (o en una estación de desarrollo), con interfaz gráfica de 3 pasos.

---

## Tecnología

| Capa | Tecnología |
|------|------------|
| Lenguaje | **Python 3.12** |
| UI | **CustomTkinter** (Tkinter moderno) + tablas `ttk.Treeview` |
| Datos | **pandas** (transformación), **openpyxl** (Excel) |
| BD PsKloud | **mysql-connector-python 8.x** (MySQL remoto) o SQLite local demo |
| Sage (nuevo) | **Sage 50 SDK** (`Sage.Peachtree.API`) vía script C# compilado en runtime |
| Sage (legacy) | **pywin32** + automatización Excel |
| Empaquetado | **PyInstaller** → `AutoHub.exe` portable (~51 MB ZIP, ~118 MB descomprimido) |
| Actualizaciones | ZIP local o GitHub (`DiegoT21/Auto-Hub`, branch `main`) |

**Excluido del portable** (para bajar peso): pdfplumber, matplotlib, scipy, CTkTable, fpdf2. PDF/CSV funcionan en entorno de desarrollo; el ZIP portable está optimizado para MySQL + SDK.

---

## Arquitectura (carpetas)

```
Auto-Hub/
├── app/                 # UI (main, pasos, editor, preview, conexiones)
├── src/                 # Lógica (extract, validate, transform, sage_sdk_write, db…)
├── config/              # config.json, connections.json, pdf_extractor.json
├── scripts/sage_sdk/    # WriteTestInvoice.cs, bats, sample_invoice.json
├── scripts/build_portable.py
├── assets/              # iconos, branding
└── docs/                # documentación (este archivo)
```

**Archivos sensibles (no van al repo ni al ZIP):**

- `config/config.json`
- `config/connections.json`
- `scripts/sage_sdk/app_id.txt` (Application ID de Sage)

---

## Flujo de usuario (3 pasos)

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ 1. Importar │ ──► │ 2. Revisar  │ ──► │ 3. Sage     │
└─────────────┘     └─────────────┘     └─────────────┘
```

### Paso 1 — Importar

- Conectar a **MySQL PsKloud** (`operti` / `opermv` vía vista `autohub_v_facturas`)
- O importar **PDF** / **CSV**
- O cargar **prueba Sika** (`*0000001`, 3 líneas) para test SDK
- Buscar facturas por fecha/cliente, seleccionar, importar

### Paso 2 — Revisar

- Validación: RUC Panamá, totales de línea (con tolerancia a descuentos)
- Preview de válidas vs rechazadas
- Editor de datos antes de cargar

### Paso 3 — Carga Sage

- **Autorizar Sage** → Always Allow (una sola vez)
- **SDK prueba** → escribe factura en empresa de prueba vía API
- **▶ START** → camino antiguo por **plantilla Excel** (automatización)

---

## Integración con Sage 50

### Camino SDK (principal)

1. Auto-Hub genera `sample_invoice.json` (formato outbox)
2. Compila `WriteTestInvoice.cs` con `csc.exe` + DLLs de:
   `C:\Program Files (x86)\Sage\Peachtree\API\`
3. Abre sesión SDK → pide acceso → escribe `SalesInvoice`
4. Cierra sesión (`company.Close()` + `session.End()`) para no bloquear **Actian Zen**

**Configuración actual (prueba):**

| Campo | Valor |
|-------|-------|
| Empresa | `LYL CONST CIA de PRUEBA` |
| Cliente forzado | `C SUAREZ TORRE 1` |
| Fecha en Sage | Hoy (año contable abierto) |
| Número factura | Prefijo `AH` + timestamp |

### Camino Excel (legacy)

- Exporta CSV / llena plantilla Excel
- Automatiza Excel con pywin32
- Menos directo; no compite con Actian igual de agresivo que el SDK

### Motor de base de datos Sage

- **Actian Zen Workgroup Engine** (servicio interno: `zenengine`)
- Debe estar en estado **RUNNING**
- SDK y Sage comparten Actian → sesiones mal cerradas dejan Sage en “No responde”

---

## Fuentes de datos PsKloud

| Origen | Detalle |
|--------|---------|
| MySQL producción | Vista `autohub_v_facturas` sobre `operti` + `opermv`, `tipodoc = 'FAC'` |
| SQLite demo | Tablas normalizadas locales |
| PDF | Extracción por patrones (`config/pdf_extractor.json`) |
| CSV | Import manual |

**Conexión típica MySQL:**

- Host remoto PsKloud (ej. red LYL)
- Puerto 3306
- Schema `admin000002`
- Esquema en Hub: `pskloud_canonical`
- Vista: `autohub_v_facturas` (crear con botón “Crear vista PsKloud” si falta)

---

## Requisitos

### PC donde corre Auto-Hub (Sage)

| Requisito | Detalle |
|-----------|---------|
| SO | Windows 10/11 64-bit |
| Sage | Sage 50 Accounting **US** instalado |
| SDK | `Sage.Peachtree.API.dll` en Program Files (x86) |
| App ID | `C:\Temp\sage_sdk\app_id.txt` (de sdk.50us@sage.com) |
| .NET | Framework 4.x (`csc.exe` para compilar writer) |
| Red | Acceso a MySQL PsKloud (si importas de producción) |
| RAM | 16 GB alcanza; ideal no correr Hub + SDK en hora pico en el server |

### Licencia Sage

- Sage 50 US en red (varias sucursales)
- SDK = permiso de **desarrollo**, no sustituye puestos de contabilidad
- “Sesión no comercial” = aviso de licencia/modo, no define edición exacta

### No requiere en PC Sage

- Python instalado (va empaquetado en el exe)
- Git / login GitHub (se pasa ZIP por AnyDesk)

---

## Despliegue

### Instalación inicial

1. En máquina de desarrollo: `python scripts/build_portable.py`
2. Copiar `AutoHub-AnyDesk.zip` (~51 MB) por AnyDesk
3. Extraer en `C:\AutoHub`
4. Ejecutar `AutoHub.exe`
5. Configurar conexión MySQL y **Usar conexión**
6. Una vez: **Autorizar Sage** → **Always Allow**

### Actualizaciones

1. Pasar `AutoHub-update.zip` al Escritorio (o junto al exe)
2. Abrir Auto-Hub → **Actualizar app**
3. No pisa `connections.json`, `config.json` ni `app_id.txt`

### Desarrollo local (opcional)

```powershell
git clone https://github.com/DiegoT21/Auto-Hub.git
cd Auto-Hub
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app\main.py
```

---

## Peso y consumo de recursos

| Métrica | Valor aproximado |
|---------|------------------|
| ZIP portable | **~51 MB** |
| Carpeta descomprimida | **~118 MB** |
| RAM en reposo | **~150–250 MB** (pandas/numpy) |
| Pico al buscar MySQL | Consulta de red + hasta 150 facturas en preview |
| Pico al compilar SDK | Subprocess `csc` + `WriteTestInvoice.exe` (segundos) |
| Disco extra | `output/`, `state/`, logs locales |

**Por qué pesa:** pandas + numpy empaquetados con PyInstaller.

**Por qué no es pesado en uso:** no hay servidor web, no corre 24/7, no escanea toda la BD (límite preview 150).

---

## Estado del proyecto

### Hecho

- UI compacta (pasos en una fila, tabla visible)
- Import MySQL PsKloud, PDF, CSV
- Validación RUC Panamá y líneas con descuento
- SDK escribe factura en empresa de **prueba**
- Botones **Autorizar Sage** y **SDK prueba**
- Cierre limpio de sesión SDK (evitar bloqueo Actian)
- Portable AnyDesk + actualización in-app
- MySQL connector 8.x + `mysql_native_password`

### Pendiente

- Empresa Sage **producción** (`LYL CONSTRUCTIONS SUPPLY INC 2025`)
- Mapeo cliente PsKloud → ID cliente Sage real
- Fechas históricas (años contables cerrados)
- Carga masiva con deduplicación
- Confirmar estabilidad Actian en SERVER-LYL bajo carga real

---

## Relación con otros proyectos

| Proyecto | Repo / ubicación | Rol |
|----------|------------------|-----|
| **Auto-Hub** | DiegoT21/Auto-Hub | UI + import + carga Sage en PC contable |
| **PsKloud Extractor** | desktop-sage-ps (develop) | Node/Tauri, outbox, polling — no es la UI Sage |
| **Backoffice** | Monorepo PsKloud | Panel web/admin |

**No mezclar repos:** Auto-Hub es independiente del extractor Node.

---

## Operación segura en SERVER-LYL (3 sucursales)

1. **Una vez:** Sage abierto en empresa de prueba → **Autorizar Sage** → **Always Allow**
2. Cargas SDK preferiblemente **fuera de hora pico** o con Sage en estado conocido
3. Si Sage dice **“No responde”**:
   - Cerrar `peachw.exe` / `WriteTestInvoice.exe` si existen
   - `services.msc` → **Actian Zen Workgroup Engine** (`zenengine`) → Reiniciar
   - Reiniciar PC si hace falta
4. Desarrollo intensivo → mejor en **PC de desarrollo**, no en el server de producción

---

## Comandos útiles (PC Sage, cmd como Administrador)

```bat
sc query zenengine
net stop "Actian Zen Workgroup Engine"
net start "Actian Zen Workgroup Engine"
taskkill /F /IM peachw.exe /T
taskkill /F /IM WriteTestInvoice.exe /T
```

---

## Resumen en una frase

**Auto-Hub es un puente visual PsKloud → Sage 50**: Python empaquetado que importa facturas, las valida y hoy escribe en la empresa de prueba vía SDK; listo para extender a producción cuando exista mapeo de clientes y reglas de empresa real.

---

*Generado para LYL / integración PsKloud–Sage. Para cambios técnicos ver commits en `main` del repo Auto-Hub.*
