from __future__ import annotations

from typing import Callable

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
        height=36,
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
