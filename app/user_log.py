"""Convierte mensajes tecnicos a eventos cortos para la UI (status / ok / err / skip)."""
from __future__ import annotations

import json
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
    "cliente no existe en sage. se crea",
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
    "permiso de sage",
    "sage ya habia",
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


def parse_invoice_card(text: str) -> dict | None:
    raw = (text or "").strip()
    if raw.lower().startswith("[card]"):
        raw = raw.split("]", 1)[-1].strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def classify(msg: str) -> tuple[str, str] | None:
    """Devuelve (kind, texto) o None para tirar el mensaje.

    kind: status | load | ok | err | skip | card
    """
    text = (msg or "").strip()
    if not text:
        return None
    lower = text.lower()

    if lower.startswith("[card]"):
        return "card", text

    if lower.startswith("[trace]"):
        if (
            " fail " in lower
            or "ultimo_fail" in lower
            or "aviso win32" in lower
            or "add-type exception" in lower
        ):
            mapped = _map(text, lower)
            if mapped:
                shown, kind = mapped
                return kind, shown
            return "err", "Fallo Sage: " + text[:220]
        return None

    if any(lower.startswith(p) for p in _SKIP_PREFIXES):
        if not (
            lower.startswith("linea ")
            and ("item creado" in lower or "sin item" in lower or "item=" in lower)
        ):
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
    if lower.startswith("[card]"):
        return text, "card"
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
    if "borrador, no se carga" in lower or "recibida (no emitida" in lower:
        rest = text.split(":", 1)[-1].strip() if ":" in text else text
        return rest or "Borrador TMP. No se carga a Sage.", "skip"
    if "sin item_codigo de pskloud" in lower or "sin item_codigo |" in lower:
        rest = text.split("|", 1)[-1].strip() if "|" in text else ""
        return (
            "G Core no trajo codigo de item"
            + ((" · " + rest) if rest else "")
            + ". No se guardo."
        ), "err"
    if "lote incompleto" in lower:
        return "Dato incompleto (sin cliente o numero).", "err"
    if "factura vieja" in lower:
        n = re.search(r"(\d+)", text)
        cuantas = n.group(1) if n else "1"
        return cuantas + " vieja(s) marcadas en la nube.", "skip"
    if "pending sin facturas usables" in lower:
        return "La nube mando un dato inutilizable.", "err"
    if "ledger bridge nack ok" in lower:
        kind = "permanente" if "permanent=true" in lower else "para reintento"
        sent = re.search(r"sent=(\d+)", lower)
        n = sent.group(1) if sent else "?"
        return "Nube dejo " + n + " factura(s) en fallo " + kind + ".", "status"
    if "ledger bridge nack fallo" in lower:
        return "No se pudo reportar el fallo a la nube.", "err"
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
    if "already granted" in lower or "ok - acceso granted" in lower:
        return "Sage autorizo Always Allow.", "status"
    if "solicitando acceso" in lower:
        return "Pidiendo acceso a Sage...", "status"
    if "ya no deberia pedir" in lower:
        return "Sage ya no deberia pedir Allow en cada carga.", "status"
    if lower.startswith("error fallida"):
        return _short_err(text), "err"
    if lower.startswith("error:") or lower.startswith("add-type"):
        if (
            "no existe en sage" in lower
            or ("faltan " in lower and "items en sage" in lower)
            or "codigo 16" in lower
            or "no se pudo crear item" in lower
        ):
            return _short_err(text), "err"
        rest = text.split(":", 1)[-1].strip() if ":" in text else text
        return (rest[:180] or "Sage host fallo."), "err"
    if "no se pudo crear el cliente" in lower or "error creando cliente" in lower:
        return "Sage no dejo crear el cliente.", "err"
    if "borrando facturas ah" in lower:
        return "Borrando facturas AH de Sage...", "status"
    if lower.startswith("borrada:"):
        rest = text.split(":", 1)[-1].strip()
        return "Borrada " + rest, "status"
    if "ok - facturas ah borradas" in lower:
        rest = text.split(":", 1)[-1].strip()
        return "Borradas de Sage: " + rest, "ok"
    if lower.startswith("no se pudo borrar"):
        return text, "err"
    if "quitadas de enviadas" in lower:
        return "Lista de enviadas actualizada.", "status"
    if "gl ventas sucursal" in lower:
        rest = text.split(":", 1)[-1].strip()
        return "Cuenta ventas Sage: " + rest, "status"
    if "gl descuento sucursal" in lower:
        rest = text.split(":", 1)[-1].strip()
        return "Cuenta descuento Sage: " + rest, "status"
    if "sage sigue minimizado" in lower or "con sage minimizado" in lower:
        return "Sage esta minimizado. Restauralo a pantalla y reintenta.", "err"
    if lower.startswith("[trace]"):
        fn = re.search(r"fn=([^\s]+)", text)
        paso = re.search(r"paso=([^\s]+)", text)
        linea = re.search(r"linea=([^\s]+)", text)
        sku = re.search(r"sku=([^\s]+)", text)
        bits = []
        if fn:
            bits.append(fn.group(1))
        if paso:
            bits.append("paso " + paso.group(1))
        if linea:
            bits.append("linea " + linea.group(1))
        if sku:
            bits.append("SKU " + sku.group(1))
        where = " · ".join(bits) if bits else text[7:80].strip()
        return "Fallo Sage: " + where, "err"
    if "aviso win32 ui no cargo" in lower:
        rest = text.split(":", 1)[-1].strip() if ":" in text else text
        return "Win32 UI no cargo: " + rest[:180], "err"
    if "sage restaurado" in lower:
        return "Sage restaurado. Abriendo inventario...", "status"
    if "prueba full sage" in lower:
        return "Prueba full de factura en Sage...", "status"
    if "reporte de prueba full" in lower:
        rest = text.split(":", 1)[-1].strip() if ":" in text else text
        return "Reporte de prueba: " + rest, "status"
    if lower.startswith("prueba full:"):
        if "fallo" in lower:
            return text[:220], "err"
        return text[:220], "ok"
    if "error prueba full" in lower:
        return text[:220], "err"
    if "factura de prueba guardada" in lower:
        return "Factura de prueba guardada. Borrando esa AH...", "status"
    if "no se guardo la factura. no se borra" in lower:
        return "La prueba no se guardo. No se borro nada.", "err"
    if "no se pudo borrar la factura de prueba" in lower:
        return "Se creo la prueba pero no se pudo borrar. Revisa Sage.", "err"
    if "probando match de items" in lower or "probando crear items" in lower:
        return "Probando match de items en Sage...", "status"
    if lower.startswith("probe "):
        if "ninguna via" in lower:
            return text[:180], "err"
        if "resumen" in lower:
            any_ok = "=OK" in text or "=ok" in text
            return text, "ok" if any_ok else "err"
        return text[:180], "status"
    if "nube repitio" in lower:
        return text[:200], "skip"
    if "itbms no cuadra, no se carga a sage" in lower:
        rest = text.split(":", 1)[-1].strip() if ":" in text else text
        return (rest[:220] or "ITBMS de la factura no cuadra con Sage."), "err"
    if "factura incompleta, no se carga a sage" in lower:
        rest = text.split(":", 1)[-1].strip() if ":" in text else text
        return (rest[:220] or "La factura llego sin todos sus items."), "err"
    if "sigue incompleta, en espera" in lower:
        rest = text.split(":", 1)[-1].strip() if ":" in text else text
        return "Esperando los items que faltan: " + rest, "skip"
    if "fallida guardada" in lower:
        rest = text.split(":", 1)[-1].strip() if ":" in text else text
        return "En cola hasta crear items en Sage: " + rest, "err"
    if "items faltantes en sage" in lower:
        return text[:220], "err"
    if "ya en cola de fallidas" in lower:
        rest = text.split(":", 1)[-1].strip() if ":" in text else text
        return "Esperando items: " + rest, "skip"
    if "reenviando" in lower and "fallida" in lower:
        return "Reenviando facturas fallidas...", "status"
    if lower.startswith("enviando fallida "):
        rest = text[len("Enviando fallida ") :].strip()
        return rest, "load"
    if "fallida cargada" in lower:
        return "Fallida cargada en Sage.", "status"
    if lower.startswith("fallidas: cargadas"):
        return text[:180], "ok" if "siguen 0" in lower else "status"
    if "sigue sin item en sage" in lower:
        return text[:220], "err"
    if "no hay facturas fallidas" in lower:
        return "No hay facturas fallidas.", "status"
    if (
        "no existe en sage" in lower
        or ("faltan " in lower and ("item en sage" in lower or "items en sage" in lower))
        or "no se pudo crear item sage" in lower
        or "no se pudo poner item id" in lower
    ):
        return "El item no esta en Sage. La factura no se guardo.", "err"
    if lower.startswith("[item]"):
        rest = text.split("]", 1)[-1].strip()
        if "fallo" in lower:
            return rest, "err"
        return rest, "status"
    if "item creado y recargado" in lower:
        return "Item creado en Sage y puesto en la linea.", "status"
    if "no se pudo crear el item" in lower or "no tiene create() de inventario" in lower:
        return "Sage no deja crear items por SDK. Se intenta por ventana.", "status"
    if "item creado en maintain inventory" in lower:
        rest = text.split(":", 1)[-1].strip()
        return "Item creado en la ventana de Sage: " + rest, "status"
    if "abriendo maintain inventory" in lower:
        return "Abriendo Maintain Inventory Items en Sage...", "status"
    if "com import item ok" in lower:
        return "Item importado a Sage por COM.", "status"
    if "item sage encontrado" in lower:
        rest = text.split(":", 1)[-1].strip()
        return "Item Sage: " + rest, "status"
    if "item sage no encontrado" in lower:
        rest = text.split(":", 1)[-1].strip()
        return "Sin item Sage: " + rest, "status"
    if lower.startswith("linea ") and "sin item" in lower:
        return "Linea sin item Sage; se uso cuenta GL.", "status"
    if lower.startswith("linea ") and "item=" in lower:
        return "Linea con item que ya existia en Sage.", "status"
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
    elif "sin item_codigo" in lower:
        tip = "G Core no trajo el codigo del item"
    elif "add-type" in lower or "win32 ui no cargo" in lower:
        tip = "El host Win32 de Sage no cargo (Add-Type)"
    elif (
        "codigo 16" in lower
        or "no existe en sage" in lower
        or ("faltan " in lower and ("item en sage" in lower or "items en sage" in lower))
        or "no se pudo crear item" in lower
    ):
        tip = "El item no existe en Sage"
    elif "codigo 99" in lower:
        tip = "Sage rechazo la factura"
    else:
        tip = "No se pudo guardar"
    return (who + " · " + tip) if who else tip
