from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from app import theme
from app.components import glass_card


class WorkflowBar(ctk.CTkFrame):
    """Barra de pasos glass — estilo bento."""

    STEPS = (
        (1, "Importar", "Traer facturas"),
        (2, "Revisar", "Validar y editar"),
        (3, "Carga Sage", "Enviar a Sage 50"),
    )

    def __init__(
        self,
        parent: ctk.CTk,
        on_step: Callable[[int], None],
    ) -> None:
        super().__init__(parent, fg_color="transparent")
        self.on_step = on_step
        self._current = 1
        self._buttons: dict[int, ctk.CTkButton] = {}

        shell = glass_card(self, radius=theme.BENTO_RADIUS)
        shell.pack(fill="x")
        inner = ctk.CTkFrame(shell, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=10)

        for num, title, subtitle in self.STEPS:
            col = glass_card(inner, radius=theme.BENTO_RADIUS_SM)
            col.pack(side="left", expand=True, fill="both", padx=5)

            def make_cmd(n: int) -> Callable[[], None]:
                return lambda: on_step(n)

            b = ctk.CTkButton(
                col,
                text=f"{num}. {title}",
                anchor="w",
                height=42,
                corner_radius=12,
                fg_color="transparent",
                hover_color=theme.GLASS_BG_HOVER,
                text_color=theme.TEXT_SECONDARY,
                font=("Segoe UI", 13, "bold"),
                command=make_cmd(num),
            )
            b.pack(fill="x", padx=8, pady=(10, 0))
            ctk.CTkLabel(
                col,
                text=subtitle,
                font=theme.FONT_SMALL,
                text_color=theme.TEXT_MUTED,
            ).pack(anchor="w", padx=12, pady=(2, 10))
            self._buttons[num] = b

        self.status_label = ctk.CTkLabel(
            self,
            text="Comienza importando facturas desde PsKloud, PDF o CSV.",
            font=theme.FONT_SMALL,
            text_color=theme.TEXT_SECONDARY,
            anchor="w",
        )
        self.status_label.pack(fill="x", pady=(10, 0))

    def set_step(self, step: int) -> None:
        self._current = step
        for num, button in self._buttons.items():
            if num == step:
                button.configure(
                    fg_color=theme.ACCENT,
                    text_color="white",
                    hover_color=theme.ACCENT_HOVER,
                )
            else:
                button.configure(
                    fg_color="transparent",
                    text_color=theme.TEXT_SECONDARY,
                    hover_color=theme.GLASS_BG_HOVER,
                )

    def set_status(self, text: str) -> None:
        self.status_label.configure(text=text)
