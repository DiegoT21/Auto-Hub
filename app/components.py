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


def card(parent, **kwargs) -> ctk.CTkFrame:
    return glass_card(parent, **kwargs)


def glass_input(parent, **kwargs) -> ctk.CTkEntry:
    defaults = dict(
        fg_color=theme.GLASS_INPUT,
        border_color=theme.GLASS_BORDER,
        corner_radius=theme.BENTO_RADIUS_SM,
        text_color=theme.TEXT_PRIMARY,
        placeholder_text_color=theme.TEXT_MUTED,
        height=28,
        font=theme.FONT_BODY,
    )
    defaults.update(kwargs)
    return ctk.CTkEntry(parent, **defaults)


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


def bento_tile(
    parent,
    *,
    icon: str,
    title: str,
    subtitle: str,
    command: Callable[[], None] | None = None,
    accent: bool = False,
    compact: bool = False,
) -> ctk.CTkFrame:
    """Celda bento glass con hover y clic."""
    frame = glass_card(parent, glow=accent, radius=theme.BENTO_RADIUS_SM if compact else theme.BENTO_RADIUS)
    inner = ctk.CTkFrame(frame, fg_color="transparent")
    pad = 14 if compact else 20
    inner.pack(fill="both", expand=True, padx=pad, pady=pad)

    top = ctk.CTkFrame(inner, fg_color="transparent")
    top.pack(fill="x")
    ctk.CTkLabel(top, text=icon, font=("Segoe UI", 28 if compact else 34)).pack(side="left")
    if accent:
        chip = ctk.CTkLabel(
            top,
            text="Recomendado",
            font=("Segoe UI", 9, "bold"),
            text_color=theme.ACCENT_SOFT,
            fg_color=theme.GLASS_BG_ACTIVE,
            corner_radius=8,
            padx=8,
            pady=2,
        )
        chip.pack(side="right")

    ctk.CTkLabel(
        inner,
        text=title,
        font=("Segoe UI", 15 if compact else 17, "bold"),
        text_color=theme.TEXT_PRIMARY,
        anchor="w",
    ).pack(fill="x", pady=(10, 2))
    ctk.CTkLabel(
        inner,
        text=subtitle,
        font=theme.FONT_SMALL,
        text_color=theme.TEXT_SECONDARY,
        wraplength=280 if not compact else 200,
        justify="left",
        anchor="w",
    ).pack(fill="x", pady=(0, 12))

    if command:
        btn(
            inner,
            text="Abrir →",
            variant="primary" if accent else "secondary",
            width=110,
            height=theme.BTN_HEIGHT_SM,
            command=command,
        ).pack(anchor="w")

        def on_enter(_e) -> None:
            frame.configure(fg_color=theme.GLASS_BG_HOVER, border_color=theme.GLASS_BORDER_LIGHT)

        def on_leave(_e) -> None:
            border = theme.GLASS_BORDER_GLOW if accent else theme.GLASS_BORDER
            frame.configure(fg_color=theme.GLASS_BG, border_color=border)

        frame.bind("<Enter>", on_enter)
        frame.bind("<Leave>", on_leave)

    return frame


def stat_chip(parent, label: str, value: str, *, color: str | None = None) -> ctk.CTkFrame:
    box = glass_card(parent, radius=theme.BENTO_RADIUS_SM)
    ctk.CTkLabel(box, text=label, font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED).pack(
        anchor="w", padx=16, pady=(14, 0)
    )
    val_label = ctk.CTkLabel(
        box,
        text=value,
        font=("Segoe UI", 22, "bold"),
        text_color=color or theme.TEXT_PRIMARY,
    )
    val_label.pack(anchor="w", padx=16, pady=(2, 14))
    box._value_label = val_label  # type: ignore[attr-defined]
    return box


def section_title(parent, title: str, subtitle: str = "") -> ctk.CTkFrame:
    wrap = ctk.CTkFrame(parent, fg_color="transparent")
    ctk.CTkLabel(wrap, text=title, font=theme.FONT_TITLE, text_color=theme.TEXT_PRIMARY).pack(anchor="w")
    if subtitle:
        ctk.CTkLabel(
            wrap,
            text=subtitle,
            font=theme.FONT_SUBTITLE,
            text_color=theme.TEXT_SECONDARY,
        ).pack(anchor="w", pady=(4, 0))
    return wrap


CARD_WRAP = 300


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


def invoice_card(parent, payload: dict[str, Any]) -> ctk.CTkFrame:
    """Tarjeta compacta: numero, cliente y, si fallo, el motivo siempre a la vista."""
    ok = bool(payload.get("ok"))
    bar = theme.CARD_DOT_OK if ok else theme.CARD_DOT_ERR
    outer = ctk.CTkFrame(
        parent,
        fg_color=theme.CARD_OK_BG if ok else theme.CARD_ERR_BG,
        corner_radius=8,
        border_width=1,
        border_color=theme.CARD_OK_BORDER if ok else theme.CARD_ERR_BORDER,
    )
    body = ctk.CTkFrame(outer, fg_color="transparent", height=1)
    body.pack(fill="both", expand=True)
    # height=1: sin esto el CTkFrame impone su alto por defecto (200 px) a la tarjeta.
    ctk.CTkFrame(body, width=3, height=1, fg_color=bar, corner_radius=2).pack(side="left", fill="y")
    inner = ctk.CTkFrame(body, fg_color="transparent", height=1)
    inner.pack(side="left", fill="both", expand=True, padx=7, pady=4)

    head = ctk.CTkFrame(inner, fg_color="transparent", height=1)
    head.pack(fill="x")
    card_line(
        head,
        str(payload.get("ref") or "Factura"),
        font=("Segoe UI", 11, "bold"),
        color=theme.TEXT_PRIMARY,
        side="left",
    )
    total = str(payload.get("total") or "").strip()
    if total:
        card_line(
            head,
            total if total.startswith("$") else ("$" + total),
            font=("Segoe UI", 10, "bold"),
            color=theme.TEXT_PRIMARY,
            side="right",
        )

    cust = str(payload.get("customer_name") or payload.get("customer_id") or "").strip()
    date = str(payload.get("date") or "").strip()
    sub = " · ".join(bit for bit in (cust, date) if bit)
    if sub:
        card_line(
            inner,
            sub if len(sub) <= 52 else (sub[:49] + "..."),
            font=("Segoe UI", 9),
            color=theme.TEXT_SECONDARY,
        )

    lines = [ln for ln in (payload.get("lines") or []) if isinstance(ln, dict)]
    if ok:
        n = len(lines)
        card_line(
            inner,
            (str(n) + (" item" if n == 1 else " items") + " en Sage") if n else "Cargada en Sage",
            font=("Segoe UI", 9, "bold"),
            color=theme.CARD_OK_SOFT,
        )
        return outer

    card_line(
        inner,
        fail_summary(payload),
        font=("Segoe UI", 9, "bold"),
        color=theme.CARD_ERR_SOFT,
        wrap=CARD_WRAP,
    )

    detail = str(payload.get("detail") or "").strip() or "Sin detalle de Sage. Revisa Ver logs."
    detail_box = ctk.CTkFrame(inner, fg_color="transparent", height=1)
    bad = [ln for ln in lines if not ln.get("ok")]
    for ln in (bad or lines)[:6]:
        card_line(
            detail_box,
            "L"
            + str(ln.get("n") or "?")
            + "  "
            + str(ln.get("sku") or "(sin codigo)")
            + ("  falta en Sage" if not ln.get("ok") else ""),
            font=("Segoe UI", 9),
            color=theme.CARD_ERR_SOFT if not ln.get("ok") else theme.TEXT_SECONDARY,
        )
    card_line(
        detail_box,
        detail,
        font=("Segoe UI", 9),
        color=theme.TEXT_SECONDARY,
        wrap=CARD_WRAP,
    )

    def toggle() -> None:
        if detail_box.winfo_manager():
            detail_box.pack_forget()
            fix_btn.configure(text="Ver detalle")
        else:
            detail_box.pack(fill="x", pady=(2, 0))
            fix_btn.configure(text="Ocultar")

    fix_btn = btn(
        inner,
        text="Ver detalle",
        variant="danger",
        width=84,
        height=20,
        font=("Segoe UI", 9),
        command=toggle,
    )
    fix_btn.pack(anchor="e", pady=(2, 0))
    return outer
