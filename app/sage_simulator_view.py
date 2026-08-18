from __future__ import annotations

import customtkinter as ctk

from app import theme


class SageSimulatorView(ctk.CTkFrame):
    """Réplica visual de Sales/Invoicing de Sage 50 con animación de llenado."""

    def __init__(self, parent: ctk.CTk, on_log: callable | None = None) -> None:
        super().__init__(parent, fg_color=("gray88", "gray14"), corner_radius=0)
        self.on_log = on_log
        self._entries: dict[str, ctk.CTkEntry] = {}
        self._line_entries: list[dict[str, ctk.CTkEntry]] = []
        self._active_widget: ctk.CTkEntry | None = None
        self._build_ui()

    def _log(self, msg: str) -> None:
        if self.on_log:
            self.on_log(msg)

    def _build_ui(self) -> None:
        outer = ctk.CTkScrollableFrame(self, fg_color=("gray92", "gray16"), corner_radius=12)
        outer.pack(fill="both", expand=True, padx=12, pady=12)

        title_bar = ctk.CTkFrame(outer, fg_color=("#2B579A", "#1E3A5F"), corner_radius=6, height=36)
        title_bar.pack(fill="x", pady=(0, 10))
        title_bar.pack_propagate(False)
        ctk.CTkLabel(
            title_bar,
            text="Sales/Invoicing  —  Sage 50",
            font=("Segoe UI", 13, "bold"),
            text_color="white",
        ).pack(side="left", padx=12, pady=6)

        form = ctk.CTkFrame(outer, fg_color=("white", "gray20"), corner_radius=8)
        form.pack(fill="x", pady=(0, 10))
        form_inner = ctk.CTkFrame(form, fg_color="transparent")
        form_inner.pack(fill="x", padx=16, pady=14)
        form_inner.grid_columnconfigure(1, weight=2)
        form_inner.grid_columnconfigure(3, weight=1)

        self._add_field(form_inner, 0, 0, "Customer ID", "customer_id", colspan=3)
        self._add_field(form_inner, 1, 0, "Ship to", "ship_to", colspan=3)
        self._add_field(form_inner, 2, 0, "Invoice date", "invoice_date")
        self._add_field(form_inner, 2, 2, "Due date", "due_date")
        self._add_field(form_inner, 3, 0, "Invoice No.", "invoice_no")
        self._add_field(form_inner, 4, 0, "Ship via", "ship_via")
        self._add_field(form_inner, 4, 2, "A/R account", "ar_account")
        self._add_field(form_inner, 5, 0, "Sales rep", "sales_rep", colspan=3)

        grid_frame = ctk.CTkFrame(outer, fg_color=("white", "gray20"), corner_radius=8)
        grid_frame.pack(fill="both", expand=True, pady=(0, 10))

        headers = ["Quantity", "Item", "Description", "G/L Account", "Unit Price", "Tax", "Amount", "Job"]
        widths = [70, 90, 220, 80, 80, 50, 80, 60]
        header_row = ctk.CTkFrame(grid_frame, fg_color=("#5B6770", "#374151"), corner_radius=0)
        header_row.pack(fill="x", padx=1, pady=(1, 0))
        for i, (h, w) in enumerate(zip(headers, widths)):
            ctk.CTkLabel(
                header_row,
                text=h,
                width=w,
                font=("Segoe UI", 10, "bold"),
                text_color="white",
            ).pack(side="left", padx=1, pady=6)

        self.lines_container = ctk.CTkFrame(grid_frame, fg_color="transparent")
        self.lines_container.pack(fill="both", expand=True, padx=1, pady=1)

        for _ in range(8):
            self._add_line_row()

        footer = ctk.CTkFrame(outer, fg_color=("white", "gray20"), corner_radius=8)
        footer.pack(fill="x")
        footer.grid_columnconfigure(0, weight=1)
        footer_inner = ctk.CTkFrame(footer, fg_color="transparent")
        footer_inner.pack(fill="x", padx=16, pady=14)
        footer_inner.grid_columnconfigure(0, weight=1)

        left = ctk.CTkFrame(footer_inner, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w")
        for label in ("Balance:", "Credit limit:", "Credit status:"):
            ctk.CTkLabel(left, text=label, font=theme.FONT_SMALL, text_color=("gray40", "gray60")).pack(anchor="w")

        right = ctk.CTkFrame(footer_inner, fg_color="transparent")
        right.grid(row=0, column=1, sticky="e")
        self._add_field(right, 0, 0, "Sales tax (ITBMS)", "sales_tax", inline=True)
        self._add_field(right, 1, 0, "Invoice total", "invoice_total", inline=True)
        self._add_field(right, 2, 0, "Net due", "net_due", inline=True)

        self.status_banner = ctk.CTkLabel(
            outer,
            text="Esperando datos…",
            font=theme.FONT_SMALL,
            text_color=theme.ACCENT,
        )
        self.status_banner.pack(anchor="w", pady=(8, 0))

    def _add_field(
        self,
        parent,
        row: int,
        col: int,
        label: str,
        key: str,
        colspan: int = 1,
        inline: bool = False,
    ) -> None:
        if inline:
            row_frame = ctk.CTkFrame(parent, fg_color="transparent")
            row_frame.pack(anchor="e", pady=2)
            ctk.CTkLabel(row_frame, text=f"{label}:", width=120, anchor="e", font=theme.FONT_SMALL).pack(
                side="left", padx=(0, 8)
            )
            entry = ctk.CTkEntry(row_frame, width=100, height=28, corner_radius=4)
            entry.pack(side="left")
            self._entries[key] = entry
            return

        ctk.CTkLabel(parent, text=f"{label}:", font=theme.FONT_SMALL, anchor="w").grid(
            row=row, column=col, sticky="w", padx=(0, 8), pady=4
        )
        entry = ctk.CTkEntry(parent, height=28, corner_radius=4, border_color=("gray70", "gray40"))
        entry.grid(row=row, column=col + 1, columnspan=colspan, sticky="ew", padx=(0, 16), pady=4)
        self._entries[key] = entry

    def _add_line_row(self) -> None:
        keys = ["quantity", "item", "description", "gl_account", "unit_price", "tax", "amount", "job"]
        widths = [70, 90, 220, 80, 80, 50, 80, 60]
        row_frame = ctk.CTkFrame(self.lines_container, fg_color="transparent")
        row_frame.pack(fill="x", pady=1)
        row_entries: dict[str, ctk.CTkEntry] = {}
        for key, width in zip(keys, widths):
            entry = ctk.CTkEntry(row_frame, width=width, height=26, corner_radius=3, font=theme.FONT_SMALL)
            entry.pack(side="left", padx=1)
            row_entries[key] = entry
        self._line_entries.append(row_entries)

    def clear(self) -> None:
        for entry in self._entries.values():
            entry.delete(0, "end")
            entry.configure(fg_color=("white", "gray25"))
        for row in self._line_entries:
            for entry in row.values():
                entry.delete(0, "end")
                entry.configure(fg_color=("white", "gray25"))
        if self._active_widget:
            self._active_widget.configure(fg_color=("white", "gray25"))
        self._active_widget = None
        self.status_banner.configure(text="Esperando datos…")

    def _highlight(self, widget: ctk.CTkEntry) -> None:
        if self._active_widget:
            self._active_widget.configure(fg_color=("white", "gray25"))
        self._active_widget = widget
        widget.configure(fg_color=("#FFF9C4", "#854D0E"))

    def animate_invoice(self, invoice: dict, on_done: callable | None = None) -> None:
        self.clear()
        steps: list[tuple[ctk.CTkEntry, str, str]] = []

        header_map = {
            "customer_id": invoice.get("customer_id", ""),
            "ship_to": invoice.get("customer_id", ""),
            "invoice_date": invoice.get("invoice_date", ""),
            "due_date": invoice.get("due_date", invoice.get("invoice_date", "")),
            "invoice_no": invoice.get("invoice_no", ""),
            "ship_via": invoice.get("ship_via", ""),
            "ar_account": invoice.get("ar_account", ""),
            "sales_rep": invoice.get("sales_rep", ""),
            "sales_tax": str(invoice.get("sales_tax", "")),
            "invoice_total": str(invoice.get("invoice_total", "")),
            "net_due": str(invoice.get("net_due", "")),
        }
        for key, value in header_map.items():
            if key in self._entries and value:
                steps.append((self._entries[key], str(value), key))

        for i, line in enumerate(invoice.get("lines", [])):
            if i >= len(self._line_entries):
                break
            row = self._line_entries[i]
            for field in ("quantity", "item", "description", "gl_account", "unit_price", "tax", "amount", "job"):
                val = line.get(field, "")
                if val != "" and val is not None:
                    steps.append((row[field], str(val), f"line{i+1}.{field}"))

        self._run_steps(steps, 0, on_done)

    def _run_steps(self, steps: list, index: int, on_done: callable | None) -> None:
        if index >= len(steps):
            self.status_banner.configure(text="Carga completada")
            if on_done:
                on_done()
            return

        widget, value, label = steps[index]
        self._highlight(widget)
        self.status_banner.configure(text=f"Escribiendo: {label}")
        self._log(f"[UI] {label} ← {value[:50]}")
        self._type_into(widget, value, 0, lambda: self.after(120, lambda: self._run_steps(steps, index + 1, on_done)))

    def _type_into(self, widget: ctk.CTkEntry, text: str, pos: int, on_complete: callable) -> None:
        widget.delete(0, "end")
        if pos >= len(text):
            on_complete()
            return
        widget.insert("end", text[pos])
        self.after(25, lambda: self._type_into(widget, text, pos + 1, on_complete))
