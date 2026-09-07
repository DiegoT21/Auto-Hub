"""Convierte mensajes tecnicos a eventos cortos para la UI (status / ok / err / skip)."""
from __future__ import annotations

import re

# Lineas internas: no van a la pantalla.
_SKIP_PREFIXES = (
    "carpeta sdk:",
    "json escrito:",
    "json pending:",
    "json:",
    "application id:",
    "sesion iniciada:",
    "companias registradas",
    "empresa abierta via sdk",
    "empresa:",
    "empresa objetivo:",
    "modo: escritura",
    "modo: autorizar",
    "auto-hub - envio",
    "invoice tipo:",
    "customer.key",
    "loadmodifiers",
    "filterexpression",
    "list.load",
    "factory:",
    "usualsalesaccount",
    "version:",
    "fuente cs:",
    "sample json:",
    "preview:",
    "assemblyinitializer",
    "factura origen:",
    "factura de pskloud:",
    "fecha en sage:",
    "fecha de la factura:",
    "sucursal:",
    "cliente pskloud:",
    "cliente en pskloud:",
    "cliente sage:",
    "cliente en sage:",
    "clientes en sage:",
    "referencenumber sage:",
    "numero en sage:",
    "match por",
    "creando salesinvoice",
    "cliente asignado",
    "date/transactiondate",
    "nota sage:",
    "guardando la factura",
    "guardando factura",
    "linea ",
    "  reference:",
    "registrada para no duplicar:",
    "pidiendo permiso",
    "solicitando acceso",
    "already granted",
    "autorizacion: granted",
    "ok - acceso granted",
    "permiso de sage",
    "sage ya habia",
    "ya no deberia pedir",
    "use la misma cuenta",
    "gl copiado",
    "guardando el cliente nuevo",
    "guardando cliente nuevo",
    "este cliente no estaba",
    "aviso apellido",
    "busca invoice no",
    "verificalo en sage",
    "revisa en sage",
    "mapeado desde pskloud",
)

_SKIP_CONTAINS = (
    "clientes en sage (muestra)",
    "hwnd=",
    "sample_invoice",
)


def classify(msg: str) -> tuple[str, str] | None:
    """Devuelve (kind, texto) o None para tirar el mensaje.

    kind: status | load | ok | err | skip
    """
    text = (msg or "").strip()
    if not text:
        return None
    lower = text.lower()

    if any(lower.startswith(p) for p in _SKIP_PREFIXES):
        return None
    if any(s in lower for s in _SKIP_CONTAINS):
        return None
    if text.startswith("  - ") or text.startswith("- LYL"):
        return None
    if text.startswith("  ") and "error" not in lower:
        return None

    mapped = _map(text, lower)
    if not mapped:
        return None
    shown, kind = mapped
    return kind, shown


def friendly_log(msg: str) -> str | None:
    ev = classify(msg)
    return ev[1] if ev else None


def _map(text: str, lower: str) -> tuple[str, str] | None:
    if lower.startswith("[ok]"):
        rest = text.split("]", 1)[-1].strip()
        if "sage conectado" in lower:
            return "Sage esta listo.", "status"
        return rest, "status"
    if lower.startswith("[err]") or lower.startswith("[...]"):
        return text.split("]", 1)[-1].strip(), "err"

    if "modo automatico on" in lower:
        return "Automatico ON. Buscando facturas.", "status"
    if "modo automatico off" in lower:
        return "Automatico OFF.", "status"
    if "revisando sage y la nube" in lower:
        return "Consultando Sage y G Core...", "status"
    if "consultando ledger bridge" in lower:
        return "Consultando G Core...", "status"
    if "ledger bridge:" in lower and "lote" in lower:
        n = re.search(r"(\d+)", text)
        cuantas = n.group(1) if n else ""
        return "Hay " + cuantas + " factura(s) en cola.", "status"
    if "nube sin pendientes" in lower:
        return "Cola vacia. Esperando facturas nuevas.", "status"
    if "ledger bridge:" in lower and "http" in lower:
        return "Conectado a G Core.", "status"
    if "sin jwt" in lower:
        return "Falta la clave de G Core en config.", "err"
    if "sage debe quedar abierto" in lower or "deja abierta lyl" in lower:
        return "Deja Sage abierto en LYL 2025-2026.", "status"
    if "sage no esta abierto" in lower:
        return "Sage no esta abierto. Abre LYL 2025-2026.", "err"
    if lower.startswith("enviando "):
        rest = text[len("Enviando ") :].strip()
        if "|" in rest:
            num, cliente = [p.strip() for p in rest.split("|", 1)]
            label = (num.split(":")[-1] if ":" in num else num) + " · " + cliente
            return label, "load"
        return rest, "load"
    if "ya enviada" in lower:
        return "Ya estaba en Sage. No se duplica.", "skip"
    if "lote incompleto" in lower:
        return "Dato incompleto (sin cliente o numero).", "err"
    if "factura vieja" in lower:
        n = re.search(r"(\d+)", text)
        cuantas = n.group(1) if n else "1"
        return cuantas + " vieja(s) marcadas en la nube.", "skip"
    if "pending sin facturas usables" in lower:
        return "La nube mando un dato inutilizable.", "err"
    if "ledger bridge ack ok" in lower:
        conf = re.search(r"confirmed=(\d+)", lower)
        n = conf.group(1) if conf else "?"
        return "Nube confirmo " + n + ".", "status"
    if "ledger bridge ack fallo" in lower:
        return "No se pudo marcar en la nube.", "err"
    if lower.startswith("error automatico") or lower.startswith("error auto "):
        return _short_err(text), "err"
    if "ciclo extractor:" in lower or ("ciclo " in lower and "enviadas=" in lower):
        return None
    if "ok - factura guardada" in lower or "listo: la factura ya esta" in lower:
        return "Cargada en Sage.", "ok"
    if "conectando con sage" in lower or "hablando con sage" in lower:
        return "Hablando con Sage...", "status"
    if "always allow" in lower and "accion en sage" in lower:
        return "En Sage, elige Always Allow una vez.", "status"
    if "no se pudo crear el cliente" in lower or "error creando cliente" in lower:
        return "Sage no dejo crear el cliente.", "err"
    if "enviar a sage salio con codigo" in lower or "conectar sage salio" in lower or "sage no pudo guardar" in lower:
        return _short_err(text), "err"
    if "se agoto el tiempo" in lower:
        return "Sage no contesto. Revisa Always Allow.", "err"
    if "dump sage:" in lower:
        return "Detalle de Sage guardado. Ver logs.", "status"
    if "sistema listo" in lower:
        return "Auto-Hub listo.", "status"
    if "ok — sage conectado" in lower or "ok - sage conectado" in lower:
        return "Sage conectado.", "status"
    if "actualizando auto-hub" in lower:
        return "Actualizando Auto-Hub...", "status"
    if "actualizado. reiniciando" in lower:
        return "Actualizado. Reiniciando...", "status"
    return None


def _short_err(text: str) -> str:
    lower = text.lower()
    m = re.search(r"(000002:[^\s]+|C\d{7}|\*\d+)", text)
    who = m.group(1).split(":")[-1] if m else ""
    if "rounded" in lower or "whole currency" in lower:
        tip = "Sage: hay que redondear el monto"
    elif "qty" in lower and "unit price" in lower:
        tip = "Sage: cantidad x precio no cuadra"
    elif "current period" in lower:
        tip = "Sage: fecha fuera del periodo"
    elif "codigo 3" in lower or "falto el cliente" in lower:
        tip = "Falto el cliente"
    elif "codigo 99" in lower:
        tip = "Sage rechazo la factura"
    else:
        tip = "No se pudo guardar"
    return (who + " · " + tip) if who else tip
