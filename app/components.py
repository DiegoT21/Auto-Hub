from __future__ import annotations

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


def fail_summary(payload: dict[str, Any]) -> str:
    """Una linea corta que siempre dice por que fallo la factura."""
    lines = [ln for ln in (payload.get("lines") or []) if isinstance(ln, dict)]
    missing = list(
        dict.fromkeys(
            str(ln.get("sku") or "").strip()
            for ln in lines
            if not ln.get("ok") and str(ln.get("sku") or "").strip()
        )
    )
    if missing:
        word = "item" if len(missing) == 1 else "items"
        shown = ", ".join(missing[:3]) + (" +" + str(len(missing) - 3) if len(missing) > 3 else "")
        return "Faltan " + str(len(missing)) + " " + word + " en Sage: " + shown
    detail = str(payload.get("detail") or "").strip()
    if detail:
        first = detail.splitlines()[0].strip()
        return first if len(first) <= 120 else (first[:117] + "...")
    return "Sage no guardo la factura. Abre Ver detalle."


def dashboard_card(
    parent,
    payload: dict[str, Any],
    *,
    tone: str,
    selected: bool,
    on_open: Callable[[], None],
    on_solution: Callable[[], None] | None = None,
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
    inner.pack(fill="x", padx=10, pady=8)
    head = ctk.CTkFrame(inner, fg_color="transparent", height=1)
    head.pack(fill="x")
    card_line(
        head,
        "#" + str(payload.get("ref") or "Factura").lstrip("#"),
        font=("Segoe UI", 12, "bold"),
        color=theme.TEXT_PRIMARY,
        side="left",
    )
    chip = ctk.CTkLabel(
        head,
        text=badge,
        font=("Segoe UI", 9, "bold"),
        text_color=badge_fg,
        fg_color=badge_bg,
        corner_radius=8,
        height=18,
        padx=6,
    )
    chip.pack(side="left", padx=(8, 0))
    if tone == "ok":
        total = str(payload.get("total") or "").strip()
        if total:
            card_line(
                head,
                total if total.startswith("$") else ("$" + total),
                font=("Segoe UI", 12, "bold"),
                color=theme.TEXT_PRIMARY,
                side="right",
            )
    cust = str(payload.get("customer_name") or payload.get("customer_id") or "").strip()
    if cust:
        card_line(inner, "Cliente: " + cust, font=("Segoe UI", 10), color=theme.TEXT_SECONDARY)
    if tone != "ok":
        card_line(
            inner,
            fail_summary(payload),
            font=("Segoe UI", 10, "bold"),
            color=accent,
            wrap=260,
        )
    else:
        lines = [ln for ln in (payload.get("lines") or []) if isinstance(ln, dict)]
        n = len(lines)
        card_line(
            inner,
            (str(n) + (" item en Sage" if n == 1 else " items en Sage")) if n else "Cargada en Sage",
            font=("Segoe UI", 10, "bold"),
            color=accent,
        )
    meta = " · ".join(bit for bit in (str(payload.get("date") or "").strip(),) if bit)
    if meta:
        card_line(inner, meta, font=("Segoe UI", 10), color=theme.TEXT_SECONDARY)
    if tone != "ok":
        actions = ctk.CTkFrame(inner, fg_color="transparent", height=1)
        actions.pack(anchor="e", pady=(4, 0))
        if tone == "wait" and on_solution:
            btn(
                actions,
                text="Ver solución",
                variant="secondary",
                width=108,
                height=26,
                font=("Segoe UI", 10),
                command=on_solution,
            ).pack(side="left", padx=(0, 6))
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
