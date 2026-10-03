from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

if not getattr(sys, "frozen", False):
    _BOOTSTRAP = Path(__file__).resolve().parent.parent
    if str(_BOOTSTRAP) not in sys.path:
        sys.path.insert(0, str(_BOOTSTRAP))

import customtkinter as ctk

from src.paths import app_root, seed_runtime_files

ROOT = app_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import theme
from src.failure_view import invoice_identity
from app.components import btn, dashboard_card, fail_summary, glass_card, set_card_selected
from app.dialogs import ask_confirm, show_error, show_info
from app.user_log import classify, parse_invoice_card
from src.app_update import restart_autohub, run_update
from src.auto_poll import format_wait, next_poll
from src.ledger_bridge import base_url, is_configured
from src.sage_sdk_write import (
    TEST_COMPANY,
    authorize_sage_access,
    delete_ah_invoices,
)
from src.sage_retry import (
    failed_confirm_text,
    failed_count,
    pending_cards,
    retry_failed_invoices,
)
from src.session_log import append as append_session_log
from src.session_log import open_folder as open_logs_folder
from src.ui_log_state import load as load_ui_log_state
from src.ui_log_state import save as save_ui_log_state

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")


def _advice_for(card: dict, summary: str, detail: str) -> tuple[str, str, str]:
    text = (summary + "\n" + detail).lower()
    expected = ""
    received = ""
    match = re.search(
        r"factura\s+([0-9]+(?:\.[0-9]+)?).{0,80}?sage\s+([0-9]+(?:\.[0-9]+)?)",
        detail,
        re.I | re.S,
    )
    if "itbms" in text:
        if match:
            received = "$" + match.group(1)
            expected = "$" + match.group(2)
        return (
            "La tasa aplicada difiere de la que Sage va a calcular. Corrígela en el origen antes de volver a enviarla.",
            expected,
            received,
        )
    if card.get("retryable") or ("item" in text and "sage" in text):
        return ("Crea el producto faltante en Sage y después usa Reintentar pendientes.", "", "")
    if "cliente" in text:
        return ("Revisa el cliente en Sage antes de reenviar la factura.", "", "")
    if "incomplet" in text or "faltan items" in text:
        return ("La factura llegó sin todas sus líneas. Corrígelas en el origen; reenviarla ahora va a fallar igual.", "", "")
    if card.get("ok"):
        return ("Esta factura ya quedó guardada en Sage.", "", "")
    return ("Revisa el detalle. Reenviarla sin corregir el dato va a fallar otra vez.", "", "")

LOGO_ICO = ROOT / "assets" / "autohub.ico"
APP_ID = "Posper.AutoHub.1"
CONFIG_PATH = Path(os.environ.get("AUTOHUB_CONFIG", ROOT / "config" / "config.json"))


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    with CONFIG_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def _set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


class AutoHubApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Auto-Hub")
        self.geometry("1180x720")
        self.minsize(1024, 640)
        self.after(0, self._maximize)
        self.configure(fg_color=theme.BG_DARK)

        self.config = _load_config()
        self._auto_on = False
        self._auto_busy = False
        self._idle_idx = 0
        self._next_delay_ms = 20_000
        self._log_lock = threading.Lock()
        self._ev_q: deque[tuple[str, str]] = deque()
        saved_logs = load_ui_log_state(ROOT)
        self._n_ok = int(saved_logs["ok"])
        self._n_err = int(saved_logs["err"])
        self._n_skip = int(saved_logs["skip"])
        self._cards: deque[dict] = deque(saved_logs["cards"])
        self._skip_next_err = False
        self._current = ""
        self._last_err_text = ""
        self._last_card_text = ""
        self._last_card_at = 0.0
        self._sage_busy = False
        self._view = "all"
        self._query = ""
        self._selected_key = None
        self._selected_card: dict | None = None

        if LOGO_ICO.exists():
            try:
                self.iconbitmap(default=str(LOGO_ICO))
            except Exception:
                pass

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)
        self._build_dashboard()
        self._paint_counts()
        self._paint_cards()
        self.after(150, self._flush_logs)
        self._log("Sistema listo")
        self._refresh_status()
        self._refresh_retry_btn()

    def _maximize(self) -> None:
        try:
            self.state("zoomed")
        except Exception:
            self.attributes("-zoomed", True)

    def _build_dashboard(self) -> None:
        top = ctk.CTkFrame(self, fg_color=theme.BG_SIDEBAR, corner_radius=0, height=44)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_propagate(False)
        brand = ctk.CTkFrame(top, fg_color="transparent")
        brand.pack(side="left", padx=14)
        logo = ctk.CTkFrame(brand, width=26, height=26, fg_color=theme.ACCENT, corner_radius=6)
        logo.pack(side="left", pady=9)
        logo.pack_propagate(False)
        ctk.CTkLabel(logo, text="AH", font=("Segoe UI", 10, "bold"), text_color="white").place(
            relx=0.5, rely=0.5, anchor="center"
        )
        ctk.CTkLabel(brand, text="Auto-Hub", font=theme.FONT_LOGO, text_color=theme.TEXT_PRIMARY).pack(
            side="left", padx=(8, 0)
        )
        self.header_sage = ctk.CTkLabel(top, text="", font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY)
        self.header_sage.pack(side="left", padx=(18, 0))
        self.header_cloud = ctk.CTkLabel(top, text="", font=theme.FONT_SMALL, text_color=theme.SUCCESS)
        self.header_cloud.pack(side="left", padx=(12, 0))

        action = ctk.CTkFrame(self, fg_color="transparent")
        action.grid(row=1, column=0, sticky="ew", padx=14, pady=(10, 0))
        self.auto_btn = btn(
            action,
            text="▶  Iniciar automático",
            variant="primary",
            width=190,
            height=36,
            command=self.on_toggle_auto,
        )
        self.auto_btn.pack(side="left")
        status_box = ctk.CTkFrame(action, fg_color="transparent")
        status_box.pack(side="left", padx=(12, 0))
        status_line = ctk.CTkFrame(status_box, fg_color="transparent", height=1)
        status_line.pack(anchor="w")
        self.status_label = ctk.CTkLabel(
            status_line,
            text="Sage y G Core",
            font=("Segoe UI", 13, "bold"),
            text_color=theme.TEXT_PRIMARY,
        )
        self.status_label.pack(side="left")
        self.auto_badge = ctk.CTkLabel(
            status_line,
            text="EN PAUSA",
            font=("Segoe UI", 9, "bold"),
            text_color="#64748B",
            fg_color="#F1F5F9",
            corner_radius=8,
            height=18,
            padx=8,
        )
        self.auto_badge.pack(side="left", padx=(8, 0))
        self.live_label = ctk.CTkLabel(
            status_box,
            text="En espera.",
            font=theme.FONT_SMALL,
            text_color=theme.TEXT_SECONDARY,
            anchor="w",
        )
        self.live_label.pack(anchor="w")
        self.cycle_label = ctk.CTkLabel(
            status_box,
            text="Aun no consulta.",
            font=theme.FONT_SMALL,
            text_color=theme.TEXT_SECONDARY,
            anchor="w",
        )
        self.cycle_label.pack(anchor="w")

        self._options_open = False
        self.options_btn = btn(
            action,
            text="Opciones ▾",
            variant="secondary",
            width=110,
            height=32,
            command=self._toggle_options,
        )
        self.options_btn.pack(side="right", padx=(8, 0))
        self._options_menu = glass_card(self, radius=10)
        self._options_menu.configure(width=210)

        def menu_btn(text: str, command, *, variant: str = "ghost"):
            widget = btn(
                self._options_menu,
                text=text,
                variant=variant,
                height=theme.BTN_HEIGHT,
                command=lambda: self._run_option(command),
            )
            widget.pack(fill="x", padx=8, pady=2)
            return widget

        menu_btn("Consultar ahora", self.on_poll_now)
        self.auth_btn = menu_btn("Conectar Sage", self.on_authorize_sage, variant="secondary")
        self.delete_btn = menu_btn("Borrar AH", self.on_delete_ah)
        menu_btn("Limpiar historial", self._clear_log)
        menu_btn("Actualizar app", self.on_update_app)
        menu_btn("Ver logs", self.on_open_logs)

        stats = ctk.CTkFrame(self, fg_color="transparent")
        stats.grid(row=2, column=0, sticky="ew", padx=14, pady=(10, 0))
        for col in range(4):
            stats.grid_columnconfigure(col, weight=1)
        self.count_ok = self._stat_card(stats, "Cargadas en Sage", theme.SUCCESS, "✓")
        self.count_skip = self._stat_card(stats, "Omitidas", theme.TEXT_SECONDARY, "▷")
        self.count_wait = self._stat_card(stats, "Esperando corrección", theme.WARNING, "◷")
        self.count_fail = self._stat_card(stats, "Fallidas", theme.DANGER, "!")
        self.count_ok.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.count_skip.grid(row=0, column=1, sticky="ew", padx=6)
        self.count_wait.grid(row=0, column=2, sticky="ew", padx=6)
        self.count_fail.grid(row=0, column=3, sticky="ew", padx=(6, 0))

        tools = ctk.CTkFrame(self, fg_color="transparent")
        tools.grid(row=3, column=0, sticky="ew", padx=14, pady=(10, 0))
        self._tab_btns = {}
        for key, label in (("all", "Todas"), ("ok", "Cargadas"), ("fail", "Fallidas")):
            tab = btn(
                tools,
                text=label,
                variant="secondary",
                height=28,
                width=110,
                command=lambda k=key: self._set_view(k),
            )
            tab.pack(side="left", padx=(0, 6))
            self._tab_btns[key] = tab
        self.search_entry = ctk.CTkEntry(
            tools,
            placeholder_text="Buscar factura, cliente o ID...",
            height=28,
            width=280,
            fg_color=theme.GLASS_INPUT,
            border_color=theme.GLASS_BORDER,
        )
        self.search_entry.pack(side="left", padx=(8, 0))
        self.search_entry.bind("<KeyRelease>", lambda _e: self._on_search())
        self.retry_btn = btn(
            tools,
            text="Reintentar pendientes (0)",
            variant="secondary",
            height=28,
            width=190,
            command=self.on_retry_failed,
        )
        self.retry_btn.pack(side="right")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=4, column=0, sticky="nsew", padx=14, pady=10)
        body.grid_columnconfigure(0, weight=2)
        body.grid_columnconfigure(1, weight=3)
        body.grid_columnconfigure(2, weight=0, minsize=300)
        body.grid_rowconfigure(0, weight=1)
        self._body = body
        self.ok_host = self._scroll_column(body, "Cargadas con éxito")
        self.ok_host.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.att_host = self._scroll_column(body, "Facturas que requieren atención")
        self.att_host.grid(row=0, column=1, sticky="nsew", padx=6)
        self._build_detail(body)

        foot = ctk.CTkFrame(self, fg_color=theme.BG_SIDEBAR, corner_radius=0, height=28)
        foot.grid(row=5, column=0, sticky="ew")
        foot.grid_propagate(False)
        self.footer_sage = ctk.CTkLabel(
            foot, text="Sage: LYL 2025-2026", font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY
        )
        self.footer_sage.pack(side="left", padx=14)
        ctk.CTkLabel(foot, text="Auto-Hub", font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED).pack(
            side="right", padx=14
        )
        self._style_tabs()
        self._sync_play_button()

    def _stat_card(self, parent, title: str, color: str, icon: str) -> ctk.CTkFrame:
        box = ctk.CTkFrame(parent, fg_color="#FFFFFF", corner_radius=12, border_width=1, border_color=theme.GLASS_BORDER)
        ctk.CTkLabel(box, text=title, font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY).pack(
            anchor="w", padx=12, pady=(8, 0)
        )
        row = ctk.CTkFrame(box, fg_color="transparent", height=1)
        row.pack(fill="x", padx=12, pady=(0, 8))
        lab = ctk.CTkLabel(row, text="0", font=("Segoe UI", 22, "bold"), text_color=theme.TEXT_PRIMARY)
        lab.pack(side="left")
        ctk.CTkLabel(row, text=icon, font=("Segoe UI", 16), text_color=color).pack(side="right")
        box._value = lab  # type: ignore[attr-defined]
        return box

    def _scroll_column(self, parent, title: str) -> ctk.CTkFrame:
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.grid_rowconfigure(1, weight=1)
        wrap.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(wrap, text=title, font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY, anchor="w").grid(
            row=0, column=0, sticky="ew", pady=(0, 4)
        )
        host = ctk.CTkScrollableFrame(wrap, fg_color="transparent")
        host.grid(row=1, column=0, sticky="nsew")
        wrap._host = host  # type: ignore[attr-defined]
        wrap._title = wrap.grid_slaves(row=0, column=0)[0]  # type: ignore[attr-defined]
        return wrap

    def _build_detail(self, parent) -> None:
        panel = ctk.CTkFrame(parent, fg_color="#FFFFFF", corner_radius=12, border_width=1, border_color=theme.GLASS_BORDER)
        panel.grid(row=0, column=2, sticky="nsew", padx=(6, 0))
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_columnconfigure(0, weight=1)
        head = ctk.CTkFrame(panel, fg_color="transparent", height=1)
        head.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 0))
        ctk.CTkLabel(head, text="Detalle de la factura", font=("Segoe UI", 13, "bold"), text_color=theme.TEXT_PRIMARY).pack(
            side="left"
        )
        self.detail_kind = ctk.CTkLabel(
            head, text="", font=("Segoe UI", 9, "bold"), text_color=theme.DANGER, fg_color="#FEF2F2", corner_radius=8, padx=6
        )
        self.detail_close = btn(head, text="✕", variant="ghost", width=28, height=24, command=self._clear_selection)
        self.detail_close.pack(side="right")
        self.detail_kind.pack(side="right", padx=(0, 6))
        body = ctk.CTkScrollableFrame(panel, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
        self.detail_body = body
        self.detail_empty = ctk.CTkLabel(
            body,
            text="Selecciona una factura de la lista para ver su detalle.",
            font=theme.FONT_SMALL,
            text_color=theme.TEXT_SECONDARY,
            wraplength=240,
            justify="left",
        )
        self.detail_empty.pack(anchor="w", pady=8)

        content = ctk.CTkFrame(body, fg_color="transparent")
        self.detail_content = content
        self.detail_ref = ctk.CTkLabel(content, text="", font=("Segoe UI", 16, "bold"), text_color=theme.TEXT_PRIMARY, anchor="w")
        self.detail_ref.pack(anchor="w", pady=(4, 2))
        self.detail_cust = ctk.CTkLabel(content, text="", font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY, anchor="w", justify="left")
        self.detail_cust.pack(anchor="w", fill="x")
        self.detail_date = ctk.CTkLabel(content, text="", font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY, anchor="w")
        self.detail_date.pack(anchor="w")

        advice_box = ctk.CTkFrame(content, fg_color="#F8FAFC", corner_radius=8, border_width=1, border_color=theme.GLASS_BORDER)
        advice_box.pack(fill="x", pady=(10, 6))
        self.detail_advice_box = advice_box
        ctk.CTkLabel(
            advice_box, text="Acción recomendada", font=("Segoe UI", 11, "bold"), text_color=theme.TEXT_PRIMARY, anchor="w"
        ).pack(anchor="w", padx=10, pady=(8, 2))
        self.detail_advice = ctk.CTkLabel(
            advice_box, text="", font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY, wraplength=200, justify="left", anchor="w"
        )
        self.detail_advice.pack(anchor="w", fill="x", padx=10, pady=(0, 8))
        nums = ctk.CTkFrame(advice_box, fg_color="transparent")
        self.detail_nums = nums
        self.detail_values = {}
        for title in ("ESPERADO", "RECIBIDO"):
            cell = ctk.CTkFrame(nums, fg_color="#FFFFFF", corner_radius=8, border_width=1, border_color=theme.GLASS_BORDER)
            cell.pack(side="left", fill="x", expand=True, padx=(0, 6))
            ctk.CTkLabel(cell, text=title, font=("Segoe UI", 9, "bold"), text_color=theme.TEXT_MUTED).pack(anchor="w", padx=8, pady=(6, 0))
            value = ctk.CTkLabel(cell, text="", font=("Segoe UI", 13, "bold"), text_color=theme.TEXT_PRIMARY)
            value.pack(anchor="w", padx=8, pady=(0, 6))
            self.detail_values[title] = value
        advice_box.bind("<Configure>", self._wrap_advice)

        ctk.CTkLabel(content, text="Detalle técnico", font=("Segoe UI", 11, "bold"), text_color=theme.TEXT_PRIMARY, anchor="w").pack(
            anchor="w", pady=(8, 2)
        )
        self.detail_tech = ctk.CTkTextbox(
            content, height=110, wrap="word", fg_color="#0F172A", text_color="#E2E8F0", font=("Cascadia Mono", 10)
        )
        self.detail_tech.pack(fill="x")
        self.detail_data_title = ctk.CTkLabel(
            content, text="Datos recibidos", font=("Segoe UI", 11, "bold"), text_color=theme.TEXT_PRIMARY, anchor="w"
        )
        self.detail_data = ctk.CTkTextbox(
            content, height=90, wrap="word", fg_color="#0F172A", text_color="#E2E8F0", font=("Cascadia Mono", 10)
        )
        self._detail_sig = None
        foot = ctk.CTkFrame(panel, fg_color="transparent", height=1)
        foot.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        self.detail_retry = btn(
            foot, text="Reintentar factura", variant="primary", height=32, command=self.on_retry_failed
        )
        self.detail_close_btn = btn(
            foot, text="Cerrar detalle", variant="secondary", width=110, height=32, command=self._clear_selection
        )
        self._detail_panel = panel

    def _refresh_status(self) -> None:
        jwt_ok = is_configured(ROOT, self.config)
        self.header_sage.configure(text="Sage: " + TEST_COMPANY)
        if jwt_ok:
            self.header_cloud.configure(text="●  G Core conectado", text_color=theme.SUCCESS)
            self.status_label.configure(text="Sage y G Core conectados")
        else:
            self.header_cloud.configure(text="●  Falta la clave de G Core", text_color=theme.DANGER)
            self.status_label.configure(text="Falta la clave de G Core")
        self.footer_sage.configure(text="Sage: " + TEST_COMPANY)

    def _clear_log(self) -> None:
        self._n_ok = 0
        self._n_err = 0
        self._n_skip = 0
        self._cards.clear()
        self._skip_next_err = False
        self._current = ""
        self._last_err_text = ""
        self._last_card_text = ""
        self._last_card_at = 0.0
        self._selected_key = None
        self._selected_card = None
        self._set_live("En espera.")
        self.cycle_label.configure(text="Aun no consulta.")
        self._paint_counts()
        self._paint_cards()
        self._save_log_state()

    def _set_live(self, text: str) -> None:
        shown = "" if text in ("En espera.", "Auto-Hub listo.") else text
        self.live_label.configure(text=shown)

    def _paint_counts(self) -> None:
        self.count_ok._value.configure(text=str(self._n_ok))  # type: ignore[attr-defined]
        self.count_skip._value.configure(text=str(self._n_skip))  # type: ignore[attr-defined]
        self.count_wait._value.configure(text=str(getattr(self, "_pending_count", 0)))  # type: ignore[attr-defined]
        self.count_fail._value.configure(text=str(getattr(self, "_fail_count", 0)))  # type: ignore[attr-defined]

    def _save_log_state(self) -> None:
        try:
            save_ui_log_state(
                ROOT,
                ok=self._n_ok,
                err=self._n_err,
                skip=self._n_skip,
                cards=self._cards,
            )
        except Exception:
            pass

    def _lists(self) -> tuple[list[dict], list[dict], list[dict]]:
        pending = pending_cards(ROOT)
        for card in pending:
            card["retryable"] = True
        queued = {invoice_identity(card) for card in pending}
        latest: dict = {}
        order: list = []
        for card in self._cards:
            key = invoice_identity(card)
            if key in latest:
                order.remove(key)
            latest[key] = card
            order.append(key)
        ok_cards = [latest[key] for key in reversed(order) if latest[key].get("ok")]
        failed = [latest[key] for key in reversed(order) if not latest[key].get("ok") and key not in queued]
        return ok_cards, list(reversed(pending)), failed

    def _matches(self, card: dict) -> bool:
        query = self._query.strip().lower()
        if not query:
            return True
        blob = " ".join(
            str(card.get(key) or "")
            for key in ("ref", "customer_name", "customer_id", "detail", "date")
        ).lower()
        return query in blob or query in fail_summary(card).lower()

    def _fill_column(self, host, cards: list[dict], empty: str) -> None:
        cache = getattr(host, "_cards_cache", None)
        if cache is None:
            cache = host._cards_cache = {}
            host._cards_order = []
            host._empty = ctk.CTkLabel(host, text="", font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY, anchor="w")
        shown = []
        seen = set()
        for card in cards:
            key = invoice_identity(card)
            if key in seen or not self._matches(card):
                continue
            seen.add(key)
            shown.append((key, card))
        for key in list(cache):
            if key not in seen:
                cache.pop(key)[1].destroy()
        rebuilt = False
        for key, card in shown:
            tone = "ok" if card.get("ok") else ("wait" if card.get("retryable") else "fail")
            sig = tone + json.dumps(card, sort_keys=True, ensure_ascii=False, default=str)
            current = cache.get(key)
            if current and current[0] == sig:
                continue
            if current:
                current[1].destroy()
            widget = dashboard_card(
                host,
                card,
                tone=tone,
                selected=key == self._selected_key,
                on_open=lambda k=key: self._show_detail(k),
                on_solution=(lambda k=key: self._show_detail(k)) if tone == "wait" else None,
            )
            cache[key] = (sig, widget, card)
            rebuilt = True
        order = [key for key, _ in shown]
        if rebuilt or order != host._cards_order:
            for key in host._cards_order:
                if key in cache:
                    cache[key][1].pack_forget()
            for key in order:
                cache[key][1].pack(fill="x", pady=(0, 6))
            host._cards_order = order
        if shown:
            host._empty.pack_forget()
        else:
            host._empty.configure(text=empty)
            host._empty.pack(anchor="w", pady=6)

    def _card_for(self, key) -> dict | None:
        for column in (self.ok_host, self.att_host):
            entry = getattr(column._host, "_cards_cache", {}).get(key)
            if entry:
                return entry[2]
        return None

    def _highlight(self, key, selected: bool) -> None:
        for column in (self.ok_host, self.att_host):
            entry = getattr(column._host, "_cards_cache", {}).get(key)
            if entry:
                set_card_selected(entry[1], selected)

    def _paint_cards(self) -> None:
        ok_cards, waiting, failed = self._lists()
        self._pending_count = len(waiting)
        self._fail_count = len(failed)
        self._paint_counts()
        self.retry_btn.configure(text="Reintentar pendientes (" + str(len(waiting)) + ")")
        self._tab_btns["ok"].configure(text="Cargadas  " + str(len(ok_cards)))
        self._tab_btns["fail"].configure(text="Fallidas  " + str(len(failed)))
        view = self._view
        if view == "ok":
            self.ok_host.grid()
            self.att_host.grid_remove()
            self._fill_column(self.ok_host._host, ok_cards, "Sin facturas cargadas.")
        elif view == "fail":
            self.ok_host.grid_remove()
            self.att_host.grid()
            self._fill_column(self.att_host._host, failed, "Sin facturas fallidas.")
        else:
            self.ok_host.grid()
            self.att_host.grid()
            self._fill_column(self.ok_host._host, ok_cards, "Sin facturas cargadas.")
            self._fill_column(
                self.att_host._host,
                failed + waiting,
                "Sin facturas pendientes.",
            )
        self.ok_host._title.configure(text="Cargadas con éxito (" + str(len(ok_cards)) + ")")
        attention = len(failed) + len(waiting)
        self.att_host._title.configure(
            text="Facturas que requieren atención ("
            + str(attention)
            + ")    "
            + str(len(waiting))
            + " para corregir · "
            + str(len(failed))
            + " fallidas"
        )
        if self._selected_key is not None:
            fresh = self._card_for(self._selected_key)
            if fresh is not None:
                self._selected_card = fresh
            self._render_detail(self._selected_card)

    def _set_view(self, view: str) -> None:
        self._view = view
        self._style_tabs()
        self._paint_cards()

    def _style_tabs(self) -> None:
        for key, tab in self._tab_btns.items():
            if key == self._view:
                tab.configure(fg_color=theme.ACCENT, text_color="white", border_color=theme.ACCENT)
            else:
                tab.configure(fg_color="#FFFFFF", text_color=theme.TEXT_PRIMARY, border_color=theme.GLASS_BORDER)

    def _on_search(self) -> None:
        self._query = self.search_entry.get()
        self._paint_cards()

    def _clear_selection(self) -> None:
        if self._selected_key is not None:
            self._highlight(self._selected_key, False)
        self._selected_key = None
        self._selected_card = None
        self._render_detail(None)

    def _show_detail(self, key) -> None:
        card = self._card_for(key)
        if card is None:
            return
        if self._selected_key is not None and self._selected_key != key:
            self._highlight(self._selected_key, False)
        self._selected_key = key
        self._selected_card = card
        self._highlight(key, True)
        self._render_detail(card)

    def _scale(self) -> float:
        try:
            return float(ctk.ScalingTracker.get_widget_scaling(self))
        except Exception:
            return 1.0

    def _wrap_advice(self, event=None) -> None:
        width = self.detail_advice_box.winfo_width() / self._scale()
        wrap = max(140, int(width) - 28)
        if getattr(self, "_advice_wrap", None) != wrap:
            self._advice_wrap = wrap
            self.detail_advice.configure(wraplength=wrap)
            self.detail_cust.configure(wraplength=wrap + 10)

    @staticmethod
    def _set_text(box: ctk.CTkTextbox, text: str) -> None:
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", text)
        box.configure(state="disabled")

    def _render_detail(self, card: dict | None) -> None:
        sig = None if not card else json.dumps(card, sort_keys=True, ensure_ascii=False, default=str)
        if sig == self._detail_sig:
            return
        self._detail_sig = sig
        if not card:
            self.detail_content.pack_forget()
            self.detail_empty.pack(anchor="w", pady=8)
            self.detail_kind.configure(text="")
            self.detail_retry.pack_forget()
            self.detail_close_btn.pack_forget()
            return
        self.detail_empty.pack_forget()
        if not self.detail_content.winfo_manager():
            self.detail_content.pack(fill="x")
        retryable = bool(card.get("retryable"))
        detail = str(card.get("detail") or "").strip()
        summary = fail_summary(card)
        kind = "Esperando corrección" if retryable else ("Cargada" if card.get("ok") else "Error de Sage")
        color = theme.WARNING if retryable else (theme.SUCCESS if card.get("ok") else theme.DANGER)
        soft = "#FFFBEB" if retryable else ("#ECFDF5" if card.get("ok") else "#FEF2F2")
        self.detail_kind.configure(text=kind, text_color=color, fg_color=soft)
        self.detail_ref.configure(text="#" + str(card.get("ref") or "Factura").lstrip("#"))
        cust = str(card.get("customer_name") or card.get("customer_id") or "Sin cliente")
        self.detail_cust.configure(text="Cliente:  " + cust)
        when = str(card.get("date") or "").strip()
        if when:
            self.detail_date.configure(text="Fecha/hora:  " + when)
            if not self.detail_date.winfo_manager():
                self.detail_date.pack(anchor="w", after=self.detail_cust)
        else:
            self.detail_date.pack_forget()
        advice, expected, received = _advice_for(card, summary, detail)
        self.detail_advice.configure(text=advice)
        if expected and received:
            self.detail_values["ESPERADO"].configure(text=expected)
            self.detail_values["RECIBIDO"].configure(text=received)
            if not self.detail_nums.winfo_manager():
                self.detail_nums.pack(fill="x", padx=10, pady=(0, 8))
        else:
            self.detail_nums.pack_forget()
        self._set_text(self.detail_tech, detail or summary or "Sin detalle técnico.")
        lines = [ln for ln in (card.get("lines") or []) if isinstance(ln, dict)]
        if lines:
            self._set_text(self.detail_data, json.dumps(lines, ensure_ascii=False, indent=2))
            if not self.detail_data.winfo_manager():
                self.detail_data_title.pack(anchor="w", pady=(8, 2))
                self.detail_data.pack(fill="x", pady=(0, 8))
        else:
            self.detail_data_title.pack_forget()
            self.detail_data.pack_forget()
        if not self.detail_close_btn.winfo_manager():
            self.detail_close_btn.pack(side="right")
        if retryable:
            if not self.detail_retry.winfo_manager():
                self.detail_retry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        else:
            self.detail_retry.pack_forget()
        self._wrap_advice()

    def _log(self, msg: str) -> None:
        self._log_from_thread(msg)

    def _log_from_thread(self, msg: str) -> None:
        ev = classify(msg)
        if not ev:
            return
        kind, shown = ev
        with self._log_lock:
            if kind == "card":
                now = time.monotonic()
                if shown == self._last_card_text and now - self._last_card_at < 5.0:
                    return
                self._last_card_text = shown
                self._last_card_at = now
            if kind == "err" and shown == self._last_err_text:
                return
            if kind == "err":
                self._last_err_text = shown
            elif kind in ("ok", "load"):
                self._last_err_text = ""
            self._ev_q.append(ev)
        try:
            append_session_log(ROOT, kind, shown)
        except Exception:
            pass

    def _flush_logs(self) -> None:
        try:
            with self._log_lock:
                batch = list(self._ev_q)
                self._ev_q.clear()
            if batch:
                self._apply_events(batch)
        finally:
            try:
                if self.winfo_exists():
                    self.after(150, self._flush_logs)
            except Exception:
                pass

    def _apply_events(self, batch: list[tuple[str, str]]) -> None:
        events: list[tuple[str, str]] = []
        pending_status: tuple[str, str] | None = None
        for ev in batch:
            if ev[0] == "status":
                pending_status = ev
                continue
            if pending_status:
                events.append(pending_status)
                pending_status = None
            events.append(ev)
        if pending_status:
            events.append(pending_status)

        counts_changed = False
        cards_changed = False
        refresh_retry = False
        live = ""
        for kind, text in events:
            if kind == "status":
                live = text
            elif kind == "load":
                self._current = text
                live = "Cargando " + text
                self._skip_next_err = False
            elif kind == "card":
                data = parse_invoice_card(text)
                if not data:
                    continue
                self._cards.append(data)
                cards_changed = True
                if data.get("ok"):
                    self._n_ok += 1
                    live = "Cargada: " + str(data.get("ref") or self._current or text)
                    self._skip_next_err = False
                else:
                    self._n_err += 1
                    live = "Fallo: " + str(data.get("ref") or data.get("detail") or text)
                    self._skip_next_err = True
                    refresh_retry = True
                counts_changed = True
                self._current = ""
            elif kind == "ok":
                live = "Cargada: " + (self._current or text)
                self._current = ""
                self._skip_next_err = False
                refresh_retry = True
            elif kind == "err":
                live = "Fallo: " + text
                failed_ref = self._current
                self._current = ""
                refresh_retry = True
                if self._skip_next_err:
                    continue
                if not failed_ref:
                    continue
                self._cards.append(
                    {
                        "ok": False,
                        "ref": (failed_ref or "Factura").split(" · ")[0],
                        "date": "",
                        "customer_id": "",
                        "customer_name": "",
                        "total": "",
                        "detail": text,
                        "lines": [],
                    }
                )
                self._n_err += 1
                self._skip_next_err = True
                cards_changed = True
                counts_changed = True
            elif kind == "skip":
                n = 1
                for part in text.split():
                    if part.isdigit():
                        n = int(part)
                        break
                self._n_skip += n
                counts_changed = True
                live = text
                low = text.lower()
                if "esperando items" in low or "en cola" in low or "fallida" in low:
                    refresh_retry = True
        if live:
            self._set_live(live)
        if counts_changed:
            self._paint_counts()
        if cards_changed:
            self._paint_cards()
        if counts_changed or cards_changed:
            self._save_log_state()
        if refresh_retry:
            self._refresh_retry_btn()

    def _toggle_options(self) -> None:
        if self._options_open:
            self._close_options()
            return
        self.update_idletasks()
        # CTk multiplica x/y de place() por el escalado de Windows; se pasan en unidades logicas.
        scale = self._scale()
        right = (self.options_btn.winfo_rootx() - self.winfo_rootx() + self.options_btn.winfo_width()) / scale
        bottom = (self.options_btn.winfo_rooty() - self.winfo_rooty() + self.options_btn.winfo_height()) / scale
        self._options_menu.place(x=max(8, int(right - 210)), y=int(bottom + 6))
        self._options_menu.lift()
        self._options_open = True
        self.options_btn.configure(text="Opciones ▴")

    def _close_options(self) -> None:
        if not self._options_open:
            return
        self._options_menu.place_forget()
        self._options_open = False
        self.options_btn.configure(text="Opciones ▾")

    def _run_option(self, command) -> None:
        self._close_options()
        command()

    def _sync_play_button(self) -> None:
        if self._auto_on:
            self.auto_btn.configure(text="⏸  Pausar automático")
            self.auto_badge.configure(text="AUTOMÁTICO ACTIVO", text_color="#047857", fg_color="#D1FAE5")
        else:
            self.auto_btn.configure(text="▶  Iniciar automático")
            self.auto_badge.configure(text="EN PAUSA", text_color="#64748B", fg_color="#F1F5F9")

    def on_poll_now(self) -> None:
        if self._auto_busy or self._sage_busy:
            show_info(self, "Consultar ahora", "Espera a que termine la consulta en curso.")
            return
        self._begin_cycle()

    def on_toggle_auto(self) -> None:
        self._auto_on = not self._auto_on
        self._sync_play_button()
        if self._auto_on:
            self._log("Modo automatico ON")
            if is_configured(ROOT, self.config):
                self._log("Ledger Bridge: " + base_url(self.config))
            else:
                self._log("Sin JWT de Ledger Bridge. Pon config/ledger_bridge.jwt")
            self._log("Sage debe quedar abierto en LYL.")
            self._idle_idx = 0
            self._next_delay_ms = 20_000
            self._schedule_auto(immediate=True)
        else:
            timer = getattr(self, "_auto_timer", None)
            if timer:
                self.after_cancel(timer)
                self._auto_timer = None
            self._log("Modo automatico OFF")
            self.cycle_label.configure(text="Terminando consulta en curso; no se programaran mas." if self._auto_busy else "En pausa. Sin consultas programadas.")

    def _schedule_auto(self, immediate: bool = False) -> None:
        if not self._auto_on:
            return
        delay = 400 if immediate else max(1, int(self._next_delay_ms))
        old = getattr(self, "_auto_timer", None)
        if old:
            self.after_cancel(old)
        self._auto_timer = self.after(delay, self._auto_tick)

    def _auto_tick(self) -> None:
        self._auto_timer = None
        if not self._auto_on:
            return
        if self._auto_busy:
            return
        if self._sage_busy:
            self._schedule_auto()
            return
        self._begin_cycle()

    def _begin_cycle(self) -> None:
        self._auto_busy = True
        self._set_live("Consultando y procesando pendientes...")
        self.cycle_label.configure(text="Consulta en curso.")

        def worker() -> None:
            t0 = time.time()
            try:
                from src.extractor_inbox import process_extractor_outbox

                stats = process_extractor_outbox(
                    ROOT,
                    self.config,
                    on_log=self._log_from_thread,
                )
                self.after(0, self._on_auto_cycle, stats, "", time.time() - t0)
            except Exception as exc:
                self.after(0, self._on_auto_cycle, None, str(exc), time.time() - t0)

        threading.Thread(target=worker, daemon=True).start()

    def _on_auto_cycle(self, stats: dict | None, error: str, elapsed: float = 0.0) -> None:
        self._auto_busy = False
        if error:
            self._log("ERROR automatico: " + error)
        self._idle_idx, self._next_delay_ms, reason = next_poll(self._idle_idx, stats, error)
        self._set_cycle_summary(stats, error, elapsed, reason, self._next_delay_ms)
        self._refresh_retry_btn()
        self._schedule_auto()

    def _set_cycle_summary(
        self,
        stats: dict | None,
        error: str,
        elapsed: float,
        reason: str = "empty",
        delay_ms: int = 0,
    ) -> None:
        hhmm = datetime.now().strftime("%H:%M")
        sec = str(round(elapsed, 1)) + " s"
        wait = format_wait(delay_ms) if delay_ms else ""
        if error:
            summary = "Ultima consulta " + hhmm + " · " + sec + " · error · reintento en " + wait
        elif stats and stats.get("blocked"):
            summary = "Ultima consulta " + hhmm + " · bloqueada: revisa Sage y la conexion · reintento en " + wait
        elif stats and stats.get("cloud_empty"):
            summary = "Ultima consulta " + hhmm + " · " + sec + " · cola vacia · proxima en " + wait
        elif not stats or not (stats.get("sent") or stats.get("failed") or stats.get("skipped")):
            summary = "Ultima consulta " + hhmm + " · " + sec + " · sin facturas procesadas · proxima en " + wait
        else:
            bits: list[str] = []
            sent = int(stats.get("sent") or 0)
            skipped = int(stats.get("skipped") or 0)
            failed = int(stats.get("failed") or 0)
            if sent:
                bits.append(str(sent) + " cargadas")
            if skipped:
                bits.append(str(skipped) + " omitidas")
            if failed:
                bits.append(str(failed) + (" fallo" if failed == 1 else " fallos"))
            extra = " · reintento en " + wait if reason == "error" else " · proxima en " + wait
            summary = "Ultima consulta " + hhmm + " · " + sec + " · " + ", ".join(bits) + extra
        if not self._auto_on:
            summary = summary.split(" · proxima en ")[0].split(" · reintento en ")[0] + " · En pausa"
        self.cycle_label.configure(text=summary)

    def on_open_logs(self) -> None:
        try:
            open_logs_folder(ROOT)
        except Exception as exc:
            show_error(self, "Logs", str(exc))

    def _set_sage_btns(self, busy: bool) -> None:
        self._sage_busy = busy
        state = "disabled" if busy else "normal"
        try:
            self.auth_btn.configure(state=state)
            self.retry_btn.configure(state=state)
            self.delete_btn.configure(state=state)
        except Exception:
            pass

    def _refresh_retry_btn(self) -> None:
        self._paint_cards()

    def on_retry_failed(self) -> None:
        if self._sage_busy:
            return
        if self._auto_busy:
            show_info(self, "Reenviar fallidas", "Espera a que termine la consulta en curso.")
            return
        if self._auto_on:
            show_error(self, "Enviar fallidas", "Pon Pausa antes de reenviar.")
            return
        n = failed_count(ROOT)
        if n < 1:
            show_info(self, "Enviar fallidas", "No hay facturas esperando items.")
            return
        try:
            if not ask_confirm(self, "Enviar fallidas", failed_confirm_text(ROOT)):
                return
        except Exception as exc:
            show_error(self, "Enviar fallidas", str(exc))
            return
        self._set_sage_btns(True)
        self._log("Reenviando facturas fallidas...")

        def worker() -> None:
            try:
                stats = retry_failed_invoices(ROOT, on_log=self._log_from_thread)
                msg = (
                    "Cargadas "
                    + str(stats.get("sent") or 0)
                    + ". Siguen "
                    + str(stats.get("remaining") or 0)
                    + "."
                )
                self.after(0, self._on_retry_done, True, msg)
            except Exception as exc:
                self.after(0, self._on_retry_done, False, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_retry_done(self, ok: bool, message: str) -> None:
        self._set_sage_btns(False)
        self._refresh_retry_btn()
        self._log(message)
        if ok:
            show_info(self, "Enviar fallidas", message)
        else:
            show_error(self, "Enviar fallidas", message)

    def on_delete_ah(self) -> None:
        if self._sage_busy:
            return
        if self._auto_on:
            show_error(self, "Borrar AH", "Pon Pausa antes de borrar.")
            return
        try:
            if not ask_confirm(
                self,
                "Borrar facturas AH",
                "Esto borra en Sage TODAS las Sales Invoices cuyo Invoice No. empieza con AH.\n"
                "Ejemplo: AH110926-C-03380.\n\n"
                "No toca facturas que no sean de Auto-Hub.\n"
                "Sage tiene que estar abierto en LYL 2025-2026.\n"
                "Cierra la lista de facturas si la tienes abierta, o dale Refresh despues.\n\n"
                "Luego Auto-Hub las puede volver a cargar.",
            ):
                return
        except Exception as exc:
            show_error(self, "Borrar AH", str(exc))
            return
        self._set_sage_btns(True)
        self._log("Borrando facturas AH de Sage...")

        def worker() -> None:
            try:
                stats = delete_ah_invoices(ROOT, on_log=self._log_from_thread)
                msg = (
                    "Borradas "
                    + str(stats.get("deleted") or 0)
                    + ". Fallos "
                    + str(stats.get("failed") or 0)
                    + "."
                )
                self.after(0, self._on_delete_ah_done, True, msg)
            except Exception as exc:
                self.after(0, self._on_delete_ah_done, False, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_delete_ah_done(self, ok: bool, message: str) -> None:
        self._set_sage_btns(False)
        self._log(message)
        if ok:
            show_info(self, "Borrar AH", message)
        else:
            show_error(self, "Borrar AH", message)

    def on_authorize_sage(self) -> None:
        if self._sage_busy:
            return
        try:
            if not ask_confirm(
                self,
                "Conectar Sage",
                "1. Abre Sage 50\n"
                "2. Entra a LYL CONSTRUCTIONS SUPPLY INC 2025-2026\n"
                "3. Pulsa Confirmar y, cuando Sage pregunte, elige Always Allow",
            ):
                return
        except Exception as exc:
            show_error(self, "Conectar Sage", str(exc))
            return
        self._set_sage_btns(True)
        self._log("Conectando con Sage 50 — esperando Always Allow...")

        def worker() -> None:
            try:
                authorize_sage_access(ROOT, on_log=self._log_from_thread)
                self.after(0, self._on_sage_done, True, "OK — Sage conectado.")
            except Exception as exc:
                self.after(0, self._on_sage_done, False, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_sage_done(self, ok: bool, message: str) -> None:
        self._set_sage_btns(False)
        self._log(message)
        if ok:
            show_info(self, "Sage 50", message)
        else:
            show_error(self, "Sage 50", message)

    def on_update_app(self) -> None:
        confirm = (
            "Si hay AutoHub-update.zip en el Escritorio o junto al exe, "
            "lo aplica y reinicia.\nNo toca ledger_bridge.jwt.\n\nSage puede seguir abierto."
        )
        if not ask_confirm(self, "Actualizar Auto-Hub", confirm):
            return
        self._log("Actualizando Auto-Hub...")

        def worker() -> None:
            try:
                run_update(ROOT, on_log=self._log_from_thread)
                self.after(0, self._on_update_done, True, "Actualizado. Reiniciando...")
            except Exception as exc:
                self.after(0, self._on_update_done, False, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_update_done(self, ok: bool, message: str) -> None:
        self._log(message)
        if not ok:
            show_error(self, "Actualizar", message)
            return
        show_info(self, "Actualizar", message)
        try:
            restart_autohub(ROOT)
        except Exception as exc:
            self._log("No se pudo reiniciar solo: " + str(exc))
            return
        self.after(400, self.destroy)


def main() -> None:
    seed_runtime_files()
    _set_windows_app_id()
    app = AutoHubApp()
    app.mainloop()


if __name__ == "__main__":
    main()
