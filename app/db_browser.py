from __future__ import annotations

import threading
from datetime import date, datetime
from typing import Any, Callable

import customtkinter as ctk

from app import theme
from app.components import btn, card, glass_input
from src.extract import preview_invoice_headers

SUCURSAL_ORDER = {
    "ADI SUPPLY": 0,
    "CORONADO": 1,
    "RIO ABAJO": 2,
}
SUCURSAL_COLOR = {
    "ADI SUPPLY": theme.SUCCESS,
    "CORONADO": theme.CYAN,
    "RIO ABAJO": theme.ACCENT,
}


def _sucursal_name(row: dict[str, Any]) -> str:
    return str(row.get("sucursal") or "").strip() or "SIN SUCURSAL"


def _short_doc(row: dict[str, Any]) -> str:
    fid = str(row.get("factura_id") or "")
    if ":" in fid:
        return fid.rsplit(":", 1)[-1]
    num = str(row.get("numero_factura") or "")
    return num if len(num) <= 16 else "…" + num[-10:]


def _format_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    text = str(value or "")[:10]
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return f"{text[8:10]}/{text[5:7]}/{text[:4]}"
    return text or "—"


def _sort_invoices(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda r: str(r.get("cliente_nombre") or "").upper())
    ordered.sort(key=lambda r: str(r.get("fecha_emision") or ""), reverse=True)
    ordered.sort(key=lambda r: (SUCURSAL_ORDER.get(_sucursal_name(r), 50), _sucursal_name(r)))
    return ordered


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
        self._page = 0
        self._page_size = 10
        self._has_next = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        filters = ctk.CTkFrame(self, fg_color="transparent")
        filters.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        filters.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(filters, text="Desde", font=theme.FONT_SMALL).grid(
            row=0, column=0, padx=(0, 4), sticky="w"
        )
        self.date_entry = glass_input(filters, width=100, placeholder_text="vacio = todas")
        self.date_entry.grid(row=0, column=1, padx=(0, 8), sticky="w")
        self.date_entry.insert("0", datetime.now().strftime("%Y-%m-%d"))

        ctk.CTkLabel(filters, text="Cliente / factura", font=theme.FONT_SMALL).grid(
            row=0, column=2, padx=(0, 4), sticky="w"
        )
        self.customer_entry = glass_input(filters, placeholder_text="nombre o numero...")
        self.customer_entry.grid(row=0, column=3, padx=(0, 8), sticky="ew")

        self.search_btn = btn(filters, text="Buscar", variant="primary", width=80, command=self.refresh)
        self.search_btn.grid(row=0, column=4, padx=(0, 6))
        btn(filters, text="Todo", variant="ghost", width=60, command=self.select_all).grid(row=0, column=5)

        self._header = ctk.CTkFrame(self, fg_color=theme.GLASS_INPUT, corner_radius=8, height=28)
        self._header.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        self._header.grid_propagate(False)
        self._build_column_header(self._header)

        self.list_frame = ctk.CTkScrollableFrame(self, fg_color="transparent", corner_radius=8)
        self.list_frame.grid(row=2, column=0, sticky="nsew")

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.count_label = ctk.CTkLabel(
            actions,
            text="Pulsa Buscar. Se muestran 10 por pagina.",
            font=theme.FONT_SMALL,
            text_color=theme.TEXT_SECONDARY,
        )
        self.count_label.pack(side="left")
        pager = ctk.CTkFrame(actions, fg_color="transparent")
        pager.pack(side="left", padx=(16, 0))
        self.prev_btn = btn(pager, text="← Anterior", variant="ghost", width=90, command=self._prev_page)
        self.prev_btn.pack(side="left", padx=(0, 6))
        self.page_label = ctk.CTkLabel(
            pager,
            text="Pagina 1",
            font=theme.FONT_SMALL,
            text_color=theme.TEXT_SECONDARY,
            width=80,
        )
        self.page_label.pack(side="left")
        self.next_btn = btn(pager, text="Siguiente →", variant="ghost", width=100, command=self._next_page)
        self.next_btn.pack(side="left", padx=(6, 0))
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
            self.prev_btn.configure(state="disabled" if loading or self._page <= 0 else "normal")
            self.next_btn.configure(state="disabled" if loading or not self._has_next else "normal")
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
        page = self._page
        page_size = self._page_size
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
                    limit=page_size + 1,
                    offset=page * page_size,
                )
                error = ""
            except Exception as exc:
                rows = []
                error = str(exc)
            self.after(0, lambda: self._apply_refresh_result(token, rows, error))

        threading.Thread(target=worker, daemon=True).start()

    def refresh(self) -> None:
        self._page = 0
        self.refresh_async()

    def _prev_page(self) -> None:
        if self._loading or self._page <= 0:
            return
        self._page -= 1
        self.refresh_async()

    def _next_page(self) -> None:
        if self._loading or not self._has_next:
            return
        self._page += 1
        self.refresh_async()

    def _apply_refresh_result(self, token: int, rows: list[dict], error: str) -> None:
        if token != self._refresh_token:
            return
        if error:
            self._rows = []
            self._has_next = False
            self.count_label.configure(text=f"Error: {error}", text_color=theme.DANGER)
            self.page_label.configure(text=f"Pagina {self._page + 1}")
            self._set_loading(False)
            for w in self.list_frame.winfo_children():
                w.destroy()
            self._checks.clear()
            return

        self._has_next = len(rows) > self._page_size
        rows = rows[: self._page_size]
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
            self.page_label.configure(text=f"Pagina {self._page + 1}")
            self._set_loading(False)
            return

        ordered = _sort_invoices(rows)
        current = None
        for row in ordered:
            suc = _sucursal_name(row)
            if suc != current:
                current = suc
                count = sum(1 for item in ordered if _sucursal_name(item) == suc)
                self._add_group_header(suc, count)
            self._add_invoice_row(row)

        shown = len(rows)
        start = self._page * self._page_size + 1
        end = start + shown - 1
        extra = " · hay mas" if self._has_next else ""
        self.count_label.configure(
            text=f"{shown} en esta pagina ({start}-{end}){extra}",
            text_color=theme.TEXT_SECONDARY,
        )
        self.page_label.configure(text=f"Pagina {self._page + 1}")
        self._set_loading(False)

    def _layout_columns(self, parent: ctk.CTkFrame) -> None:
        parent.grid_columnconfigure(0, minsize=28, weight=0)
        parent.grid_columnconfigure(1, minsize=88, weight=0)
        parent.grid_columnconfigure(2, minsize=0, weight=1)
        parent.grid_columnconfigure(3, minsize=84, weight=0)
        parent.grid_columnconfigure(4, minsize=48, weight=0)
        parent.grid_columnconfigure(5, minsize=92, weight=0)

    def _build_column_header(self, parent: ctk.CTkFrame) -> None:
        self._layout_columns(parent)
        specs = (
            (0, ""),
            (1, "Fecha"),
            (2, "Cliente"),
            (3, "Total"),
            (4, "Lin."),
            (5, "Doc."),
        )
        for col, text in specs:
            sticky = "e" if col in (3, 4) else "w"
            ctk.CTkLabel(
                parent,
                text=text,
                font=theme.FONT_SMALL,
                text_color=theme.TEXT_MUTED,
                anchor=sticky,
            ).grid(row=0, column=col, sticky="ew", padx=6, pady=4)

    def _add_group_header(self, sucursal: str, count: int) -> None:
        bar = ctk.CTkFrame(self.list_frame, fg_color=theme.GLASS_BG_HOVER, corner_radius=6)
        bar.pack(fill="x", pady=(8, 2), padx=0)
        color = SUCURSAL_COLOR.get(sucursal, theme.TEXT_SECONDARY)
        ctk.CTkLabel(
            bar,
            text=f"{sucursal}  ·  {count}",
            font=theme.FONT_SMALL,
            text_color=color,
            anchor="w",
        ).pack(fill="x", padx=10, pady=4)

    def _add_invoice_row(self, row: dict[str, Any]) -> None:
        item = card(self.list_frame)
        item.pack(fill="x", pady=1, padx=0)
        inner = ctk.CTkFrame(item, fg_color="transparent")
        inner.pack(fill="x", padx=6, pady=3)
        self._layout_columns(inner)

        var = ctk.StringVar(value="off")
        chk = ctk.CTkCheckBox(
            inner,
            text="",
            variable=var,
            onvalue="on",
            offvalue="off",
            width=24,
        )
        chk.grid(row=0, column=0, sticky="w")
        self._checks[row["factura_id"]] = chk

        ctk.CTkLabel(
            inner,
            text=_format_date(row.get("fecha_emision")),
            font=theme.FONT_BODY,
            text_color=theme.TEXT_SECONDARY,
            anchor="w",
        ).grid(row=0, column=1, sticky="ew", padx=(0, 6))

        name = str(row.get("cliente_nombre") or "").strip() or "—"
        ctk.CTkLabel(
            inner,
            text=name,
            font=theme.FONT_BODY,
            text_color=theme.TEXT_PRIMARY,
            anchor="w",
        ).grid(row=0, column=2, sticky="ew", padx=(0, 8))

        try:
            total = f"${float(row.get('total_factura') or 0):,.2f}"
        except (TypeError, ValueError):
            total = "$0.00"
        ctk.CTkLabel(
            inner,
            text=total,
            font=theme.FONT_BODY,
            text_color=theme.TEXT_PRIMARY,
            anchor="e",
        ).grid(row=0, column=3, sticky="ew", padx=(0, 6))

        ctk.CTkLabel(
            inner,
            text=str(row.get("line_count") or "—"),
            font=theme.FONT_BODY,
            text_color=theme.TEXT_MUTED,
            anchor="e",
        ).grid(row=0, column=4, sticky="ew", padx=(0, 6))

        ctk.CTkLabel(
            inner,
            text=_short_doc(row),
            font=theme.FONT_SMALL,
            text_color=theme.TEXT_MUTED,
            anchor="w",
        ).grid(row=0, column=5, sticky="ew")

    def select_all(self) -> None:
        for chk in self._checks.values():
            chk.select()

    def _extract(self) -> None:
        selected = [fid for fid, chk in self._checks.items() if chk.get() == 1 or chk.get() == "on"]
        if not selected:
            self.count_label.configure(text="Selecciona al menos una factura.")
            return
        self.on_extract_selected(selected)
