from __future__ import annotations

import json
import os
import sys
import threading
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
from app.components import btn, glass_card
from app.dialogs import ask_confirm, show_error, show_info
from app.user_log import classify
from src.app_update import restart_autohub, run_update
from src.ledger_bridge import base_url, is_configured
from src.sage_sdk_write import TEST_COMPANY, authorize_sage_access
from src.session_log import append as append_session_log
from src.session_log import open_folder as open_logs_folder

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
        self.geometry("1020x680")
        self.minsize(900, 580)
        self.configure(fg_color=theme.BG_DARK)

        self.config = _load_config()
        self._auto_on = False
        self._auto_busy = False
        self._idle_idx = 0
        self._log_lock = threading.Lock()
        self._ev_q: deque[tuple[str, str]] = deque(maxlen=400)
        self._n_ok = 0
        self._n_err = 0
        self._n_skip = 0
        self._ok_lines: deque[str] = deque(maxlen=12)
        self._err_lines: deque[str] = deque(maxlen=12)
        self._current = ""

        if LOGO_ICO.exists():
            try:
                self.iconbitmap(default=str(LOGO_ICO))
            except Exception:
                pass

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main()
        self.after(150, self._flush_logs)
        self._log("Sistema listo")
        self._refresh_status()

    def _build_sidebar(self) -> None:
        sidebar = glass_card(self, radius=0, glow=False)
        sidebar.configure(fg_color=theme.BG_SIDEBAR, border_width=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.configure(width=176)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=10, pady=(12, 10))
        logo = ctk.CTkFrame(brand, width=28, height=28, fg_color=theme.ACCENT, corner_radius=6)
        logo.pack(side="left")
        logo.pack_propagate(False)
        ctk.CTkLabel(logo, text="AH", font=("Segoe UI", 11, "bold"), text_color="white").place(
            relx=0.5, rely=0.5, anchor="center"
        )
        ctk.CTkLabel(brand, text="Auto-Hub", font=theme.FONT_LOGO, text_color=theme.TEXT_PRIMARY).pack(
            side="left", padx=(8, 0)
        )

        self._nav_log = ctk.CTkButton(
            sidebar,
            text="  Que esta pasando",
            anchor="w",
            height=32,
            corner_radius=theme.BENTO_RADIUS_SM,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            text_color="white",
            font=theme.FONT_BODY,
            command=lambda: None,
        )
        self._nav_log.pack(fill="x", padx=8, pady=1)

        ctk.CTkButton(
            sidebar,
            text="  Actualizar app",
            anchor="w",
            height=32,
            corner_radius=theme.BENTO_RADIUS_SM,
            fg_color="transparent",
            hover_color=theme.GLASS_BG_HOVER,
            text_color=theme.TEXT_SECONDARY,
            font=theme.FONT_BODY,
            command=self.on_update_app,
        ).pack(fill="x", padx=8, pady=1)

        ctk.CTkButton(
            sidebar,
            text="  Ver logs",
            anchor="w",
            height=32,
            corner_radius=theme.BENTO_RADIUS_SM,
            fg_color="transparent",
            hover_color=theme.GLASS_BG_HOVER,
            text_color=theme.TEXT_SECONDARY,
            font=theme.FONT_BODY,
            command=self.on_open_logs,
        ).pack(fill="x", padx=8, pady=1)

        ctk.CTkLabel(
            sidebar,
            text="LYL 2025-2026",
            text_color=theme.TEXT_MUTED,
            font=theme.FONT_SMALL,
        ).pack(side="bottom", anchor="w", padx=12, pady=(0, 12))

    def _build_main(self) -> None:
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=12, pady=12)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(3, weight=1)

        self.status_label = ctk.CTkLabel(
            main,
            text="Sage y G Core",
            font=theme.FONT_HEADING,
            text_color=theme.TEXT_PRIMARY,
            anchor="w",
        )
        self.status_label.grid(row=0, column=0, sticky="ew")

        actions = glass_card(main, glow=True)
        actions.grid(row=1, column=0, sticky="ew", pady=(10, 10))
        inner = ctk.CTkFrame(actions, fg_color="transparent")
        inner.pack(fill="x", padx=theme.BENTO_PAD, pady=theme.BENTO_PAD)

        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x")
        self.auth_btn = btn(
            row,
            text="Conectar Sage",
            variant="secondary",
            width=140,
            height=theme.BTN_HEIGHT_LG,
            command=self.on_authorize_sage,
        )
        self.auth_btn.pack(side="left")
        self.auto_btn = btn(
            row,
            text="Automatico: OFF",
            variant="primary",
            width=160,
            height=theme.BTN_HEIGHT_LG,
            command=self.on_toggle_auto,
        )
        self.auto_btn.pack(side="left", padx=(8, 0))
        btn(row, text="Limpiar", variant="ghost", width=90, height=theme.BTN_HEIGHT_LG, command=self._clear_log).pack(
            side="right"
        )

        ctk.CTkLabel(
            inner,
            text="Sage en LYL 2025-2026. Conectar Sage una vez. Automatico ON. Solo desde el 3 sep 2026 entran a Sage. Arriba ves si consulta. A la izquierda las que si cargaron. A la derecha los fallos. Las viejas solo suman en Omitidas.",
            font=theme.FONT_SMALL,
            text_color=theme.TEXT_SECONDARY,
            wraplength=740,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

        now = glass_card(main)
        now.grid(row=2, column=0, sticky="ew", pady=(0, 10))
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
        self.count_err = self._count_chip(counts, "Fallos", "0", theme.DANGER)
        self.count_ok.pack(side="left")
        self.count_skip.pack(side="left", padx=(8, 0))
        self.count_err.pack(side="left", padx=(8, 0))

        lists = ctk.CTkFrame(main, fg_color="transparent")
        lists.grid(row=3, column=0, sticky="nsew")
        lists.grid_columnconfigure(0, weight=1)
        lists.grid_columnconfigure(1, weight=1)
        lists.grid_rowconfigure(0, weight=1)

        self.ok_card = self._list_card(lists, "Cargadas en Sage", theme.SUCCESS)
        self.ok_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.err_card = self._list_card(lists, "Fallos", theme.DANGER)
        self.err_card.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.ok_box = self.ok_card._box  # type: ignore[attr-defined]
        self.err_box = self.err_card._box  # type: ignore[attr-defined]

    def _count_chip(self, parent, title: str, value: str, color: str) -> ctk.CTkFrame:
        chip = ctk.CTkFrame(parent, fg_color=theme.GLASS_INPUT, corner_radius=8, border_width=1, border_color=theme.GLASS_BORDER)
        inner = ctk.CTkFrame(chip, fg_color="transparent")
        inner.pack(padx=10, pady=6)
        ctk.CTkLabel(inner, text=title, font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED).pack(anchor="w")
        lab = ctk.CTkLabel(inner, text=value, font=theme.FONT_TITLE, text_color=color)
        lab.pack(anchor="w")
        chip._value = lab  # type: ignore[attr-defined]
        return chip

    def _list_card(self, parent, title: str, accent: str) -> ctk.CTkFrame:
        card = glass_card(parent)
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=theme.BENTO_PAD, pady=(theme.BENTO_PAD, 4))
        ctk.CTkLabel(head, text=title, font=theme.FONT_HEADING, text_color=accent, anchor="w").pack(side="left")
        box = ctk.CTkTextbox(
            card,
            font=theme.FONT_SMALL,
            corner_radius=theme.BENTO_RADIUS_SM,
            wrap="word",
            fg_color=theme.GLASS_INPUT,
            border_color=theme.GLASS_BORDER,
        )
        box.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        box.configure(state="disabled")
        card._box = box  # type: ignore[attr-defined]
        return card

    def _refresh_status(self) -> None:
        jwt_ok = is_configured(ROOT, self.config)
        cloud = "G Core listo" if jwt_ok else "Falta JWT en config/ledger_bridge.jwt"
        self.status_label.configure(text="Sage: " + TEST_COMPANY + "  ·  " + cloud)

    def _clear_log(self) -> None:
        self._n_ok = 0
        self._n_err = 0
        self._n_skip = 0
        self._ok_lines.clear()
        self._err_lines.clear()
        self._current = ""
        self._set_live("En espera.")
        self.cycle_label.configure(text="Aun no consulta.")
        self._paint_counts()
        self._paint_list(self.ok_box, self._ok_lines)
        self._paint_list(self.err_box, self._err_lines)

    def _set_live(self, text: str) -> None:
        self.live_label.configure(text=text)

    def _paint_counts(self) -> None:
        self.count_ok._value.configure(text=str(self._n_ok))  # type: ignore[attr-defined]
        self.count_skip._value.configure(text=str(self._n_skip))  # type: ignore[attr-defined]
        self.count_err._value.configure(text=str(self._n_err))  # type: ignore[attr-defined]

    def _paint_list(self, box: ctk.CTkTextbox, lines: deque[str]) -> None:
        box.configure(state="normal")
        box.delete("1.0", "end")
        if lines:
            box.insert("1.0", "\n".join(lines))
        box.configure(state="disabled")

    def _log(self, msg: str) -> None:
        self._log_from_thread(msg)

    def _log_from_thread(self, msg: str) -> None:
        ev = classify(msg)
        if not ev:
            return
        try:
            append_session_log(ROOT, ev[0], ev[1])
        except Exception:
            pass
        with self._log_lock:
            self._ev_q.append(ev)

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

        ok_changed = False
        err_changed = False
        counts_changed = False
        stamp = datetime.now().strftime("%H:%M:%S")
        live = ""
        for kind, text in events:
            if kind == "status":
                live = text
            elif kind == "load":
                self._current = text
                live = "Cargando " + text
            elif kind == "ok":
                line = stamp + "  " + (self._current or text)
                if not self._ok_lines or self._ok_lines[-1] != line:
                    self._ok_lines.append(line)
                    self._n_ok += 1
                    ok_changed = True
                    counts_changed = True
                live = "Cargada: " + (self._current or text)
                self._current = ""
            elif kind == "err":
                line = stamp + "  " + text
                if not self._err_lines or self._err_lines[-1] != line:
                    self._err_lines.append(line)
                    self._n_err += 1
                    err_changed = True
                    counts_changed = True
                live = "Fallo: " + text
                self._current = ""
            elif kind == "skip":
                n = 1
                for part in text.split():
                    if part.isdigit():
                        n = int(part)
                        break
                self._n_skip += n
                counts_changed = True
                live = text
        if live:
            self._set_live(live)
        if counts_changed:
            self._paint_counts()
        if ok_changed:
            self._paint_list(self.ok_box, self._ok_lines)
        if err_changed:
            self._paint_list(self.err_box, self._err_lines)

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
            self._schedule_auto(immediate=True)
        else:
            self._log("Modo automatico OFF")

    def _schedule_auto(self, immediate: bool = False) -> None:
        if not self._auto_on:
            return
        delays = (12000, 20000, 30000, 45000)
        delay = 400 if immediate else delays[min(self._idle_idx, len(delays) - 1)]
        self.after(delay, self._auto_tick)

    def _auto_tick(self) -> None:
        if not self._auto_on:
            return
        if self._auto_busy:
            return
        self._auto_busy = True

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
            self._idle_idx = 0
        elif stats and (stats.get("sent") or stats.get("failed") or stats.get("skipped")):
            self._idle_idx = 0
        else:
            self._idle_idx = min(self._idle_idx + 1, 3)
        self._set_cycle_summary(stats, error, elapsed)
        self._schedule_auto()

    def _set_cycle_summary(self, stats: dict | None, error: str, elapsed: float) -> None:
        hhmm = datetime.now().strftime("%H:%M")
        sec = str(round(elapsed, 1)) + " s"
        if error:
            summary = "Ultima consulta " + hhmm + " · " + sec + " · error"
        elif not stats or not (stats.get("sent") or stats.get("failed") or stats.get("skipped")):
            summary = "Ultima consulta " + hhmm + " · " + sec + " · cola vacia"
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
            summary = "Ultima consulta " + hhmm + " · " + sec + " · " + ", ".join(bits)
        self.cycle_label.configure(text=summary)

    def on_open_logs(self) -> None:
        try:
            open_logs_folder(ROOT)
        except Exception as exc:
            show_error(self, "Logs", str(exc))

    def on_authorize_sage(self) -> None:
        if not ask_confirm(
            self,
            "Conectar Sage",
            "1. Abre Sage 50\n"
            "2. Entra a LYL CONSTRUCTIONS SUPPLY INC 2025-2026\n"
            "3. Pulsa Confirmar y, cuando Sage pregunte, elige Always Allow",
        ):
            return
        self._log("Conectando con Sage 50 — esperando Always Allow...")
        self.auth_btn.configure(state="disabled")

        def worker() -> None:
            try:
                authorize_sage_access(ROOT, on_log=self._log_from_thread)
                self.after(0, self._on_sage_done, True, "OK — Sage conectado.")
            except Exception as exc:
                self.after(0, self._on_sage_done, False, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_sage_done(self, ok: bool, message: str) -> None:
        self.auth_btn.configure(state="normal")
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
