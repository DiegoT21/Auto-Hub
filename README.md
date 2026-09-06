# Auto-Hub — PsKloud → Sage 50

Repo: https://github.com/DiegoT21/Auto-Hub.git (privado)

## Instalar en la PC de Sage (recomendado)

No hace falta iniciar sesion en GitHub ni instalar Python/Git en esa PC.

1. En esta maquina corre `python scripts/build_portable.py` (o usa el ZIP ya generado).
2. Pasa `dist/AutoHub-AnyDesk.zip` por AnyDesk.
3. Extrae a `C:\AutoHub` y abre `AutoHub.exe`.

El Application ID de Sage sigue en `C:\Temp\sage_sdk\app_id.txt` (no va en el ZIP).

Ledger Bridge: copia el JWT **injector** a `config/ledger_bridge.jwt` (una linea). No va en git ni en el ZIP. En Automatico, Auto-Hub baja `GET /v1/pending` y confirma con `POST /v1/ack`.

### Actualizar despues

Pasa un `AutoHub-update.zip` nuevo al Escritorio (o junto al exe) y pulsa **Actualizar app**.
No pisa contraseñas ni `app_id.txt`.

## Instalar con Git (opcional)

Solo si quieres clonar el repo en esa PC (repo privado = login o token de GitHub):

```powershell
git clone https://github.com/DiegoT21/Auto-Hub.git C:\AutoHub
cd C:\AutoHub
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
wscript launch_autohub.vbs
```
