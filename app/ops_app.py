from __future__ import annotations

import json
import os
import sys
import threading
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
from app.user_log import friendly_log
from src.app_update import restart_autohub, run_update
from src.ledger_bridge import base_url, is_configured
from src.sage_sdk_write import TEST_COMPANY, authorize_sage_access

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
        self.geometry("980x640")
        self.minsize(860, 540)
        self.configure(fg_color=theme.BG_DARK)

        self.config = _load_config()
        self._auto_on = False
        self._auto_busy = False
        self._log_buffer: list[str] = []

        if LOGO_ICO.exists():
            try:
                self.iconbitmap(default=str(LOGO_ICO))
            except Exception:
                pass

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main()
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
        main.grid_rowconfigure(2, weight=1)

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
        btn(row, text="Limpiar log", variant="ghost", width=110, height=theme.BTN_HEIGHT_LG, command=self._clear_log).pack(
            side="right"
        )

        ctk.CTkLabel(
            inner,
            text="Abre Sage en LYL 2025-2026. Conectar Sage (Always Allow una vez). Automatico ON pide facturas a G Core. Solo 2025 en adelante entran a Sage; las viejas se marcan en la nube y no se cargan.",
            font=theme.FONT_SMALL,
            text_color=theme.TEXT_SECONDARY,
            wraplength=720,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

        log_shell = glass_card(main)
        log_shell.grid(row=2, column=0, sticky="nsew")
        log_shell.grid_columnconfigure(0, weight=1)
        log_shell.grid_rowconfigure(1, weight=1)
        head = ctk.CTkFrame(log_shell, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=theme.BENTO_PAD, pady=(theme.BENTO_PAD, 6))
        ctk.CTkLabel(
            head,
            text="Que esta pasando",
            font=theme.FONT_HEADING,
            text_color=theme.TEXT_PRIMARY,
        ).pack(side="left")
        self.log_text = ctk.CTkTextbox(
            log_shell,
            font=theme.FONT_LOG,
            corner_radius=theme.BENTO_RADIUS_SM,
            wrap="word",
            fg_color=theme.GLASS_INPUT,
            border_color=theme.GLASS_BORDER,
        )
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

    def _refresh_status(self) -> None:
        jwt_ok = is_configured(ROOT, self.config)
        cloud = "G Core listo" if jwt_ok else "Falta JWT en config/ledger_bridge.jwt"
        self.status_label.configure(text="Sage: " + TEST_COMPANY + "  ·  " + cloud)

    def _clear_log(self) -> None:
        self._log_buffer = []
        self.log_text.delete("1.0", "end")

    def _log(self, msg: str) -> None:
        shown = friendly_log(msg)
        if shown is None:
            return
        line = datetime.now().strftime("%H:%M:%S") + "  " + shown + "\n"
        self._log_buffer.append(line)
        self.log_text.insert("end", line)
        self.log_text.see("end")

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
            self._schedule_auto()
        else:
            self._log("Modo automatico OFF")

    def _schedule_auto(self) -> None:
        if self._auto_on:
            self.after(12000, self._auto_tick)

    def _auto_tick(self) -> None:
        if not self._auto_on:
            return
        if self._auto_busy:
            self._schedule_auto()
            return
        self._auto_busy = True

        def worker() -> None:
            try:
                from src.extractor_inbox import process_extractor_outbox

                stats = process_extractor_outbox(
                    ROOT,
                    self.config,
                    on_log=lambda msg: self.after(0, self._log, msg),
                )
                self.after(0, self._on_auto_cycle, stats, "")
            except Exception as exc:
                self.after(0, self._on_auto_cycle, None, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_auto_cycle(self, stats: dict | None, error: str) -> None:
        self._auto_busy = False
        if error:
            self._log("ERROR automatico: " + error)
        elif stats and (stats.get("sent") or stats.get("failed") or stats.get("skipped")):
            self._log(
                "Ciclo Extractor: enviadas="
                + str(stats.get("sent", 0))
                + " omitidas="
                + str(stats.get("skipped", 0))
                + " error="
                + str(stats.get("failed", 0))
            )
        self._schedule_auto()

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
                authorize_sage_access(ROOT, on_log=lambda msg: self.after(0, self._log, msg))
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
            def log(msg: str) -> None:
                self.after(0, self._log, msg)

            try:
                run_update(ROOT, on_log=log)
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
