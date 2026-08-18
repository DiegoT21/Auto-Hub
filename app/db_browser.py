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
    ) -> None:
        super().__init__(parent, fg_color="transparent")
        self.config = config
        self.root = root
        self.on_extract_selected = on_extract_selected
        self.on_back = on_back
        self._rows: list[dict] = []
        self._checks: dict = {}
        self._loading = False
        self._refresh_token = 0

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ctk.CTkLabel(
            header,
            text="Facturas en PsKloud",
            font=theme.FONT_HEADING,
            text_color=theme.TEXT_PRIMARY,
        ).pack(side="left")
        if on_back:
            btn(header, text="Volver", variant="ghost", width=90, command=on_back).pack(side="right")

        filters = card(self)
        filters.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        f_inner = ctk.CTkFrame(filters, fg_color="transparent")
        f_inner.pack(fill="x", padx=16, pady=16)
        f_inner.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(f_inner, text="Desde:", font=theme.FONT_SMALL).grid(
            row=0, column=0, padx=(0, 6), pady=4, sticky="w"
        )
        self.date_entry = glass_input(f_inner, width=120, placeholder_text="2026-01-01")
        self.date_entry.grid(row=0, column=1, padx=(0, 12), pady=4, sticky="w")

        ctk.CTkLabel(f_inner, text="Cliente / factura:", font=theme.FONT_SMALL).grid(
            row=0, column=2, padx=(0, 6), pady=4, sticky="w"
        )
        self.customer_entry = glass_input(f_inner, placeholder_text="nombre o numero...")
        self.customer_entry.grid(row=0, column=3, padx=(0, 0), pady=4, sticky="ew")

        btn_row = ctk.CTkFrame(f_inner, fg_color="transparent")
        btn_row.grid(row=1, column=0, columnspan=4, sticky="w", pady=(10, 0))
        self.search_btn = btn(btn_row, text="Buscar", variant="secondary", command=self.refresh)
        self.search_btn.pack(side="left", padx=(0, 8))
        btn(btn_row, text="Seleccionar todo", variant="ghost", command=self.select_all).pack(side="left")

        self.list_frame = ctk.CTkScrollableFrame(self, fg_color="transparent", corner_radius=12)
        self.list_frame.grid(row=2, column=0, sticky="nsew")

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        self.count_label = ctk.CTkLabel(
            actions,
            text="Pulsa Buscar para cargar facturas (max 150 mas recientes).",
            font=theme.FONT_SMALL,
            text_color=theme.TEXT_SECONDARY,
        )
        self.count_label.pack(side="left")
        btn(
            actions,
            text="Importar seleccionadas →",
            variant="primary",
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
            item.pack(fill="x", pady=4, padx=4)
            inner = ctk.CTkFrame(item, fg_color="transparent")
            inner.pack(fill="x", padx=12, pady=10)

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
