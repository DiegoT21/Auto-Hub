from __future__ import annotations

from typing import Any

import pandas as pd


def invoice_numbers_from_frame(frame: pd.DataFrame) -> list[str]:
    if frame.empty or "Invoice Number" not in frame.columns:
        return []
    values = frame["Invoice Number"].astype(str).dropna().unique().tolist()
    return sorted(values)


def filter_frame_by_invoice(frame: pd.DataFrame, invoice_number: str | None) -> pd.DataFrame:
    if frame.empty or invoice_number is None or "Invoice Number" not in frame.columns:
        return frame.copy()
    return frame[frame["Invoice Number"].astype(str) == str(invoice_number)].copy()


def summarize_frame(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {"invoices": 0, "lines": 0, "total": 0.0}
    invoices = invoice_numbers_from_frame(frame)
    total = 0.0
    if "Invoice Total" in frame.columns and invoices:
        for inv in invoices:
            subset = frame[frame["Invoice Number"].astype(str) == inv]
            if not subset.empty:
                total += float(subset.iloc[0].get("Invoice Total", 0) or 0)
    return {
        "invoices": len(invoices),
        "lines": len(frame),
        "total": round(total, 2),
    }


def summarize_import(
    source: str,
    valid_rows: list[dict[str, Any]],
    rejected_rows: list[dict[str, Any]],
    frame: pd.DataFrame,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    valid_invoices = {row.get("numero_factura") for row in valid_rows}
    rejected_invoices = {row.get("numero_factura") for row in rejected_rows}
    frame_summary = summarize_frame(frame)
    return {
        "source": source,
        "valid_lines": len(valid_rows),
        "rejected_lines": len(rejected_rows),
        "valid_invoices": len(valid_invoices),
        "rejected_invoices": len(rejected_invoices),
        "warnings": warnings or [],
        "frame": frame_summary,
    }


def invoice_summaries_from_frame(frame: pd.DataFrame) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for inv in invoice_numbers_from_frame(frame):
        subset = frame[frame["Invoice Number"].astype(str) == inv]
        first = subset.iloc[0]
        summaries.append(
            {
                "invoice_number": inv,
                "customer": str(first.get("Customer Name", first.get("Customer ID", ""))),
                "date": str(first.get("Date", "")),
                "lines": len(subset),
                "total": float(first.get("Invoice Total", subset["Line Amount"].sum() if "Line Amount" in subset else 0) or 0),
            }
        )
    return summaries


def grouped_rejection_messages(rejected_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    seen: dict[str, str] = {}
    for row in rejected_rows:
        inv = str(row.get("numero_factura", "?"))
        reason = str(row.get("error_reason", "Error desconocido"))
        if inv not in seen:
            seen[inv] = reason
    return [{"invoice": inv, "reason": reason} for inv, reason in sorted(seen.items())]
