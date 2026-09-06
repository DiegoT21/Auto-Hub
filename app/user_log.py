"""Convierte mensajes tecnicos del SDK/nube a frases para quien usa Auto-Hub."""
from __future__ import annotations

import re

# Lineas internas que no ayudan al usuario.
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
)

_SKIP_CONTAINS = (
    "clientes en sage (muestra)",
    "hwnd=",
    "sample_invoice",
)


def friendly_log(msg: str) -> str | None:
    text = (msg or "").strip()
    if not text:
        return None
    lower = text.lower()

    if any(lower.startswith(p) for p in _SKIP_PREFIXES):
        return None
    if any(s in lower for s in _SKIP_CONTAINS):
        return None
    if text.startswith("  - ") or (text.startswith("  ") and "cliente nuevo" not in lower and "match" not in lower and "guardando" not in lower and "gl copiado" not in lower):
        if "linea " in lower and ("qty=" in lower or "price=" in lower):
            return _line_item(text)
        return None

    mapped = _map(text, lower)
    return mapped if mapped else text


def _line_item(text: str) -> str:
    m = re.search(r"Linea\s+(\d+).*?\|\s*(.+)$", text, re.I)
    if m:
        return "Linea " + m.group(1) + ": " + m.group(2).strip()
    return None


def _map(text: str, lower: str) -> str | None:
    if lower.startswith("[ok]"):
        rest = text.split("]", 1)[-1].strip()
        if "sage conectado" in lower:
            return "Sage esta listo."
        return rest
    if lower.startswith("[err]") or lower.startswith("[...]"):
        return text.split("]", 1)[-1].strip()

    if "modo automatico on" in lower:
        return "Modo automatico encendido. Voy a buscar facturas nuevas."
    if "modo automatico off" in lower:
        return "Modo automatico apagado."
    if "ledger bridge:" in lower and "lote" in lower:
        n = re.search(r"(\d+)", text)
        cuantas = n.group(1) if n else ""
        return "Hay " + cuantas + " factura(s) esperando para entrar a Sage."
    if "ledger bridge:" in lower and "http" in lower:
        return "Conectado a la nube (G Core)."
    if "sin jwt" in lower:
        return "Falta la credencial de G Core. Hay que copiar el archivo de la clave en la carpeta config."
    if "sage debe quedar abierto" in lower or "deja abierta lyl" in lower:
        return "Deja Sage abierto en la empresa LYL 2025-2026."
    if "sage no esta abierto" in lower:
        return "Sage no esta abierto. Abre la empresa LYL para poder cargar facturas."
    if "sage esta abierto: bien" in lower:
        return "Sage esta abierto. Todo bien."
    if lower.startswith("enviando "):
        rest = text[len("Enviando ") :].strip()
        if "|" in rest:
            num, cliente = [p.strip() for p in rest.split("|", 1)]
            if cliente:
                return "Cargando en Sage la factura " + num + " de " + cliente + "."
            return "Cargando en Sage la factura " + num + "."
        return "Cargando una factura en Sage."
    if "ya enviada" in lower:
        return "Esa factura ya estaba en Sage. No se volvio a cargar."
    if "lote incompleto" in lower:
        return "Llego un dato incompleto (sin cliente o sin numero). No se carga a Sage."
    if "factura vieja" in lower:
        n = re.search(r"(\d+)", text)
        if n and "anos atras" in lower:
            return n.group(1) + " factura(s) viejas. No las cargo en Sage; las marco en la nube."
        return "Esa factura es de anos atras. No la cargo en Sage 2025-2026; la marco como vista en la nube."
    if "pending sin facturas usables" in lower:
        return "La nube mando un dato que no se puede usar como factura."
    if "ledger bridge ack ok" in lower:
        conf = re.search(r"confirmed=(\d+)", lower)
        n = conf.group(1) if conf else "?"
        return "La nube confirmo " + n + " factura(s). Si es 0, siguen en cola; si es 25, en el siguiente ciclo deberian venir otras."
    if "ledger bridge ack fallo" in lower and "confirmed=0" in lower:
        return "La nube recibio el aviso pero confirmo 0. Esas facturas siguen reservadas."
    if lower.startswith("error automatico"):
        return "Algo fallo al revisar facturas. " + _soften_error(text.split(":", 1)[-1])
    if lower.startswith("extractor lote:"):
        return "Encontre un lote de facturas en esta computadora."
        detail = text.split(":", 1)[-1].strip()
        return "No se pudo cargar esa factura. " + _soften_error(detail)
    if "ciclo extractor:" in lower or "ciclo " in lower and "enviadas=" in lower:
        sent = re.search(r"enviadas=(\d+)", lower)
        skip = re.search(r"omitidas=(\d+)", lower)
        fail = re.search(r"error=(\d+)", lower)
        return (
            "Resumen: "
            + (sent.group(1) if sent else "0")
            + " cargada(s), "
            + (skip.group(1) if skip else "0")
            + " omitida(s), "
            + (fail.group(1) if fail else "0")
            + " con error."
        )
    if "cliente no existe" in lower or "se crea:" in lower:
        return "Este cliente no estaba en Sage. Lo estoy creando ahora."
    if "alta nueva por auto-hub" in lower or "cliente nuevo" in lower and "primera factura" in lower:
        return "Primera factura de un cliente nuevo: en Sage quedara marcado CLIENTE NUEVO."
    if "guardando cliente nuevo" in lower:
        return "Guardando el cliente nuevo en Sage."
    if "gl copiado" in lower:
        return "Use la misma cuenta de ventas que los clientes de contado."
    if "ok - factura guardada" in lower:
        return "Listo: la factura ya esta en Sage."
    if "guardando factura" in lower:
        return "Guardando la factura en Sage..."
    if "conectando con sage" in lower:
        return "Hablando con Sage..."
    if "solicitando acceso" in lower:
        return "Pidiendo permiso a Sage..."
    if "already granted" in lower or "autorizacion: granted" in lower:
        return "Sage ya habia dado permiso. No hay que hacer nada."
    if "ok - acceso granted" in lower:
        return "Permiso de Sage confirmado."
    if "always allow" in lower and "accion en sage" in lower:
        return "En Sage, elige Always Allow una sola vez."
    if "factura origen:" in lower:
        num = text.split(":", 1)[-1].strip()
        return "Factura de PsKloud: " + num
    if "fecha en sage:" in lower:
        return "Fecha de la factura: " + text.split(":", 1)[-1].strip().split("(")[0].strip()
    if lower.startswith("sucursal:"):
        return "Sucursal: " + text.split(":", 1)[-1].strip()
    if "cliente pskloud:" in lower:
        rest = text.split(":", 1)[-1].strip()
        if rest in ("|", "", "|"):
            return None
        return "Cliente en PsKloud: " + rest
    if "cliente factura:" in lower:
        rest = text.split(":", 1)[-1].strip()
        if "sin codigo" in rest.lower() and "sin nombre" in rest.lower():
            return "Esta factura no trae cliente. No se puede cargar."
        return "Cliente: " + rest
    if "cliente sage:" in lower:
        return "Cliente en Sage: " + text.split(":", 1)[-1].strip()
    if "referencenumber sage:" in lower or lower.startswith("  reference:"):
        return "Numero en Sage: " + text.split(":", 1)[-1].strip()
    if "no hay match" in lower:
        return "Ese cliente no aparecia en Sage."
    if "no se encontro el cliente" in lower or "factura sin cliente" in lower:
        return "No hay cliente para esta factura. Si trae nombre, Auto-Hub lo crea; si viene vacio, se omite."
    if "no se pudo crear el cliente" in lower:
        return "Sage no dejo crear el cliente. Revisa el nombre o el codigo."
    if "enviar a sage salio con codigo" in lower:
        return "Sage no pudo guardar esta factura. " + _soften_error(text)
    if "error creando cliente" in lower:
        return "No se pudo crear el cliente en Sage."
    if "verificalo en sage" in lower:
        return "Revisa en Sage: Ventas → Facturas. Busca un numero que empiece con AH."
    if "busca invoice no" in lower:
        return None
    if "mapeado desde pskloud" in lower:
        return "Se uso el cliente de Sage equivalente: " + text.split(":", 1)[-1].strip()
    if "factura ya enviada a sage" in lower:
        return "Esa factura ya se habia enviado. " + text.split(":", 1)[-1].strip()
    if "sistema listo" in lower:
        return "Auto-Hub listo."
    if "conexion activa" in lower:
        return "Base de datos: " + text.split(":", 1)[-1].strip()
    return None


def _soften_error(detail: str) -> str:
    d = detail.strip()
    lower = d.lower()
    if "codigo 3" in lower:
        return "Falto el cliente o el dato venia vacio."
    if "codigo 4" in lower:
        return "Al cliente le falta la cuenta de ventas en Sage."
    if "http 401" in lower or "http 403" in lower:
        return "La credencial de G Core no fue aceptada."
    if "pending http" in lower:
        return "No se pudo consultar la nube."
    if "ack" in lower:
        return "La factura se cargo, pero no se pudo marcar como lista en la nube."
    return d
