from __future__ import annotations

from typing import Callable

import customtkinter as ctk
import pandas as pd
from CTkTable import CTkTable

from app import theme
from app.components import btn, glass_card
from app.dialogs import ask_confirm, ask_text, show_info, show_warning
from src.preview_utils import filter_frame_by_invoice, invoice_numbers_from_frame


class EditableDataGrid(ctk.CTkFrame):
    """Tabla editable con filtro por factura y acciones de flujo."""

    def __init__(
        self,
        parent: ctk.CTk,
        on_change: Callable[[pd.DataFrame], None] | None = None,
        on_validate: Callable[[], None] | None = None,
        on_export: Callable[[], None] | None = None,
        on_excel_sim: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, fg_color="transparent")
        self.on_change = on_change
        self.on_validate = on_validate
        self.on_export = on_export
        self.on_excel_sim = on_excel_sim
        self._full_df = pd.DataFrame()
        self._df = pd.DataFrame()
        self._view_invoice: str | None = None
        self._sage_template_columns: list[str] = []
        self._selected_row: int | None = None
        self._selected_col: int | None = None
        self._table: CTkTable | None = None
        self._dirty = False

        self._build_toolbar()
        self._build_summary_bar()
        self._table_container = glass_card(self, radius=theme.BENTO_RADIUS_SM)
        self._table_container.pack(fill="both", expand=True, pady=(8, 0))
        self._build_bottom_actions()

    def _build_toolbar(self) -> None:
        bar = glass_card(self, radius=theme.BENTO_RADIUS_SM)
        bar.pack(fill="x")

        left = ctk.CTkFrame(bar, fg_color="transparent")
        left.pack(side="left", padx=12, pady=10)
        ctk.CTkLabel(left, text="Editor de datos", font=("Segoe UI", 14, "bold")).pack(anchor="w")

        inv_row = ctk.CTkFrame(left, fg_color="transparent")
        inv_row.pack(anchor="w", pady=(4, 0))
        ctk.CTkLabel(inv_row, text="Factura:", font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY).pack(
            side="left", padx=(0, 6)
        )
        self.invoice_var = ctk.StringVar(value="Todas")
        self.invoice_menu = ctk.CTkOptionMenu(
            inv_row,
            variable=self.invoice_var,
            values=["Todas"],
            width=220,
            command=self._on_invoice_selected,
        )
        self.invoice_menu.pack(side="left")

        self._dirty_label = ctk.CTkLabel(
            left,
            text="Guardado",
            font=("Segoe UI", 10, "bold"),
            text_color=theme.SUCCESS,
        )
        self._dirty_label.pack(anchor="w", pady=(6, 0))

        self._selection_label = ctk.CTkLabel(
            left,
            text="Clic para seleccionar · doble clic para editar",
            font=theme.FONT_SMALL,
            text_color=theme.TEXT_MUTED,
        )
        self._selection_label.pack(anchor="w", pady=(2, 0))

        actions = ctk.CTkFrame(bar, fg_color="transparent")
        actions.pack(side="right", padx=12, pady=10)

        buttons = [
            ("Editar", self.edit_selected_cell),
            ("+ Fila", self.add_row),
            ("- Fila", self.delete_row),
            ("Plantilla Sage", self.apply_sage_columns),
        ]
        for text, command in buttons:
            btn(
                actions,
                text=text,
                variant="secondary",
                width=100,
                height=theme.BTN_HEIGHT_SM,
                font=theme.BTN_FONT_SM,
                command=command,
            ).pack(side="left", padx=3)

    def _build_summary_bar(self) -> None:
        self.summary_bar = glass_card(self, radius=theme.BENTO_RADIUS_SM)
        self.summary_bar.pack(fill="x", pady=(8, 0))
        self.summary_label = ctk.CTkLabel(
            self.summary_bar,
            text="Sin datos cargados",
            font=theme.FONT_SMALL,
            text_color=theme.TEXT_SECONDARY,
            anchor="w",
            justify="left",
        )
        self.summary_label.pack(fill="x", padx=16, pady=10)

    def _build_bottom_actions(self) -> None:
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", pady=(8, 0))
        if self.on_validate:
            btn(row, text="Validar de nuevo", variant="secondary", command=self.on_validate).pack(
                side="left", padx=(0, 8)
            )
        if self.on_export:
            btn(row, text="Generar archivo Sage", variant="secondary", command=self.on_export).pack(
                side="left", padx=(0, 8)
            )
        if self.on_excel_sim:
            btn(row, text="Carga en Sage", variant="primary", command=self.on_excel_sim).pack(side="left")

    @property
    def dataframe(self) -> pd.DataFrame:
        return self._full_df.copy()

    @property
    def selected_invoice(self) -> str | None:
        val = self.invoice_var.get()
        return None if val == "Todas" else val

    def load_dataframe(self, frame: pd.DataFrame, *, mark_clean: bool = True) -> None:
        self._full_df = frame.copy() if frame is not None else pd.DataFrame()
        self._view_invoice = None
        self._rebuild_invoice_menu()
        self._apply_view()
        if mark_clean:
            self._set_dirty(False)

    def _rebuild_invoice_menu(self) -> None:
        invoices = invoice_numbers_from_frame(self._full_df)
        values = ["Todas"] + invoices if invoices else ["Todas"]
        self.invoice_menu.configure(values=values)
        if self._view_invoice and self._view_invoice in invoices:
            self.invoice_var.set(self._view_invoice)
        else:
            self.invoice_var.set("Todas")
            self._view_invoice = None

    def _on_invoice_selected(self, choice: str) -> None:
        self._sync_view_to_full()
        self._view_invoice = None if choice == "Todas" else choice
        self._apply_view()

    def _apply_view(self) -> None:
        if self._view_invoice:
            self._df = filter_frame_by_invoice(self._full_df, self._view_invoice).reset_index(drop=True)
        else:
            self._df = self._full_df.copy()
        self._refresh_table()
        self._update_summary()
        self._notify_change()

    def _sync_view_to_full(self) -> None:
        if self._df.empty:
            return
        if not self._view_invoice or "Invoice Number" not in self._full_df.columns:
            self._full_df = self._df.copy()
            return
        inv = self._view_invoice
        rest = self._full_df[self._full_df["Invoice Number"].astype(str) != str(inv)]
        self._full_df = pd.concat([rest, self._df], ignore_index=True)

    def _update_summary(self) -> None:
        if self._df.empty:
            self.summary_label.configure(text="Sin datos cargados")
            return
        lines = len(self._df)
        inv = self._view_invoice or "Todas"
        subtotal = self._df["Line Amount"].astype(float).sum() if "Line Amount" in self._df else 0
        tax = self._df["Tax Amount"].astype(float).sum() if "Tax Amount" in self._df else 0
        total = float(self._df.iloc[0]["Invoice Total"]) if "Invoice Total" in self._df.columns and lines else 0
        self.summary_label.configure(
            text=f"Factura: {inv}  |  Lineas: {lines}  |  Subtotal lineas: ${subtotal:.2f}  |  ITBMS: ${tax:.2f}  |  Total factura: ${total:.2f}"
        )

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        if dirty:
            self._dirty_label.configure(text="Cambios sin guardar", text_color=theme.WARNING)
        else:
            self._dirty_label.configure(text="Guardado", text_color=theme.SUCCESS)

    def mark_clean(self) -> None:
        self._set_dirty(False)

    def set_sage_columns(self, columns: list[str]) -> None:
        self._sage_template_columns = columns

    def apply_sage_columns(self) -> None:
        if not self._sage_template_columns:
            show_info(self.winfo_toplevel(), "Plantilla Sage", "No hay plantilla configurada.")
            return
        for col in self._sage_template_columns:
            if col not in self._full_df.columns:
                self._full_df[col] = ""
        ordered = self._sage_template_columns + [c for c in self._full_df.columns if c not in self._sage_template_columns]
        self._full_df = self._full_df[ordered]
        self._apply_view()
        self._set_dirty(True)
        show_info(self.winfo_toplevel(), "Plantilla Sage", "Columnas Sage aplicadas.")

    def _df_to_table_values(self) -> list[list[str]]:
        if self._df.empty:
            return [["Sin datos"]]
        columns = [str(c) for c in self._df.columns]
        rows: list[list[str]] = [columns]
        for _, row in self._df.iterrows():
            rows.append(["" if pd.isna(row[col]) else str(row[col]) for col in self._df.columns])
        return rows

    def _refresh_table(self) -> None:
        if self._table is not None:
            self._table.destroy()
        values = self._df_to_table_values()
        rows = len(values)
        cols = len(values[0]) if values else 1
        self._table = CTkTable(
            master=self._table_container,
            values=values,
            header_color=theme.TABLE_HEADER,
            colors=[theme.TABLE_ROW_EVEN, theme.TABLE_ROW_ODD],
            hover=False,
            corner_radius=10,
            border_width=0,
            text_color=theme.TEXT_PRIMARY,
            font=theme.FONT_SMALL,
            command=self._on_cell_click,
        )
        self._table.pack(fill="both", expand=True, padx=8, pady=8)
        self._row_count = rows
        self._col_count = cols
        self._apply_selection_visual()

    def _reset_all_cells(self) -> None:
        if self._table is None:
            return
        for row in range(self._row_count):
            for col in range(self._col_count):
                if row == 0:
                    fg, text = theme.TABLE_HEADER, theme.TEXT_PRIMARY
                else:
                    fg = theme.TABLE_ROW_EVEN if row % 2 == 0 else theme.TABLE_ROW_ODD
                    text = theme.TEXT_PRIMARY
                try:
                    self._table.edit(row, col, fg_color=fg, text_color=text, border_width=0)
                except Exception:
                    pass

    def _apply_selection_visual(self) -> None:
        if self._table is None:
            return
        self._reset_all_cells()
        if self._selected_row is None or self._selected_col is None:
            return
        row, col = self._selected_row, self._selected_col
        if 0 <= row < self._row_count and 0 <= col < self._col_count:
            try:
                self._table.edit(
                    row,
                    col,
                    fg_color=theme.TABLE_SELECTED_CELL,
                    text_color=("white", "white"),
                    border_width=2,
                    border_color=theme.CYAN,
                )
            except Exception:
                pass

    def _on_cell_click(self, cell: dict) -> None:
        row, column = cell["row"], cell["column"]
        if getattr(self, "_last_click", None) == (row, column):
            self._edit_cell(row, column)
            self.after(300, lambda: setattr(self, "_last_click", None))
            return
        self._selected_row, self._selected_col = row, column
        self._apply_selection_visual()
        self._last_click = (row, column)
        self.after(300, lambda: setattr(self, "_last_click", None))

    def _edit_cell(self, row: int, column: int) -> None:
        if row == 0:
            show_warning(self.winfo_toplevel(), "Encabezado", "Usa Renombrar columna para el encabezado.")
            return
        data_row = row - 1
        col_name = self._df.columns[column]
        current = self._df.at[data_row, col_name]
        value = ask_text(
            self.winfo_toplevel(),
            "Editar celda",
            f"Columna: {col_name}\nFila: {data_row + 1}",
            "" if pd.isna(current) else str(current),
        )
        if value is None:
            return
        self._df.at[data_row, col_name] = value
        self._sync_view_to_full()
        self._apply_view()
        self._set_dirty(True)

    def edit_selected_cell(self) -> None:
        if self._selected_row is None or self._selected_col is None:
            show_warning(self.winfo_toplevel(), "Seleccion", "Haz clic en una celda.")
            return
        self._edit_cell(self._selected_row, self._selected_col)

    def add_row(self) -> None:
        if self._df.empty:
            self._df = pd.DataFrame([{}])
        else:
            blank = {col: "" for col in self._df.columns}
            if self._view_invoice and "Invoice Number" in blank:
                blank["Invoice Number"] = self._view_invoice
            self._df = pd.concat([self._df, pd.DataFrame([blank])], ignore_index=True)
        self._sync_view_to_full()
        self._apply_view()
        self._set_dirty(True)

    def delete_row(self) -> None:
        if self._selected_row is None or self._selected_row == 0:
            show_warning(self.winfo_toplevel(), "Seleccion", "Selecciona una fila de datos.")
            return
        data_row = self._selected_row - 1
        if not ask_confirm(self.winfo_toplevel(), "Eliminar fila", f"Eliminar fila {data_row + 1}?"):
            return
        self._df = self._df.drop(data_row).reset_index(drop=True)
        self._sync_view_to_full()
        self._selected_row = None
        self._selected_col = None
        self._apply_view()
        self._set_dirty(True)

    def _notify_change(self) -> None:
        if self.on_change:
            self.on_change(self._full_df.copy())
