from __future__ import annotations

import re
from typing import Any, Callable

import customtkinter as ctk

from app import theme

ButtonVariant = str  # primary | secondary | ghost | danger


def glass_card(parent, *, glow: bool = False, radius: int | None = None, **kwargs) -> ctk.CTkFrame:
    border = theme.GLASS_BORDER_GLOW if glow else theme.GLASS_BORDER
    defaults = dict(
        fg_color=theme.GLASS_BG,
        corner_radius=radius or theme.BENTO_RADIUS,
        border_width=1,
        border_color=border,
    )
    defaults.update(kwargs)
    return ctk.CTkFrame(parent, **defaults)


def btn(
    parent,
    text: str,
    command=None,
    *,
    variant: ButtonVariant = "secondary",
    width: int | None = None,
    height: int | None = None,
    font=None,
    **kwargs,
) -> ctk.CTkButton:
    height = height or theme.BTN_HEIGHT
    font = font or theme.BTN_FONT

    styles: dict[str, dict] = {
        "primary": {
            "fg_color": theme.BTN_PRIMARY,
            "hover_color": theme.BTN_PRIMARY_HOVER,
            "text_color": theme.BTN_PRIMARY_TEXT,
            "border_width": 1,
            "border_color": theme.ACCENT_SOFT,
        },
        "secondary": {
            "fg_color": theme.BTN_SECONDARY,
            "hover_color": theme.BTN_SECONDARY_HOVER,
            "text_color": theme.BTN_SECONDARY_TEXT,
            "border_width": 1,
            "border_color": theme.BTN_SECONDARY_BORDER,
        },
        "ghost": {
            "fg_color": "transparent",
            "hover_color": theme.BTN_GHOST_HOVER,
            "text_color": theme.TEXT_SECONDARY,
            "border_width": 1,
            "border_color": theme.GLASS_BORDER,
        },
        "danger": {
            "fg_color": theme.BTN_DANGER_BG,
            "hover_color": theme.BTN_DANGER_HOVER,
            "text_color": theme.BTN_DANGER_TEXT,
            "border_width": 1,
            "border_color": theme.BTN_DANGER_BORDER,
        },
    }
    style = styles.get(variant, styles["secondary"])
    opts = {**style, "corner_radius": theme.BTN_RADIUS, "font": font, "height": height}
    if width is not None:
        opts["width"] = width
    opts.update(kwargs)
    return ctk.CTkButton(parent, text=text, command=command, **opts)


def card_line(parent, text: str, *, font, color: str, wrap: int = 0, side: str | None = None):
    """Etiqueta de tarjeta que mide por su texto (CTkLabel trae 28 px fijos por defecto)."""
    label = ctk.CTkLabel(
        parent,
        text=text,
        font=font,
        text_color=color,
        height=1,
        anchor="w",
        justify="left",
        **({"wraplength": wrap} if wrap else {}),
    )
    if side:
        label.pack(side=side)
    else:
        label.pack(fill="x")
    return label


def display_ref(payload: dict[str, Any]) -> str:
    ref = str(payload.get("ref") or "").strip().lstrip("#")
    if not ref:
        return "Factura sin número"
    return ref if ref[0] in "*C" or ref.upper().startswith("AH") else "#" + ref


def money(value: Any) -> str:
    text = str(value or "").strip().lstrip("$").replace(",", "")
    try:
        return "${:,.2f}".format(float(text))
    except ValueError:
        return ("$" + text) if text else ""


def _missing_skus(payload: dict[str, Any]) -> list[str]:
    lines = [ln for ln in (payload.get("lines") or []) if isinstance(ln, dict)]
    missing = [
        str(ln.get("sku") or "").strip()
        for ln in lines
        if not ln.get("ok") and str(ln.get("sku") or "").strip()
    ]
    if not missing:
        found = re.search(r"faltan? \d+ items? en sage:\s*(.+)", str(payload.get("detail") or ""), re.I)
        if found:
            missing = [s.strip() for s in found.group(1).split(",") if s.strip()]
    return list(dict.fromkeys(missing))


def _customer(payload: dict[str, Any]) -> str:
    name = str(payload.get("customer_name") or "").strip()
    cid = str(payload.get("customer_id") or "").strip()
    if name and cid:
        return name + " (ID " + cid + ")"
    return name or (("ID " + cid) if cid else "")


def explain_failure(payload: dict[str, Any]) -> tuple[str, str]:
    """(que paso, que hacer) con los datos de la factura, para tarjeta y detalle."""
    detail = str(payload.get("detail") or "").strip()
    first = detail.splitlines()[0].strip() if detail else ""
    low = detail.lower()
    missing = _missing_skus(payload)
    if missing:
        word = "item" if len(missing) == 1 else "items"
        shown = ", ".join(missing[:3]) + (" +" + str(len(missing) - 3) if len(missing) > 3 else "")
        return (
            "Faltan " + str(len(missing)) + " " + word + " en Sage: " + shown,
            "Crea " + ("ese item" if len(missing) == 1 else "esos items")
            + " en el inventario de Sage con el mismo código y pulsa Reintentar pendientes.",
        )
    if "total no cuadra" in low or "itbms no cuadra" in low:
        return (
            first,
            "PsKloud y Sage calculan distinto (precio, descuento o ITBMS). No se cargó para no descuadrar: "
            "revisa la factura en PsKloud.",
        )
    if "faltan items: llegaron" in low or "incomplet" in low:
        return (first, "La factura llegó incompleta desde G Core. Reenvíala desde el Extractor.")
    if "crear el cliente" in low or "creando cliente" in low:
        who = _customer(payload)
        return (
            "Sage no dejó crear el cliente" + (" " + who if who else "") + ".",
            "Créalo en Sage con ese ID, nombre y dirección, y vuelve a enviar la factura.",
        )
    if "reference number is not unique" in low:
        return (
            "Sage ya tiene otra factura con esta referencia para el cliente" + (" " + _customer(payload) if _customer(payload) else "") + ".",
            "Casi siempre es porque ya se cargó antes. Búscala en Sage (Sales Invoices) antes de reintentar para no duplicar.",
        )
    if "no se pudo guardar" in low:
        return (
            "Sage no guardó la factura (no dio el motivo).",
            "Suele ser un bloqueo momentáneo de Sage: otra ventana abierta o Sage ocupado. "
            "La nube la reenvía en el próximo ciclo; si se repite, mira el detalle técnico.",
        )
    if "period" in low or "periodo" in low:
        return (first, "La fecha cae en un periodo cerrado de Sage. Abre el periodo o corrige la fecha.")
    if first:
        return (first if len(first) <= 140 else first[:137] + "...", "Abre Ver detalle para ver la respuesta completa de Sage.")
    return ("Sage rechazó la factura sin dar motivo.", "Abre Ver detalle para ver la respuesta completa de Sage.")


def fail_summary(payload: dict[str, Any]) -> str:
    """Una linea corta que siempre dice por que fallo la factura."""
    return explain_failure(payload)[0]


def dashboard_card(
    parent,
    payload: dict[str, Any],
    *,
    tone: str,
    selected: bool,
    on_open: Callable[[], None],
    on_solution: Callable[[], None] | None = None,
    wrap: int = 420,
) -> ctk.CTkFrame:
    """Tarjeta del tablero: verde cargada, amarilla corregible, roja fallida."""
    if tone == "ok":
        bg, border, accent, badge_bg, badge_fg, badge = (
            theme.CARD_OK_BG,
            theme.CARD_OK_BORDER,
            theme.CARD_OK_SOFT,
            "#D1FAE5",
            "#047857",
            "Procesada",
        )
    elif tone == "wait":
        bg, border, accent, badge_bg, badge_fg, badge = (
            "#FFFBEB",
            "#FDE68A",
            "#B45309",
            "#FEF3C7",
            "#B45309",
            "Esperando corrección",
        )
    else:
        bg, border, accent, badge_bg, badge_fg, badge = (
            theme.CARD_ERR_BG,
            theme.CARD_ERR_BORDER,
            theme.CARD_ERR_SOFT,
            "#FEE2E2",
            "#B91C1C",
            "Fallida",
        )
    outer = ctk.CTkFrame(
        parent,
        fg_color=bg,
        corner_radius=10,
        border_width=2 if selected else 1,
        border_color=theme.ACCENT if selected else border,
        height=1,
    )
    inner = ctk.CTkFrame(outer, fg_color="transparent", height=1)
    inner.pack(fill="x", padx=10, pady=5 if tone == "ok" else 8)
    head = ctk.CTkFrame(inner, fg_color="transparent", height=1)
    head.pack(fill="x")
    card_line(
        head,
        display_ref(payload),
        font=("Segoe UI", 12, "bold"),
        color=theme.TEXT_PRIMARY,
        side="left",
    )
    if tone != "ok":
        ctk.CTkLabel(
            head,
            text=badge,
            font=("Segoe UI", 9, "bold"),
            text_color=badge_fg,
            fg_color=badge_bg,
            corner_radius=8,
            height=18,
            padx=6,
        ).pack(side="left", padx=(8, 0))
    total = money(payload.get("total"))
    if total:
        card_line(
            head,
            total,
            font=("Segoe UI", 12, "bold"),
            color=theme.TEXT_PRIMARY,
            side="right",
        )
    meta = " · ".join(
        bit
        for bit in (
            _customer(payload) if tone != "ok" else str(payload.get("customer_name") or payload.get("customer_id") or "").strip(),
            str(payload.get("date") or "").strip()[:10],
        )
        if bit
    )
    if meta:
        card_line(inner, meta, font=("Segoe UI", 10), color=theme.TEXT_SECONDARY, wrap=wrap)
    if tone != "ok":
        reason, action = explain_failure(payload)
        card_line(inner, reason, font=("Segoe UI", 10, "bold"), color=accent, wrap=wrap)
        card_line(inner, action, font=("Segoe UI", 10), color=theme.TEXT_SECONDARY, wrap=wrap)
        actions = ctk.CTkFrame(inner, fg_color="transparent", height=1)
        actions.pack(anchor="e", pady=(4, 0))
        btn(
            actions,
            text="Ver detalle",
            variant="primary" if selected else "secondary",
            width=96,
            height=26,
            font=("Segoe UI", 10),
            command=on_open,
        ).pack(side="left")
        outer._detail_btn = actions.winfo_children()[-1]  # type: ignore[attr-defined]
    outer._base_border = border  # type: ignore[attr-defined]
    outer.bind("<Button-1>", lambda _e: on_open())
    inner.bind("<Button-1>", lambda _e: on_open())
    return outer


def set_card_selected(card: ctk.CTkFrame, selected: bool) -> None:
    """Resalta la tarjeta elegida sin volver a construirla."""
    base = getattr(card, "_base_border", theme.GLASS_BORDER)
    card.configure(border_width=2 if selected else 1, border_color=theme.ACCENT if selected else base)
    detail_btn = getattr(card, "_detail_btn", None)
    if detail_btn is None:
        return
    if selected:
        detail_btn.configure(fg_color=theme.BTN_PRIMARY, hover_color=theme.BTN_PRIMARY_HOVER, text_color=theme.BTN_PRIMARY_TEXT, border_color=theme.ACCENT_SOFT)
    else:
        detail_btn.configure(fg_color=theme.BTN_SECONDARY, hover_color=theme.BTN_SECONDARY_HOVER, text_color=theme.BTN_SECONDARY_TEXT, border_color=theme.BTN_SECONDARY_BORDER)
