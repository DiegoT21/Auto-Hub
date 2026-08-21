from __future__ import annotations

import threading
from typing import Callable

import customtkinter as ctk

from app import theme
from app.components import btn, card, glass_card, glass_input
from src.extract import extract_invoices_by_ids, preview_invoice_headers


class DbBrowserPanel(ctk.CTkFrame):
    """Explorador de facturas en BD antes de extraer."""

    def __init__(
        self,
        parent: ctk.CTk,
        config: dict,
        root,
        on_extract_selected: Callable[[list], None],
        on_back: Callable[[], None] | None = None,
        get_config: Callable[[], dict] | None = None,
    ) -> None:
        super().__init__(parent, fg_color="transparent")
        self.config = config
        self.get_config = get_config
        self.root = root
        self.on_extract_selected = on_extract_selected
        self.on_back = on_back
        self._rows: list[dict] = []
        self._checks: dict = {}
        self._loading = False
        self._refresh_token = 0

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        filters = ctk.CTkFrame(self, fg_color="transparent")
        filters.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        filters.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(filters, text="Desde", font=theme.FONT_SMALL).grid(
            row=0, column=0, padx=(0, 4), sticky="w"
        )
        self.date_entry = glass_input(filters, width=100, placeholder_text="vacio = todas")
        self.date_entry.grid(row=0, column=1, padx=(0, 8), sticky="w")
        self.date_entry.insert("0", "2024-01-01")

        ctk.CTkLabel(filters, text="Cliente / factura", font=theme.FONT_SMALL).grid(
            row=0, column=2, padx=(0, 4), sticky="w"
        )
        self.customer_entry = glass_input(filters, placeholder_text="nombre o numero...")
        self.customer_entry.grid(row=0, column=3, padx=(0, 8), sticky="ew")

        self.search_btn = btn(filters, text="Buscar", variant="primary", width=80, command=self.refresh)
        self.search_btn.grid(row=0, column=4, padx=(0, 6))
        btn(filters, text="Todo", variant="ghost", width=60, command=self.select_all).grid(row=0, column=5)

        self.list_frame = ctk.CTkScrollableFrame(self, fg_color="transparent", corner_radius=8)
        self.list_frame.grid(row=1, column=0, sticky="nsew")

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self.count_label = ctk.CTkLabel(
            actions,
            text="Pulsa Buscar (max 150).",
            font=theme.FONT_SMALL,
            text_color=theme.TEXT_SECONDARY,
        )
        self.count_label.pack(side="left")
        btn(
            actions,
            text="Importar seleccionadas",
            variant="primary",
            width=170,
            command=self._extract,
        ).pack(side="right")

        if self._is_local_sqlite():
            self.refresh_async()

    def _is_local_sqlite(self) -> bool:
        return self.config.get("database", {}).get("driver", "sqlite") == "sqlite"

    def _set_loading(self, loading: bool, message: str = "") -> None:
        self._loading = loading
        state = "disabled" if loading else "normal"
        try:
            self.search_btn.configure(state=state)
        except Exception:
            pass
        if message:
            self.count_label.configure(text=message, text_color=theme.TEXT_SECONDARY)

    def refresh_async(self) -> None:
        if self._loading:
            return
        self._refresh_token += 1
        token = self._refresh_token
        date_from = self.date_entry.get().strip() or None
        customer = self.customer_entry.get().strip() or None
        if self.get_config:
            try:
                self.config = self.get_config()
            except Exception:
                pass
        config = self.config
        root = self.root

        self._set_loading(True, "Cargando facturas...")

        def worker() -> None:
            try:
                rows = preview_invoice_headers(
                    config,
                    root,
                    date_from=date_from,
                    customer_query=customer,
                )
                error = ""
            except Exception as exc:
                rows = []
                error = str(exc)
            self.after(0, lambda: self._apply_refresh_result(token, rows, error))

        threading.Thread(target=worker, daemon=True).start()

    def refresh(self) -> None:
        self.refresh_async()

    def _apply_refresh_result(self, token: int, rows: list[dict], error: str) -> None:
        if token != self._refresh_token:
            return
        self._set_loading(False)
        if error:
            self._rows = []
            self.count_label.configure(text=f"Error: {error}", text_color=theme.DANGER)
            for w in self.list_frame.winfo_children():
                w.destroy()
            self._checks.clear()
            return

        self._rows = rows
        for w in self.list_frame.winfo_children():
            w.destroy()
        self._checks.clear()

        if not rows:
            ctk.CTkLabel(
                self.list_frame,
                text="No hay facturas con esos filtros.",
                text_color=theme.TEXT_MUTED,
            ).pack(anchor="w", padx=8, pady=8)
            self.count_label.configure(text="0 facturas", text_color=theme.TEXT_SECONDARY)
            return

        limit = int(self.config.get("extraction", {}).get("preview_limit", 150))
        for row in rows:
            item = card(self.list_frame)
            item.pack(fill="x", pady=1, padx=0)
            inner = ctk.CTkFrame(item, fg_color="transparent")
            inner.pack(fill="x", padx=8, pady=4)

            var = ctk.StringVar(value="off")
            chk = ctk.CTkCheckBox(
                inner,
                text="",
                variable=var,
                onvalue="on",
                offvalue="off",
                width=24,
            )
            chk.pack(side="left", padx=(0, 8))
            self._checks[row["factura_id"]] = chk

            text = (
                f"{row['numero_factura']}  |  {row['cliente_nombre']}  |  "
                f"{row['fecha_emision']}  |  {row.get('line_count', '?')} lineas  |  "
                f"${float(row['total_factura']):.2f}"
            )
            ctk.CTkLabel(inner, text=text, font=theme.FONT_BODY, text_color=theme.TEXT_PRIMARY).pack(
                side="left", fill="x", expand=True
            )

        suffix = f" (mostrando max {limit})" if len(rows) >= limit else ""
        self.count_label.configure(
            text=f"{len(rows)} factura(s) encontradas{suffix}",
            text_color=theme.TEXT_SECONDARY,
        )

    def select_all(self) -> None:
        for chk in self._checks.values():
            chk.select()

    def _extract(self) -> None:
        selected = [fid for fid, chk in self._checks.items() if chk.get() == 1 or chk.get() == "on"]
        if not selected:
            self.count_label.configure(text="Selecciona al menos una factura.")
            return
        self.on_extract_selected(selected)
