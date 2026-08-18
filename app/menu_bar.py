from __future__ import annotations

import tkinter as tk
from typing import Any, Callable

import customtkinter as ctk

from app import theme


class AppMenuBar(ctk.CTkFrame):
    """Barra de menu estilo escritorio: Importar, Exportar, Editar, Ver, Opciones."""

    def __init__(self, parent: ctk.CTk, commands: dict[str, Callable[..., Any]]) -> None:
        super().__init__(parent, fg_color=theme.GLASS_BG, corner_radius=0, height=36)
        self.pack_propagate(False)
        self._cmds = commands
        self._menus: dict[str, tk.Menu | ctk.CTkButton] = {}

        self.configure(border_width=1, border_color=theme.GLASS_BORDER)
        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=8)

        items = [
            ("importar", "Importar", self._build_import_menu),
            ("exportar", "Exportar", self._build_export_menu),
            ("editar", "Editar", self._build_edit_menu),
            ("ver", "Ver", self._build_view_menu),
            ("opciones", "Opciones", self._build_options_menu),
        ]

        for key, label, builder in items:
            builder(key)
            btn = ctk.CTkButton(
                inner,
                text=label,
                width=88,
                height=28,
                corner_radius=6,
                fg_color="transparent",
                hover_color=theme.GLASS_BG_HOVER,
                text_color=theme.TEXT_PRIMARY,
                font=("Segoe UI", 12),
                anchor="center",
                command=lambda k=key: self._show_menu(k),
            )
            btn.pack(side="left", padx=2, pady=4)
            self._menus[f"{key}_btn"] = btn

    def _menu_style(self, menu: tk.Menu) -> None:
        menu.configure(
            tearoff=0,
            bg=theme.GLASS_BG,
            fg=theme.TEXT_PRIMARY,
            activebackground=theme.ACCENT,
            activeforeground="white",
            borderwidth=1,
            relief="flat",
            font=("Segoe UI", 11),
        )

    def _add_menu(self, key: str, label: str, entries: list[tuple[str, str, str | None]]) -> None:
        menu = tk.Menu(self.winfo_toplevel())
        self._menu_style(menu)
        for text, cmd_key, accel in entries:
            if cmd_key is None:
                menu.add_separator()
                continue
            cmd = self._cmds.get(cmd_key)
            if cmd:
                menu.add_command(label=text, accelerator=accel or "", command=cmd)
        self._menus[key] = menu

    def _build_import_menu(self, key: str) -> None:
        self._add_menu(
            key,
            "Importar",
            [
                ("Desde PsKloud (BD)...", "import_pskloud", "Ctrl+1"),
                ("Desde PDF...", "import_pdf", "Ctrl+Shift+P"),
                ("Desde CSV...", "import_csv", "Ctrl+Shift+C"),
            ],
        )

    def _build_export_menu(self, key: str) -> None:
        self._add_menu(
            key,
            "Exportar",
            [
                ("CSV para Sage 50...", "export_sage", "Ctrl+E"),
                ("Rechazados (errores)...", "export_rejected", ""),
                (None, None, None),
                ("Abrir carpeta de salida", "open_output", ""),
            ],
        )

    def _build_edit_menu(self, key: str) -> None:
        self._add_menu(
            key,
            "Editar",
            [
                ("Validar de nuevo", "revalidate", "F5"),
                ("Ir al editor", "go_editor", ""),
            ],
        )

    def _build_view_menu(self, key: str) -> None:
        self._add_menu(
            key,
            "Ver",
            [
                ("Paso 1 — Importar", "view_step1", "Ctrl+1"),
                ("Paso 2 — Revisar", "view_step2", "Ctrl+2"),
                ("Paso 3 — Carga Sage", "view_step3", "Ctrl+3"),
                (None, None, None),
                ("Log de actividad", "view_activity", "Ctrl+L"),
            ],
        )

    def _build_options_menu(self, key: str) -> None:
        self._add_menu(
            key,
            "Opciones",
            [
                ("Conexion a base de datos...", "db_connections", ""),
                ("Actualizar Auto-Hub...", "update_app", ""),
                (None, None, None),
                ("Restablecer BD local...", "reset_db", ""),
                ("Abrir plantilla Excel Sage", "open_excel_template", ""),
            ],
        )

    def _show_menu(self, key: str) -> None:
        menu = self._menus.get(key)
        if not isinstance(menu, tk.Menu):
            return
        btn = self._menus.get(f"{key}_btn")
        if not isinstance(btn, ctk.CTkButton):
            return
        x = btn.winfo_rootx()
        y = btn.winfo_rooty() + btn.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def bind_shortcuts(self, root: ctk.CTk) -> None:
        bindings = {
            "<Control-1>": "import_pskloud",
            "<Control-2>": lambda: self._cmds.get("view_step2", lambda: None)(),
            "<Control-3>": lambda: self._cmds.get("view_step3", lambda: None)(),
            "<Control-e>": "export_sage",
            "<Control-E>": "export_sage",
            "<Control-l>": "view_activity",
            "<Control-L>": "view_activity",
            "<F5>": "revalidate",
        }
        for seq, target in bindings.items():
            if isinstance(target, str):
                cmd = self._cmds.get(target)
                if cmd:
                    root.bind_all(seq, lambda _e, c=cmd: c())
            else:
                root.bind_all(seq, lambda _e, c=target: c())
