from __future__ import annotations

from typing import Any, Callable

import customtkinter as ctk
import pandas as pd

from app import theme
from app.components import btn, card, glass_card, stat_chip
from src.preview_utils import grouped_rejection_messages, invoice_summaries_from_frame, summarize_import


class PreviewPanel(ctk.CTkFrame):
    """Previsualizacion unificada antes de cargar al editor."""

    def __init__(
        self,
        parent: ctk.CTk,
        on_load_editor: Callable[[], None],
        on_export_rejected: Callable[[], None],
        on_back: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, fg_color="transparent")
        self.on_load_editor = on_load_editor
        self.on_export_rejected = on_export_rejected
        self.on_back = on_back
        self._summary: dict[str, Any] = {}
        self._pdf_meta: dict[str, Any] = {}

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ctk.CTkLabel(
            header,
            text="Validacion de facturas",
            font=theme.FONT_HEADING,
            text_color=theme.TEXT_PRIMARY,
        ).pack(side="left")
        if on_back:
            btn(header, text="Volver", variant="ghost", width=90, command=on_back).pack(side="right")

        self.stats_row = ctk.CTkFrame(self, fg_color="transparent")
        self.stats_row.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        for i in range(4):
            self.stats_row.grid_columnconfigure(i, weight=1)

        self.tabs = ctk.CTkTabview(
            self,
            corner_radius=theme.BENTO_RADIUS,
            fg_color=theme.GLASS_BG,
            segmented_button_fg_color=theme.GLASS_INPUT,
            segmented_button_selected_color=theme.ACCENT,
            segmented_button_unselected_color=theme.GLASS_BG_HOVER,
        )
        self.tabs.grid(row=2, column=0, sticky="nsew")
        self.tab_resumen = self.tabs.add("Resumen")
        self.tab_valid = self.tabs.add("Validos")
        self.tab_rejected = self.tabs.add("Rechazados")
        self.tab_detail = self.tabs.add("Detalle")

        self.resumen_text = ctk.CTkTextbox(
            self.tab_resumen,
            font=theme.FONT_BODY,
            corner_radius=theme.BENTO_RADIUS_SM,
            fg_color=theme.GLASS_INPUT,
            border_color=theme.GLASS_BORDER,
        )
        self.resumen_text.pack(fill="both", expand=True, padx=8, pady=8)

        self.valid_table_frame = ctk.CTkScrollableFrame(self.tab_valid, fg_color="transparent")
        self.valid_table_frame.pack(fill="both", expand=True, padx=8, pady=8)

        self.rejected_text = ctk.CTkTextbox(
            self.tab_rejected,
            font=theme.FONT_MONO,
            corner_radius=theme.BENTO_RADIUS_SM,
            fg_color=theme.GLASS_INPUT,
            border_color=theme.GLASS_BORDER,
        )
        self.rejected_text.pack(fill="both", expand=True, padx=8, pady=8)

        self.detail_text = ctk.CTkTextbox(
            self.tab_detail,
            font=theme.FONT_MONO,
            corner_radius=theme.BENTO_RADIUS_SM,
            fg_color=theme.GLASS_INPUT,
            border_color=theme.GLASS_BORDER,
        )
        self.detail_text.pack(fill="both", expand=True, padx=8, pady=8)

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        self.load_btn = btn(
            actions,
            text="Continuar → Revisar y editar",
            variant="primary",
            command=self.on_load_editor,
        )
        self.load_btn.pack(side="left", padx=(0, 8))
        self.reject_btn = btn(
            actions,
            text="Exportar rechazados",
            variant="danger",
            command=self.on_export_rejected,
        )
        self.reject_btn.pack(side="left")

    def _stat_card(self, column: int, title: str, value: str, color: str = theme.TEXT_PRIMARY) -> None:
        box = stat_chip(self.stats_row, title, value, color=color)
        box.grid(row=0, column=column, sticky="nsew", padx=6)

    def show_data(
        self,
        source: str,
        frame: pd.DataFrame,
        valid_rows: list[dict[str, Any]],
        rejected_rows: list[dict[str, Any]],
        warnings: list[str] | None = None,
        pdf_meta: dict[str, Any] | None = None,
    ) -> None:
        self._pdf_meta = pdf_meta or {}
        summary = summarize_import(source, valid_rows, rejected_rows, frame, warnings)
        self._summary = summary

        for w in self.stats_row.winfo_children():
            w.destroy()

        self._stat_card(0, "Fuente", source, theme.CYAN)
        self._stat_card(1, "Facturas validas", str(summary["valid_invoices"]), theme.SUCCESS)
        self._stat_card(2, "Lineas validas", str(summary["valid_lines"]), theme.TEXT_PRIMARY)
        self._stat_card(
            3,
            "Rechazadas",
            str(summary["rejected_lines"]),
            theme.DANGER if summary["rejected_lines"] else theme.TEXT_MUTED,
        )

        lines = [
            f"Fuente: {source}",
            f"Facturas validas: {summary['valid_invoices']}",
            f"Lineas validas: {summary['valid_lines']}",
            f"Facturas rechazadas: {summary['rejected_invoices']}",
            f"Lineas rechazadas: {summary['rejected_lines']}",
            "",
            "Totales por factura:",
        ]
        for item in invoice_summaries_from_frame(frame):
            lines.append(
                f"  - {item['invoice_number']} | {item['customer']} | {item['lines']} lineas | ${item['total']:.2f}"
            )
        if warnings:
            lines.extend(["", "Advertencias:"])
            lines.extend(f"  - {w}" for w in warnings)
        if self._pdf_meta:
            lines.extend(["", "Campos detectados (PDF):"])
            for key, val in self._pdf_meta.items():
                if key != "raw_text_preview":
                    lines.append(f"  - {key}: {val}")

        self.resumen_text.delete("1.0", "end")
        self.resumen_text.insert("1.0", "\n".join(lines))

        for w in self.valid_table_frame.winfo_children():
            w.destroy()
        if frame.empty:
            ctk.CTkLabel(
                self.valid_table_frame,
                text="No hay lineas validas para mostrar.",
                text_color=theme.TEXT_MUTED,
            ).pack(anchor="w")
        else:
            preview_cols = [
                c
                for c in [
                    "Invoice Number",
                    "Date",
                    "Customer Name",
                    "Description",
                    "Quantity",
                    "Unit Price",
                    "Line Amount",
                    "Invoice Total",
                ]
                if c in frame.columns
            ]
            head = ctk.CTkFrame(self.valid_table_frame, fg_color=theme.BG_CARD, corner_radius=8)
            head.pack(fill="x", pady=(0, 4))
            for col_idx, col_name in enumerate(preview_cols):
                ctk.CTkLabel(
                    head,
                    text=col_name,
                    font=("Segoe UI", 10, "bold"),
                    text_color=theme.TEXT_SECONDARY,
                    width=120,
                    anchor="w",
                ).grid(row=0, column=col_idx, padx=6, pady=6, sticky="w")

            for _, row in frame.head(50).iterrows():
                line = ctk.CTkFrame(self.valid_table_frame, fg_color="transparent")
                line.pack(fill="x", pady=1)
                for col_idx, col_name in enumerate(preview_cols):
                    val = str(row.get(col_name, ""))[:40]
                    ctk.CTkLabel(
                        line,
                        text=val,
                        font=theme.FONT_SMALL,
                        text_color=theme.TEXT_PRIMARY,
                        width=120,
                        anchor="w",
                    ).grid(row=0, column=col_idx, padx=6, sticky="w")

        rejected_lines = ["Facturas rechazadas y motivo:", ""]
        for item in grouped_rejection_messages(rejected_rows):
            rejected_lines.append(f"{item['invoice']}: {item['reason']}")
        if not rejected_rows:
            rejected_lines.append("(ninguna)")
        self.rejected_text.delete("1.0", "end")
        self.rejected_text.insert("1.0", "\n".join(rejected_lines))

        detail_parts = []
        if self._pdf_meta.get("raw_text_preview"):
            detail_parts.append("=== Texto detectado (PDF) ===")
            detail_parts.append(self._pdf_meta["raw_text_preview"])
        if self._pdf_meta.get("detected_fields"):
            detail_parts.append("\n=== Campos ===")
            for k, v in self._pdf_meta["detected_fields"].items():
                detail_parts.append(f"{k}: {v}")
        if not detail_parts:
            detail_parts.append("Sin detalle adicional para esta fuente.")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", "\n".join(detail_parts))

        has_valid = not frame.empty
        self.load_btn.configure(state="normal" if has_valid else "disabled")
        self.reject_btn.configure(state="normal" if rejected_rows else "disabled")

        if summary["rejected_lines"] and has_valid:
            self.tabs.set("Rechazados")
        else:
            self.tabs.set("Resumen")
