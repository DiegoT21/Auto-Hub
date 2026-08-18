# Auto-Hub — PsKloud → Sage 50

Repo: https://github.com/DiegoT21/Auto-Hub.git (privado)

## Instalar en la PC de Sage (una vez)

```powershell
git clone https://github.com/DiegoT21/Auto-Hub.git C:\AutoHub
cd C:\AutoHub
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
wscript launch_autohub.vbs
```

Python 3.10+ con PATH. Git opcional si usas el ZIP.

Luego: **Actualizar app** en Auto-Hub (no hace falta volver a GitHub).

`app_id.txt` de Sage va en `C:\Temp\sage_sdk\` o `scripts\sage_sdk\` (no se sube al repo).
