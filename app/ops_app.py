from __future__ import annotations

import json
import os
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
from app.history_panel import HistoryPanel
from src.failure_view import failure_groups
from app.components import btn, glass_card, invoice_card
from app.dialogs import ask_confirm, show_error, show_info
from app.user_log import classify, parse_invoice_card
from src.app_update import restart_autohub, run_update
from src.auto_poll import format_wait, next_poll
from src.ledger_bridge import base_url, is_configured
from src.sage_sdk_write import (
    TEST_COMPANY,
    authorize_sage_access,
    delete_ah_invoices,
    probe_sage_items,
    run_full_sage_probe,
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
        self.geometry("1080x720")
        self.minsize(960, 620)
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

        if LOGO_ICO.exists():
            try:
                self.iconbitmap(default=str(LOGO_ICO))
            except Exception:
                pass

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main()
        self._paint_counts()
        self._paint_cards()
        self.after(150, self._flush_logs)
        self._log("Sistema listo")
        self._refresh_status()
        self._refresh_retry_btn()

    def _build_sidebar(self) -> None:
        sidebar = glass_card(self, radius=0, glow=False)
        sidebar.configure(fg_color=theme.BG_SIDEBAR, border_width=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.configure(width=248)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=12, pady=(14, 12))
        logo = ctk.CTkFrame(brand, width=28, height=28, fg_color=theme.ACCENT, corner_radius=6)
        logo.pack(side="left")
        logo.pack_propagate(False)
        ctk.CTkLabel(logo, text="AH", font=("Segoe UI", 11, "bold"), text_color="white").place(
            relx=0.5, rely=0.5, anchor="center"
        )
        ctk.CTkLabel(brand, text="Auto-Hub", font=theme.FONT_LOGO, text_color=theme.TEXT_PRIMARY).pack(
            side="left", padx=(8, 0)
        )

        btns = ctk.CTkFrame(sidebar, fg_color="transparent")
        btns.pack(fill="x", padx=10, pady=(0, 8))

        def side_btn(text: str, command, *, variant: str = "ghost", width: int = 220):
            widget = btn(
                btns,
                text=text,
                variant=variant,
                width=width,
                height=theme.BTN_HEIGHT_LG,
                command=command,
            )
            widget.pack(fill="x", pady=3)
            return widget

        self.auth_btn = side_btn("Conectar Sage", self.on_authorize_sage, variant="secondary")
        self.auto_btn = side_btn("Automatico: OFF", self.on_toggle_auto, variant="primary")
        self.retry_btn = side_btn("Enviar fallidas", self.on_retry_failed, variant="danger")
        self.delete_btn = side_btn("Borrar AH", self.on_delete_ah)
        side_btn("Limpiar historial", self._clear_log)
        side_btn("Actualizar app", self.on_update_app)
        side_btn("Ver logs", self.on_open_logs)

        ctk.CTkLabel(
            sidebar,
            text="LYL 2025-2026",
            text_color=theme.TEXT_MUTED,
            font=theme.FONT_SMALL,
        ).pack(side="bottom", anchor="w", padx=14, pady=(0, 14))

    def _build_main(self) -> None:
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=12, pady=12)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(2, weight=1)

        self.status_label = ctk.CTkLabel(
            main,
            text="Sage y G Core",
            font=theme.FONT_HEADING,
            text_color=theme.TEXT_PRIMARY,
            anchor="w",
        )
        self.status_label.grid(row=0, column=0, sticky="ew")

        now = glass_card(main)
        now.grid(row=1, column=0, sticky="ew", pady=(10, 10))
        now_in = ctk.CTkFrame(now, fg_color="transparent")
        now_in.pack(fill="x", padx=theme.BENTO_PAD, pady=theme.BENTO_PAD)
        ctk.CTkLabel(
            now_in,
            text="Ahora",
            font=theme.FONT_SMALL,
            text_color=theme.TEXT_MUTED,
            anchor="w",
        ).pack(anchor="w")
        self.live_label = ctk.CTkLabel(
            now_in,
            text="En espera.",
            font=theme.FONT_HEADING,
            text_color=theme.ACCENT,
            anchor="w",
            wraplength=740,
            justify="left",
        )
        self.live_label.pack(anchor="w", pady=(2, 2))
        self.cycle_label = ctk.CTkLabel(
            now_in,
            text="Aun no consulta.",
            font=theme.FONT_SMALL,
            text_color=theme.TEXT_MUTED,
            anchor="w",
            wraplength=740,
            justify="left",
        )
        self.cycle_label.pack(anchor="w", pady=(0, 8))
        counts = ctk.CTkFrame(now_in, fg_color="transparent")
        counts.pack(fill="x")
        self.count_ok = self._count_chip(counts, "Cargadas", "0", theme.SUCCESS)
        self.count_skip = self._count_chip(counts, "Omitidas", "0", theme.WARNING)
        self.count_err = self._count_chip(counts, "Pendientes de reenvio", "0", theme.DANGER)
        self.count_ok.pack(side="left")
        self.count_skip.pack(side="left", padx=(8, 0))
        self.count_err.pack(side="left", padx=(8, 0))

        lists = ctk.CTkFrame(main, fg_color="transparent")
        lists.grid(row=2, column=0, sticky="nsew")
        lists.grid_columnconfigure(0, weight=1)
        lists.grid_columnconfigure(1, weight=1)
        lists.grid_rowconfigure(0, weight=1)

        self.ok_host = self._card_column(lists, "Cargadas", theme.SUCCESS)
        self.ok_host.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.err_host = self._card_column(lists, "Fallidas", theme.DANGER)
        self.err_host.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

    def _card_column(self, parent, title: str, color: str) -> ctk.CTkFrame:
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.grid_columnconfigure(0, weight=1)
        wrap.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            wrap,
            text=title,
            font=theme.FONT_HEADING,
            text_color=color,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 4))
        host = ctk.CTkScrollableFrame(wrap, fg_color="transparent")
        host.grid(row=1, column=0, sticky="nsew")
        empty = ctk.CTkLabel(
            host,
            text="Nada aqui aun.",
            font=theme.FONT_SMALL,
            text_color=theme.TEXT_MUTED,
            anchor="w",
        )
        empty.pack(anchor="w", pady=4)
        wrap._host = host  # type: ignore[attr-defined]
        wrap._empty = empty  # type: ignore[attr-defined]
        return wrap

    def _count_chip(self, parent, title: str, value: str, color: str) -> ctk.CTkFrame:
        chip = ctk.CTkFrame(parent, fg_color=theme.GLASS_INPUT, corner_radius=8, border_width=1, border_color=theme.GLASS_BORDER)
        inner = ctk.CTkFrame(chip, fg_color="transparent")
        inner.pack(padx=10, pady=6)
        ctk.CTkLabel(inner, text=title, font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED).pack(anchor="w")
        lab = ctk.CTkLabel(inner, text=value, font=theme.FONT_TITLE, text_color=color)
        lab.pack(anchor="w")
        chip._value = lab  # type: ignore[attr-defined]
        return chip

    def _refresh_status(self) -> None:
        jwt_ok = is_configured(ROOT, self.config)
        cloud = "G Core listo" if jwt_ok else "Falta JWT en config/ledger_bridge.jwt"
        self.status_label.configure(text="Sage: " + TEST_COMPANY + "  ·  " + cloud)

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
        self._set_live("En espera.")
        self.cycle_label.configure(text="Aun no consulta.")
        self._paint_counts()
        self._paint_cards()
        self._save_log_state()

    def _set_live(self, text: str) -> None:
        self.live_label.configure(text=text)

    def _paint_counts(self) -> None:
        self.count_ok._value.configure(text=str(self._n_ok))  # type: ignore[attr-defined]
        self.count_skip._value.configure(text=str(self._n_skip))  # type: ignore[attr-defined]
        self.count_err._value.configure(text=str(getattr(self, "_pending_count", 0)))  # type: ignore[attr-defined]

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

    def _paint_column(self, column: ctk.CTkFrame, payloads: list[dict], empty_text: str, groups=None) -> None:
        panel = getattr(column, "_history_panel", None)
        if panel is None:
            panel = column._history_panel = HistoryPanel(column._host)
        panel.update(groups if groups is not None else [("Historial", payloads)])

    def _paint_cards(self) -> None:
        ok_cards = [c for c in self._cards if c.get("ok")]
        err_cards = [c for c in self._cards if not c.get("ok")]
        self._paint_column(self.ok_host, ok_cards, "Sin facturas cargadas.")
        pending = pending_cards(ROOT)
        self._paint_column(self.err_host, err_cards, "Sin registros.", groups=failure_groups(self._cards, pending))
        self._pending_count = len(pending)
        self.count_err._value.configure(text=str(len(pending)))
        self.retry_btn.configure(text=f"Reenviar fallidas ({len(pending)})")

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

    def on_toggle_auto(self) -> None:
        self._auto_on = not self._auto_on
        self.auto_btn.configure(text="Automatico: ON" if self._auto_on else "Automatico: OFF")
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
            self.cycle_label.configure(text="Terminando consulta en curso; no se programaran mas." if self._auto_busy else "Automatico apagado. Sin consultas programadas.")

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
        self._auto_busy = True
        self._set_live("Consultando y procesando pendientes...")
        self.cycle_label.configure(text="Consulta en curso.")

        def worker() -> None:
            import time

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
            summary = summary.split(" · proxima en ")[0].split(" · reintento en ")[0] + " · Automatico apagado"
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
            show_error(self, "Enviar fallidas", "Pon Automatico OFF antes de reenviar.")
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

    def on_probe_items(self) -> None:
        if self._sage_busy:
            return
        if self._auto_on:
            show_error(self, "Probar items", "Pon Automatico OFF antes de probar.")
            return
        try:
            if not ask_confirm(
                self,
                "Probar items",
                "Sage tiene que estar abierto en LYL 2025-2026.\n\n"
                "Esto NO escribe facturas ni crea items.\n"
                "Solo comprueba que S-020, P-001 y N-001 existan en Sage.",
            ):
                return
        except Exception as exc:
            show_error(self, "Probar items", str(exc))
            return
        self._set_sage_btns(True)
        self._log("Probando match de items en Sage...")

        def worker() -> None:
            try:
                summary = probe_sage_items(ROOT, on_log=self._log_from_thread)
                self.after(0, self._on_probe_done, True, summary)
            except Exception as exc:
                self.after(0, self._on_probe_done, False, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_probe_done(self, ok: bool, message: str) -> None:
        self._set_sage_btns(False)
        self._log(message)
        if ok:
            show_info(self, "Probar items", message)
        else:
            show_error(self, "Probar items", message)

    def on_full_probe(self) -> None:
        if self._sage_busy:
            return
        if self._auto_on:
            show_error(self, "Prueba full", "Pon Automatico OFF antes de probar.")
            return
        try:
            if not ask_confirm(
                self,
                "Prueba full de factura",
                "Sage tiene que estar abierto en LYL 2025-2026.\n\n"
                "Crea UNA factura de prueba con:\n"
                "- cliente nuevo AHT*\n"
                "- 3 items que YA existen: S-020, P-001, N-001\n"
                "- 3 lineas, 2 con descuento\n"
                "- cuenta ventas 4001 y descuento 4031 (Rio)\n"
                "- ITBMS 7%\n\n"
                "No crea items nuevos. Si no hay match, Fail 16.\n"
                "Si Sage la guarda, borra SOLO esa factura AH*-99xxx.\n"
                "El cliente AHT* queda. Escribe un reporte en logs/.",
            ):
                return
        except Exception as exc:
            show_error(self, "Prueba full", str(exc))
            return
        self._set_sage_btns(True)
        self._log("Prueba full Sage: cliente nuevo + match S-020/P-001/N-001 + descuento + cuentas...")

        def worker() -> None:
            try:
                summary = run_full_sage_probe(ROOT, on_log=self._log_from_thread)
                self.after(0, self._on_full_probe_done, True, summary)
            except Exception as err:
                self.after(0, self._on_full_probe_done, False, str(err))

        threading.Thread(target=worker, daemon=True).start()

    def _on_full_probe_done(self, ok: bool, message: str) -> None:
        self._set_sage_btns(False)
        self._log(message)
        if ok:
            show_info(self, "Prueba full", message)
        else:
            show_error(self, "Prueba full", message)

    def on_reopen_8012(self) -> None:
        if self._sage_busy:
            return
        if self._auto_on:
            show_error(self, "Rehacer 12/13", "Pon Automatico OFF.")
            return
        try:
            if not ask_confirm(
                self,
                "Rehacer *0008012 y *0008013",
                "Borra en Sage SOLO las facturas AH que terminan en -08012 y -08013\n"
                "(INDUSTRIAS METALICAS CARMONA y REFRIPROYECTOS).\n\n"
                "No toca 8011 ni el resto del lote.\n"
                "Las quita de enviadas para que Automatico las vuelva a cargar\n"
                "completas (2 items + descuento 4031 + ITBMS).\n\n"
                "Sage abierto en LYL 2025-2026. Extractor ya actualizado con SKU.",
            ):
                return
        except Exception as exc:
            show_error(self, "Rehacer 12/13", str(exc))
            return
        self._set_sage_btns(True)
        self._log("Rehaciendo AH*-08012 y AH*-08013...")

        def worker() -> None:
            try:
                stats = delete_ah_invoices(
                    ROOT,
                    on_log=self._log_from_thread,
                    only_seq=["08012", "08013"],
                )
                msg = (
                    "Borradas "
                    + str(stats.get("deleted") or 0)
                    + ". Enviadas quitadas "
                    + str(stats.get("forgotten") or 0)
                    + ". Pon Automatico ON."
                )
                self.after(0, self._on_reopen_done, True, msg)
            except Exception as exc:
                self.after(0, self._on_reopen_done, False, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_reopen_done(self, ok: bool, message: str) -> None:
        self._set_sage_btns(False)
        self._log(message)
        if ok:
            show_info(self, "Rehacer 12/13", message)
        else:
            show_error(self, "Rehacer 12/13", message)

    def on_delete_ah(self) -> None:
        if self._sage_busy:
            return
        if self._auto_on:
            show_error(self, "Borrar AH", "Pon Automatico OFF antes de borrar.")
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
