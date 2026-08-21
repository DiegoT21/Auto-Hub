from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from app import theme


class WorkflowBar(ctk.CTkFrame):
    """Pasos en una sola fila, sin tarjetas grandes."""

    STEPS = (
        (1, "1. Importar"),
        (2, "2. Revisar"),
        (3, "3. Sage"),
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

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x")

        for num, title in self.STEPS:
            b = ctk.CTkButton(
                row,
                text=title,
                width=110,
                height=26,
                corner_radius=8,
                fg_color="transparent",
                hover_color=theme.GLASS_BG_HOVER,
                text_color=theme.TEXT_SECONDARY,
                font=("Segoe UI", 11, "bold"),
                border_width=1,
                border_color=theme.GLASS_BORDER,
                command=lambda n=num: on_step(n),
            )
            b.pack(side="left", padx=(0, 6))
            self._buttons[num] = b

        self.status_label = ctk.CTkLabel(
            row,
            text="",
            font=theme.FONT_SMALL,
            text_color=theme.TEXT_MUTED,
            anchor="w",
        )
        self.status_label.pack(side="left", fill="x", expand=True, padx=(8, 0))

    def set_step(self, step: int) -> None:
        self._current = step
        for num, button in self._buttons.items():
            if num == step:
                button.configure(
                    fg_color=theme.ACCENT,
                    text_color="white",
                    hover_color=theme.ACCENT_HOVER,
                    border_color=theme.ACCENT,
                )
            else:
                button.configure(
                    fg_color="transparent",
                    text_color=theme.TEXT_SECONDARY,
                    hover_color=theme.GLASS_BG_HOVER,
                    border_color=theme.GLASS_BORDER,
                )

    def set_status(self, text: str) -> None:
        self.status_label.configure(text=text)
