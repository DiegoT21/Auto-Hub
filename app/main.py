from __future__ import annotations

import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
import pandas as pd
from CTkTable import CTkTable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import theme
from app.components import btn, card, glass_card, bento_tile, section_title, stat_chip
from app.data_editor import EditableDataGrid
from app.db_browser import DbBrowserPanel
from app.db_connection_dialog import ConnectionBar, DatabaseConnectionDialog
from app.dialogs import ask_confirm, show_error, show_info, show_warning
from app.glass_bg import GlassBackground
from app.menu_bar import AppMenuBar
from app.preview_view import PreviewPanel
from app.workflow_bar import WorkflowBar
from src.csv_import import (
    apply_column_mapping,
    detect_column_mapping,
    normalize_sage_columns,
    sage_dataframe_to_raw_rows,
)
from src.connections import (
    DEFAULT_CONNECTIONS_PATH,
    apply_profile_to_config,
    connection_summary,
    get_connection,
    load_connections,
    save_config,
)
from src.db import load_config
from src.export_csv import export_csv, export_rejected
from src.excel_automation import run_excel_automation
from src.extract import extract_invoices, extract_invoices_by_ids, save_watermark
from src.extract_pdf import extract_invoices_from_pdfs
from src.sage_excel import (
    copy_empty_workbook,
    create_sage_template,
    dataframe_to_invoice,
    load_simulator_config,
)
from src.app_update import run_update, restart_autohub
from src.sage_sdk_write import (
    TEST_COMPANY,
    TEST_CUSTOMER_ID,
    load_sika_test_rows,
    run_test_company_write,
)
from src.transform import transform_rows
from src.validate import validate_rows

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

LOGO_PNG = ROOT / "assets" / "autohub_logo.png"
LOGO_ICO = ROOT / "assets" / "autohub.ico"
APP_ID = "Posper.AutoHub.1"
CONFIG_PATH = Path(os.environ.get("AUTOHUB_CONFIG", ROOT / "config" / "config.json"))


def _python_exe() -> Path:
    exe = Path(sys.executable)
    if exe.stem.lower() == "pythonw":
        return exe.with_name("python.exe")
    return exe


def _set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def _ensure_local_database() -> None:
    db = ROOT / "data" / "pskloud_demo.db"
    if db.exists():
        return
    try:
        import subprocess

        subprocess.run(
            [str(_python_exe()), str(ROOT / "scripts" / "seed_database.py")],
            cwd=ROOT,
            check=False,
        )
    except Exception:
        pass


class AutoHubApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Auto-Hub")
        self.geometry("1280x800")
        self.minsize(1100, 720)
        self.configure(fg_color=theme.BG_DARK)

        self._bg = GlassBackground(self)
        self._bg.place_fill()

        self.config = load_config(CONFIG_PATH)
        self.connections_path = DEFAULT_CONNECTIONS_PATH
        self._sync_active_connection()
        self.sim_config = load_simulator_config(ROOT)
        self.last_csv: Path | None = None
        self.last_excel: Path | None = None
        self.current_invoice: dict | None = None
        self.excel_open = False
        self.valid_rows: list[dict] = []
        self.rejected_rows: list[dict] = []
        self._dirty = False
        self._import_warnings: list[str] = []
        self._pdf_meta: dict = {}
        self._pending_frame: pd.DataFrame = pd.DataFrame()
        self._import_source = ""
        self._current_step = 1
        self._step2_mode = "preview"
        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        self._recent_jobs: list[tuple[str, str, str]] = []
        self._logo_image: ctk.CTkImage | None = None

        self._apply_branding()
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_menu_bar()
        self._build_sidebar()
        self._build_main()
        self._go_step(1)
        self._add_job("Sistema listo", "ok")

    def _apply_branding(self) -> None:
        if LOGO_ICO.exists():
            try:
                self.iconbitmap(default=str(LOGO_ICO))
            except Exception:
                pass
        if LOGO_PNG.exists():
            try:
                import tkinter as tk
                from PIL import Image

                self._window_icon = tk.PhotoImage(file=str(LOGO_PNG))
                self.iconphoto(True, self._window_icon)

                pil_img = Image.open(LOGO_PNG)
                self._logo_image = ctk.CTkImage(
                    light_image=pil_img,
                    dark_image=pil_img,
                    size=(40, 40),
                )
            except Exception:
                self._logo_image = None

        def refresh_shortcut() -> None:
            try:
                import subprocess

                subprocess.run(
                    [str(_python_exe()), str(ROOT / "scripts" / "setup_branding.py")],
                    cwd=ROOT,
                    capture_output=True,
                    check=False,
                )
            except Exception:
                pass

        threading.Thread(target=refresh_shortcut, daemon=True).start()

    # ── Menu bar ────────────────────────────────────────────

    def _build_menu_bar(self) -> None:
        self.menu_bar = AppMenuBar(self, self._menu_commands())
        self.menu_bar.grid(row=0, column=0, columnspan=2, sticky="ew")

    def _menu_commands(self) -> dict:
        return {
            "import_pskloud": lambda: self._go_step(1),
            "import_pdf": self.on_extract_pdf,
            "import_csv": self.on_open_csv,
            "export_sage": self.on_export,
            "export_rejected": self.on_export_rejected,
            "open_output": self.on_open_output_folder,
            "revalidate": self.on_revalidate,
            "go_editor": self._menu_go_editor,
            "view_step1": lambda: self._go_step(1),
            "view_step2": lambda: self._go_step(2),
            "view_step3": lambda: self._go_step(3),
            "view_activity": lambda: self._show_activity(True),
            "reset_db": self.on_reset,
            "open_excel_template": self.on_prepare_excel,
            "db_connections": self.on_db_connections,
            "update_app": self.on_update_app,
        }

    def _menu_go_editor(self) -> None:
        if self._pending_frame.empty and self.editor.dataframe.empty:
            show_warning(self, "Sin datos", "Importa facturas primero desde el menu Importar.")
            return
        if not self.editor.dataframe.empty:
            self._show_step2_mode("editor")
        else:
            self._show_step2_mode("preview")
        self._go_step(2)

    def _sync_active_connection(self) -> None:
        data = load_connections(self.connections_path)
        profile = get_connection(data)
        if profile:
            self.config = apply_profile_to_config(self.config, profile, ROOT)
            save_config(self.config, CONFIG_PATH)

    def on_db_connections(self) -> None:
        def on_saved() -> None:
            self.config = load_config(CONFIG_PATH)
            self._on_connection_changed(reload_invoices=False)

        DatabaseConnectionDialog(
            self,
            root=ROOT,
            config_path=CONFIG_PATH,
            connections_path=self.connections_path,
            on_saved=on_saved,
        )

    def _on_connection_changed(self, *, reload_invoices: bool = False) -> None:
        if hasattr(self, "connection_bar"):
            self.connection_bar.refresh()
        if hasattr(self, "db_browser"):
            self.db_browser.config = self.config
            if reload_invoices:
                self.db_browser.refresh_async()
        profile = get_connection(load_connections(self.connections_path))
        if profile:
            summary = connection_summary(profile)
            self._log(f"Conexion activa: {summary}")
            self._add_job(f"BD: {profile.get('name', '')}", "ok")
        self._update_workflow_status()

    def on_update_app(self) -> None:
        if not ask_confirm(
            self,
            "Actualizar Auto-Hub",
            "Va a bajar los cambios publicados y reiniciar la app.\n"
            "No toca contraseñas ni app_id.txt.\n\n"
            "Sage puede seguir abierto.",
        ):
            return
        self._add_job("Actualizar app", "running")
        self._log("Actualizando Auto-Hub...")

        def worker() -> None:
            lines: list[str] = []

            def log(msg: str) -> None:
                lines.append(msg)
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
            self._add_job("Actualizar fallo", "error")
            show_error(self, "Actualizar", message)
            return
        self._add_job("Auto-Hub actualizado", "ok")
        show_info(self, "Actualizar", message)
        try:
            restart_autohub(ROOT)
        except Exception as exc:
            self._log("No se pudo reiniciar solo: " + str(exc))
            return
        self.after(400, self.destroy)

    def on_open_output_folder(self) -> None:
        out = ROOT / self.config["output"]["output_dir"]
        out.mkdir(parents=True, exist_ok=True)
        os.startfile(str(out))

    # ── Layout ──────────────────────────────────────────────

    def _build_sidebar(self) -> None:
        sidebar = glass_card(self, radius=0, glow=False)
        sidebar.configure(fg_color=theme.BG_SIDEBAR, border_width=0)
        sidebar.grid(row=1, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.configure(width=228)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=16, pady=(24, 20))
        if self._logo_image is not None:
            ctk.CTkLabel(brand, text="", image=self._logo_image).pack(side="left")
        else:
            logo = ctk.CTkFrame(brand, width=40, height=40, fg_color=theme.ACCENT, corner_radius=10)
            logo.pack(side="left")
            logo.pack_propagate(False)
            ctk.CTkLabel(logo, text="AH", font=("Segoe UI", 16, "bold"), text_color="white").place(
                relx=0.5, rely=0.5, anchor="center"
            )
        ctk.CTkLabel(brand, text="Auto-Hub", font=theme.FONT_LOGO, text_color=theme.TEXT_PRIMARY).pack(
            side="left", padx=(10, 0)
        )

        nav_items = [
            ("step1", "1. Importar"),
            ("step2", "2. Revisar"),
            ("step3", "3. Carga Sage"),
        ]
        for key, label in nav_items:
            step_num = int(key[-1])
            nav_btn = ctk.CTkButton(
                sidebar,
                text=f"  {label}",
                anchor="w",
                height=44,
                corner_radius=theme.BENTO_RADIUS_SM,
                fg_color="transparent",
                hover_color=theme.GLASS_BG_HOVER,
                text_color=theme.TEXT_SECONDARY,
                font=theme.FONT_BODY,
                command=lambda n=step_num: self._go_step(n),
            )
            nav_btn.pack(fill="x", padx=12, pady=2)
            self._nav_buttons[key] = nav_btn

        ctk.CTkButton(
            sidebar,
            text="  Actividad / Log",
            anchor="w",
            height=44,
            corner_radius=theme.BENTO_RADIUS_SM,
            fg_color="transparent",
            hover_color=theme.GLASS_BG_HOVER,
            text_color=theme.TEXT_MUTED,
            font=theme.FONT_BODY,
            command=lambda: self._show_activity(True),
        ).pack(fill="x", padx=12, pady=(12, 2))

        ctk.CTkButton(
            sidebar,
            text="  Actualizar app",
            anchor="w",
            height=44,
            corner_radius=theme.BENTO_RADIUS_SM,
            fg_color="transparent",
            hover_color=theme.GLASS_BG_HOVER,
            text_color=theme.TEXT_SECONDARY,
            font=theme.FONT_BODY,
            command=self.on_update_app,
        ).pack(fill="x", padx=12, pady=(8, 2))

        ctk.CTkLabel(sidebar, text="Support", text_color=theme.TEXT_MUTED, font=theme.FONT_SMALL).pack(
            side="bottom", anchor="w", padx=20, pady=(0, 20)
        )

    def _build_main(self) -> None:
        self.main = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self.main.grid(row=1, column=1, sticky="nsew")
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(self.main, fg_color="transparent", height=56)
        top.grid(row=0, column=0, sticky="ew", padx=24, pady=(16, 0))
        ctk.CTkLabel(top, text="Auto-Hub", font=theme.FONT_HEADING, text_color=theme.TEXT_PRIMARY).pack(
            side="left"
        )

        self.status_badge = ctk.CTkLabel(
            top,
            text="● Online",
            font=theme.FONT_SMALL,
            text_color=theme.SUCCESS,
            fg_color=theme.GLASS_BG,
            corner_radius=20,
            border_width=1,
            border_color=theme.GLASS_BORDER,
            padx=12,
            pady=4,
        )
        self.status_badge.pack(side="right")

        wf_wrap = ctk.CTkFrame(self.main, fg_color="transparent")
        wf_wrap.grid(row=1, column=0, sticky="ew", padx=24, pady=(8, 0))
        self.workflow_bar = WorkflowBar(wf_wrap, on_step=self._go_step)
        self.workflow_bar.pack(fill="x")

        self.pages = ctk.CTkFrame(self.main, fg_color="transparent")
        self.pages.grid(row=2, column=0, sticky="nsew", padx=16, pady=16)
        self.pages.grid_columnconfigure(0, weight=1)
        self.pages.grid_rowconfigure(0, weight=1)

        self.page_frames: dict[str, ctk.CTkFrame] = {}
        for name in ("step1", "step2", "step3", "activity"):
            frame = ctk.CTkFrame(self.pages, fg_color="transparent")
            self.page_frames[name] = frame

        self._build_step1()
        self._build_step2()
        self._build_step3()
        self._build_activity()
        self.menu_bar.bind_shortcuts(self)

    def _show_activity(self, show: bool) -> None:
        if show:
            for key, frame in self.page_frames.items():
                frame.grid_forget()
            self.page_frames["activity"].grid(row=0, column=0, sticky="nsew")

    def _go_step(self, step: int) -> None:
        self._current_step = step
        self._show_activity(False)
        for key, frame in self.page_frames.items():
            if key == "activity":
                continue
            frame.grid_forget()
        self.page_frames[f"step{step}"].grid(row=0, column=0, sticky="nsew")
        for key, nav_btn in self._nav_buttons.items():
            if key == f"step{step}":
                nav_btn.configure(fg_color=theme.ACCENT, text_color="white")
            else:
                nav_btn.configure(fg_color="transparent", text_color=theme.TEXT_SECONDARY)
        self.workflow_bar.set_step(step)
        self._update_workflow_status()

    def _show_step2_mode(self, mode: str) -> None:
        self._step2_mode = mode
        if mode == "preview":
            self.step2_editor_wrap.pack_forget()
            self.preview_panel.pack(fill="both", expand=True)
        else:
            self.preview_panel.pack_forget()
            self.step2_editor_wrap.pack(fill="both", expand=True)
        self._update_workflow_status()

    def _update_workflow_status(self) -> None:
        has_data = not self.editor.dataframe.empty
        if not has_data and self._pending_frame.empty:
            self.workflow_bar.set_status("Paso 1 — Elige PsKloud, PDF o CSV y trae tus facturas.")
            return
        if self._current_step == 1:
            self.workflow_bar.set_status("Facturas importadas. Ve al paso 2 para revisar.")
        elif self._current_step == 2:
            inv = self.editor.selected_invoice
            lines = len(self.editor.dataframe) if has_data else len(self._pending_frame)
            inv_txt = f" · Factura: {inv}" if inv else ""
            if self._step2_mode == "preview":
                self.workflow_bar.set_status(f"Paso 2 — Revisa validacion ({lines} lineas).{inv_txt}")
            else:
                self.workflow_bar.set_status(f"Paso 2 — Edita datos y elige factura ({lines} lineas).{inv_txt}")
        else:
            inv = self.editor.selected_invoice or "—"
            self.workflow_bar.set_status(f"Paso 3 — Factura {inv}. Abre plantilla Sage y pulsa START.")

    # ── Paso 1: Importar ────────────────────────────────────

    def _build_step1(self) -> None:
        page = self.page_frames["step1"]
        page.grid_columnconfigure(0, weight=3)
        page.grid_columnconfigure(1, weight=1)
        page.grid_rowconfigure(1, weight=1)
        page.grid_rowconfigure(2, weight=1)
        page.grid_rowconfigure(3, weight=1)

        section_title(
            page,
            "Importar facturas",
            "Elige la fuente. Al importar avanzas automaticamente al paso 2.",
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, theme.BENTO_GAP))

        pskloud_shell = glass_card(page, glow=True)
        pskloud_shell.grid(row=1, column=0, rowspan=3, sticky="nsew", padx=(0, theme.BENTO_GAP // 2), pady=0)
        pskloud_shell.grid_columnconfigure(0, weight=1)
        pskloud_shell.grid_rowconfigure(1, weight=1)

        ph = ctk.CTkFrame(pskloud_shell, fg_color="transparent")
        ph.grid(row=0, column=0, sticky="ew", padx=theme.BENTO_PAD, pady=(theme.BENTO_PAD, 8))
        ph.grid_columnconfigure(1, weight=1)

        title_left = ctk.CTkFrame(ph, fg_color="transparent")
        title_left.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(title_left, text="🗄", font=("Segoe UI", 22)).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(
            title_left,
            text="PsKloud — Base de datos",
            font=theme.FONT_HEADING,
            text_color=theme.TEXT_PRIMARY,
        ).pack(side="left")

        self.connection_bar = ConnectionBar(
            ph,
            root=ROOT,
            config_path=CONFIG_PATH,
            connections_path=self.connections_path,
            on_changed=self._on_connection_changed,
        )
        self.connection_bar.grid(row=0, column=1, sticky="e")

        db_wrap = ctk.CTkFrame(pskloud_shell, fg_color="transparent")
        db_wrap.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        db_wrap.grid_columnconfigure(0, weight=1)
        db_wrap.grid_rowconfigure(0, weight=1)
        self.db_browser = DbBrowserPanel(
            db_wrap,
            self.config,
            ROOT,
            on_extract_selected=self._extract_db_selected,
        )
        self.db_browser.grid(row=0, column=0, sticky="nsew")

        pdf_tile = bento_tile(
            page,
            icon="📑",
            title="Facturas PDF",
            subtitle="Selecciona archivos PDF para leer e importar.",
            command=self.on_extract_pdf,
            compact=True,
        )
        pdf_tile.grid(row=1, column=1, sticky="nsew", padx=(theme.BENTO_GAP // 2, 0), pady=(0, theme.BENTO_GAP // 2))

        csv_tile = bento_tile(
            page,
            icon="📄",
            title="Archivo CSV",
            subtitle="Importa un CSV con columnas de factura.",
            command=self.on_open_csv,
            compact=True,
        )
        csv_tile.grid(row=2, column=1, sticky="nsew", padx=(theme.BENTO_GAP // 2, 0), pady=theme.BENTO_GAP // 2)

        sdk_tile = bento_tile(
            page,
            icon="🧪",
            title="Prueba SDK — 3 lineas Sika",
            subtitle="Carga *0000001 (Miguel del Rio) y enviala a la empresa de prueba.",
            command=self.on_load_sika_sdk_test,
            compact=True,
        )
        sdk_tile.grid(row=3, column=1, sticky="nsew", padx=(theme.BENTO_GAP // 2, 0))

    # ── Paso 2: Revisar ─────────────────────────────────────

    def _build_step2(self) -> None:
        page = self.page_frames["step2"]
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(0, weight=1)

        shell = glass_card(page)
        shell.grid(row=0, column=0, sticky="nsew")
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(0, weight=1)

        content = ctk.CTkFrame(shell, fg_color="transparent")
        content.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)

        self.preview_panel = PreviewPanel(
            content,
            on_load_editor=self._commit_preview_to_editor,
            on_export_rejected=self.on_export_rejected,
            on_back=lambda: self._go_step(1),
        )

        self.step2_editor_wrap = ctk.CTkFrame(content, fg_color="transparent")
        self.step2_editor_wrap.grid_columnconfigure(0, weight=1)
        self.step2_editor_wrap.grid_rowconfigure(1, weight=1)

        ed_header = ctk.CTkFrame(self.step2_editor_wrap, fg_color="transparent")
        ed_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ctk.CTkLabel(
            ed_header,
            text="Editar facturas",
            font=theme.FONT_HEADING,
            text_color=theme.TEXT_PRIMARY,
        ).pack(side="left")
        btn(
            ed_header,
            text="← Volver a validacion",
            variant="ghost",
            command=lambda: self._show_step2_mode("preview"),
        ).pack(side="right")

        self.editor = EditableDataGrid(
            self.step2_editor_wrap,
            on_change=self._on_editor_change,
            on_validate=self.on_revalidate,
            on_export=self.on_export,
        )
        self.editor.grid(row=1, column=0, sticky="nsew")
        self.editor.set_sage_columns(self.config["mapping"]["sage_columns"])

        ed_footer = ctk.CTkFrame(self.step2_editor_wrap, fg_color="transparent")
        ed_footer.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        btn(
            ed_footer,
            text="Continuar → Carga en Sage",
            variant="primary",
            command=self._continue_to_sage,
        ).pack(side="right")

        self._show_step2_mode("preview")

    # ── Paso 3: Carga Sage ──────────────────────────────────

    def _build_step3(self) -> None:
        page = self.page_frames["step3"]
        page.grid_columnconfigure(0, weight=1)
        page.grid_columnconfigure(1, weight=1)
        page.grid_rowconfigure(2, weight=1)

        section_title(
            page,
            "Carga en Sage 50",
            "Excel (START) o SDK real en la empresa de PRUEBA.",
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, theme.BENTO_GAP))

        stats = ctk.CTkFrame(page, fg_color="transparent")
        stats.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, theme.BENTO_GAP))
        for i in range(3):
            stats.grid_columnconfigure(i, weight=1)

        self._stat_data = stat_chip(stats, "Datos", "Sin cargar", color=theme.TEXT_MUTED)
        self._stat_data.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self._stat_excel = stat_chip(stats, "Plantilla", "No abierta", color=theme.TEXT_MUTED)
        self._stat_excel.grid(row=0, column=1, sticky="nsew", padx=6)
        self._stat_invoice = stat_chip(stats, "Factura", "—", color=theme.CYAN)
        self._stat_invoice.grid(row=0, column=2, sticky="nsew", padx=(6, 0))

        actions = glass_card(page, glow=True)
        actions.grid(row=2, column=0, sticky="nsew", padx=(0, theme.BENTO_GAP // 2), pady=0)
        actions.grid_rowconfigure(1, weight=1)

        inner = ctk.CTkFrame(actions, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=theme.BENTO_PAD, pady=theme.BENTO_PAD)

        self.excel_status = ctk.CTkLabel(
            inner,
            text="Listo para automatizar",
            font=theme.FONT_HEADING,
            text_color=theme.TEXT_PRIMARY,
        )
        self.excel_status.pack(anchor="w", pady=(0, 4))

        self.excel_path_label = ctk.CTkLabel(
            inner,
            text="Plantilla: (no abierta)",
            font=theme.FONT_SMALL,
            text_color=theme.TEXT_MUTED,
        )
        self.excel_path_label.pack(anchor="w", pady=(0, 16))

        prep_row = ctk.CTkFrame(inner, fg_color="transparent")
        prep_row.pack(fill="x", pady=(0, 12))

        btn(prep_row, text="← Editar", variant="ghost", command=lambda: self._go_step(2)).pack(
            side="left", padx=(0, 8)
        )
        btn(prep_row, text="Abrir plantilla", variant="secondary", command=self.on_prepare_excel).pack(
            side="left", padx=(0, 8)
        )
        self.start_btn = btn(
            prep_row,
            text="▶ START",
            variant="primary",
            width=140,
            height=theme.BTN_HEIGHT_LG,
            font=("Segoe UI", 14, "bold"),
            command=self.on_start_automation,
        )
        self.start_btn.pack(side="left", padx=(8, 0))

        self.sdk_btn = btn(
            prep_row,
            text="SDK prueba",
            variant="secondary",
            width=140,
            height=theme.BTN_HEIGHT_LG,
            command=self.on_send_sage_sdk_test,
        )
        self.sdk_btn.pack(side="left", padx=(8, 0))

        hint = glass_card(inner, radius=theme.BENTO_RADIUS_SM)
        hint.pack(fill="x")
        ctk.CTkLabel(
            hint,
            text=(
                "SDK prueba: escribe en LYL CONST CIA de PRUEBA\n"
                "(cliente C SUAREZ TORRE 1, fecha de hoy, prefijo AH).\n"
                "Debe correrse en la PC donde esta Sage 50."
            ),
            font=theme.FONT_SMALL,
            text_color=theme.TEXT_SECONDARY,
            justify="left",
        ).pack(anchor="w", padx=16, pady=14)

        log_shell = glass_card(page)
        log_shell.grid(row=2, column=1, sticky="nsew", padx=(theme.BENTO_GAP // 2, 0))
        log_shell.grid_columnconfigure(0, weight=1)
        log_shell.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            log_shell,
            text="Log de automatizacion",
            font=theme.FONT_HEADING,
            text_color=theme.TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="w", padx=theme.BENTO_PAD, pady=(theme.BENTO_PAD, 8))
        self.excel_log = ctk.CTkTextbox(
            log_shell,
            font=theme.FONT_MONO,
            corner_radius=theme.BENTO_RADIUS_SM,
            fg_color=theme.GLASS_INPUT,
            border_color=theme.GLASS_BORDER,
        )
        self.excel_log.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

    # ── Activity (log) ──────────────────────────────────────

    def _build_activity(self) -> None:
        page = self.page_frames["activity"]
        header = ctk.CTkFrame(page, fg_color="transparent")
        header.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(header, text="Actividad / Log", font=theme.FONT_HEADING, text_color=theme.TEXT_PRIMARY).pack(
            side="left"
        )
        btn(header, text="← Volver al flujo", variant="ghost", command=lambda: self._go_step(self._current_step)).pack(
            side="right"
        )
        self.log_text = ctk.CTkTextbox(
            page,
            font=theme.FONT_MONO,
            corner_radius=theme.BENTO_RADIUS,
            wrap="word",
            fg_color=theme.GLASS_INPUT,
            border_color=theme.GLASS_BORDER,
        )
        self.log_text.pack(fill="both", expand=True)

    # ── Helpers ─────────────────────────────────────────────

    def _continue_to_sage(self) -> None:
        if self.editor.dataframe.empty:
            show_warning(self, "Sin datos", "Importa facturas en el paso 1 antes de continuar.")
            self._go_step(1)
            return
        inv = self.editor.selected_invoice
        if not inv and self.editor.dataframe["Invoice Number"].nunique() > 1:
            show_warning(self, "Elige factura", "Hay varias facturas. Selecciona una en el menu Factura.")
            return
        self._update_current_invoice_from_editor()
        if self.current_invoice is None:
            show_warning(self, "Factura invalida", "No se pudo preparar la factura seleccionada.")
            return
        self._go_step(3)

    def _add_job(self, name: str, status: str) -> None:
        ts = datetime.now().strftime("%H:%M")
        self._recent_jobs.append((name, status, ts))
        tag = {"ok": "OK", "running": "...", "error": "ERR"}.get(status, status)
        self._log(f"[{tag}] {name}")

    def _log(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        self.log_text.insert("end", line)
        self.log_text.see("end")
        if hasattr(self, "excel_log"):
            self.excel_log.insert("end", line)
            self.excel_log.see("end")

    def _set_excel_status(self) -> None:
        has_data = self.current_invoice is not None
        has_excel = self.last_excel is not None and self.excel_open
        inv = self.editor.selected_invoice if hasattr(self, "editor") else None

        if has_data:
            self.excel_status.configure(text="Datos listos", text_color=theme.SUCCESS)
            self._update_stat_chip(self._stat_data, "Cargados ✓", theme.SUCCESS)
        else:
            self.excel_status.configure(text="Sin datos", text_color=theme.TEXT_SECONDARY)
            self._update_stat_chip(self._stat_data, "Sin cargar", theme.TEXT_MUTED)

        if has_excel:
            self._update_stat_chip(self._stat_excel, "Abierta ✓", theme.SUCCESS)
        else:
            self._update_stat_chip(self._stat_excel, "No abierta", theme.TEXT_MUTED)

        inv_label = str(inv)[:28] if inv else "—"
        self._update_stat_chip(self._stat_invoice, inv_label, theme.CYAN if inv else theme.TEXT_MUTED)

        if self.last_excel:
            self.excel_path_label.configure(text=f"Plantilla: {self.last_excel.name}")
        self._update_workflow_status()

    def _update_stat_chip(self, chip: ctk.CTkFrame, value: str, color: str) -> None:
        label = getattr(chip, "_value_label", None)
        if label is not None:
            label.configure(text=value, text_color=color)

    def _on_editor_change(self, frame: pd.DataFrame) -> None:
        self._dirty = True
        if hasattr(self.editor, "_dirty"):
            self.editor._set_dirty(True)
        if frame.empty:
            self.current_invoice = None
            self._set_excel_status()
            return
        try:
            inv = self.editor.selected_invoice
            subset = frame
            if inv and "Invoice Number" in frame.columns:
                subset = frame[frame["Invoice Number"].astype(str) == str(inv)]
            self.current_invoice = dataframe_to_invoice(subset, self.sim_config, invoice_number=inv)
            self._set_excel_status()
        except Exception as exc:
            self.current_invoice = None
            self._set_excel_status()
            self._log(f"Aviso editor: {exc}")
        self._update_workflow_status()

    def _load_into_editor(self, frame: pd.DataFrame) -> None:
        self._pending_frame = frame.copy()
        self.editor.load_dataframe(frame, mark_clean=True)
        self._dirty = False
        self._update_current_invoice_from_editor()

    def _update_current_invoice_from_editor(self) -> None:
        frame = self.editor.dataframe
        if frame.empty:
            self.current_invoice = None
            return
        inv = self.editor.selected_invoice
        subset = frame
        if inv and "Invoice Number" in frame.columns:
            subset = frame[frame["Invoice Number"].astype(str) == str(inv)]
        try:
            self.current_invoice = dataframe_to_invoice(subset, self.sim_config, invoice_number=inv)
        except Exception as exc:
            self.current_invoice = None
            self._log(f"Carga Sage requiere una factura: {exc}")
        self._set_excel_status()
        self._update_workflow_status()

    def _show_preview(
        self,
        source: str,
        frame: pd.DataFrame,
        valid_rows: list[dict],
        rejected_rows: list[dict],
        warnings: list[str] | None = None,
        pdf_meta: dict | None = None,
    ) -> None:
        self._import_source = source
        self._pending_frame = frame.copy()
        self.valid_rows = valid_rows
        self.rejected_rows = rejected_rows
        self._import_warnings = warnings or []
        self._pdf_meta = pdf_meta or {}
        self.preview_panel.show_data(source, frame, valid_rows, rejected_rows, warnings, pdf_meta)
        self._show_step2_mode("preview")
        self._go_step(2)

    def _commit_preview_to_editor(self) -> None:
        if self._pending_frame.empty:
            show_warning(self, "Sin datos", "No hay datos validos para cargar.")
            return
        self._load_into_editor(self._pending_frame)
        self._add_job(f"Editor: {len(self._pending_frame)} lineas", "ok")
        self._log(f"Listo para editar — {self._import_source}.")
        self._show_step2_mode("editor")
        self._go_step(2)

    def _extract_db_selected(self, invoice_ids: list) -> None:
        try:
            self._add_job("Extraccion BD", "running")
            raw = extract_invoices_by_ids(self.config, ROOT, invoice_ids)
            self._process_raw_import(raw, "PsKloud BD")
        except Exception as exc:
            show_error(self, "Error BD", str(exc))
            self._log(f"ERROR BD: {exc}")

    def _process_raw_import(self, raw: list[dict], source: str, warnings: list[str] | None = None, pdf_meta: dict | None = None) -> None:
        self.valid_rows, self.rejected_rows = validate_rows(raw, self.config)
        frame = transform_rows(self.valid_rows, self.config)
        if frame.empty and not self.rejected_rows:
            show_warning(self, "Sin datos", "No se encontraron facturas validas.")
            self._add_job(f"{source}: sin datos", "error")
            return
        self._show_preview(source, frame, self.valid_rows, self.rejected_rows, warnings, pdf_meta)
        self._add_job(f"{source}: vista previa", "ok")
        self._log(f"Vista previa {source}: {len(frame)} lineas validas, {len(self.rejected_rows)} rechazadas.")

    def _confirm_overwrite(self) -> bool:
        if not self._dirty:
            return True
        return ask_confirm(self, "Cambios sin guardar", "Hay cambios en el editor. ¿Continuar y reemplazar datos?")

    # ── Actions ─────────────────────────────────────────────

    def on_extract(self) -> None:
        if not self._confirm_overwrite():
            return
        try:
            self._add_job("Extraccion BD", "running")
            raw = extract_invoices(self.config, ROOT)
            self._process_raw_import(raw, "PsKloud BD (incremental)")
        except Exception as exc:
            show_error(self, "Error", str(exc))
            self._log(f"ERROR: {exc}")

    def on_load_sika_sdk_test(self) -> None:
        if not self._confirm_overwrite():
            return
        try:
            raw = load_sika_test_rows(ROOT)
            warnings = [
                "Prueba SDK: factura PsKloud *0000001 (Miguel del Rio, 3 lineas Sika).",
                "En Sage de prueba el cliente sera "
                + TEST_CUSTOMER_ID
                + " y la fecha de hoy (ano abierto).",
                "montoneto a veces no cuadra con cantidad x preciounit; se envia el neto de linea.",
            ]
            valid, rejected = validate_rows(raw, self.config)
            if not valid:
                valid = raw
                warnings.append("Validacion Auto-Hub rechazo por descuento/RUC; se carga igual para la prueba SDK.")
                rejected = []
            frame = transform_rows(valid, self.config)
            self._show_preview("SDK prueba *0000001", frame, valid, rejected, warnings)
            self._add_job("Cargada prueba Sika *0000001", "ok")
            self._log("Cargadas 3 lineas Sika (*0000001). Paso 3 → SDK prueba.")
        except Exception as exc:
            show_error(self, "Prueba SDK", str(exc))
            self._log(f"ERROR prueba Sika: {exc}")

    def on_send_sage_sdk_test(self) -> None:
        rows = self.valid_rows or []
        if not rows:
            try:
                rows = load_sika_test_rows(ROOT)
            except Exception as exc:
                show_error(self, "SDK", "No hay factura cargada. " + str(exc))
                return
        if not ask_confirm(
            self,
            "Enviar a Sage (prueba)",
            "Se escribira 1 factura en:\n"
            + TEST_COMPANY
            + "\nCliente: "
            + TEST_CUSTOMER_ID
            + "\nLineas: "
            + str(len(rows))
            + "\n\nNO toca LYL CONSTRUCTIONS SUPPLY INC 2025.\n"
            "Sage 50 debe estar en esta PC (Always Allow si lo pide).",
        ):
            return

        self._go_step(3)
        self._add_job("SDK prueba", "running")
        self._log("SDK prueba — compilando y enviando...")
        if hasattr(self, "sdk_btn"):
            self.sdk_btn.configure(state="disabled")

        def worker() -> None:
            try:
                run_test_company_write(
                    ROOT,
                    rows,
                    on_log=lambda msg: self.after(0, self._log, msg),
                )
                self.after(0, self._on_sdk_done, True, "OK — factura enviada a empresa de prueba. Busca prefijo AH.")
            except Exception as exc:
                self.after(0, self._on_sdk_done, False, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_sdk_done(self, ok: bool, message: str) -> None:
        if hasattr(self, "sdk_btn"):
            self.sdk_btn.configure(state="normal")
        self._log(message)
        if ok:
            self._add_job("SDK prueba OK", "ok")
            show_info(self, "Sage SDK", message)
        else:
            self._add_job("SDK prueba fallo", "error")
            show_error(self, "Sage SDK", message)

    def on_extract_pdf(self) -> None:
        if not self._confirm_overwrite():
            return
        paths = filedialog.askopenfilenames(
            title="Seleccionar facturas PDF",
            filetypes=[("PDF", "*.pdf"), ("Todos", "*.*")],
        )
        if not paths:
            return
        try:
            self._add_job("Extraccion PDF", "running")
            raw, warnings, pdf_meta = extract_invoices_from_pdfs([Path(p) for p in paths], ROOT)
            self._process_raw_import(raw, "PDF", warnings, pdf_meta)
        except Exception as exc:
            show_error(self, "Error PDF", str(exc))
            self._log(f"ERROR PDF: {exc}")
            self._add_job("Extraccion PDF fallo", "error")

    def on_open_csv(self) -> None:
        if not self._confirm_overwrite():
            return
        path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            raw_frame = pd.read_csv(path)
            expected = self.config["mapping"]["sage_columns"]
            mapping = detect_column_mapping(raw_frame, expected)
            missing = [k for k, v in mapping.items() if v is None and k in {"Invoice Number", "Description", "Line Amount"}]
            if missing:
                show_warning(
                    self,
                    "Columnas faltantes",
                    f"No se detectaron columnas: {', '.join(missing)}.\nSe intentara aplicar mapeo parcial.",
                )
            mapped = apply_column_mapping(raw_frame, mapping)
            mapped = normalize_sage_columns(mapped, expected)
            raw_rows = sage_dataframe_to_raw_rows(mapped, self.config)
            self.last_csv = Path(path)
            self._process_raw_import(raw_rows, f"CSV ({Path(path).name})")
        except Exception as exc:
            show_error(self, "Error CSV", str(exc))

    def on_revalidate(self) -> None:
        try:
            raw_rows = sage_dataframe_to_raw_rows(self.editor.dataframe, self.config)
            self.valid_rows, self.rejected_rows = validate_rows(raw_rows, self.config)
            frame = transform_rows(self.valid_rows, self.config)
            self._show_preview(self._import_source or "Revalidacion", frame, self.valid_rows, self.rejected_rows)
            self._log("Revalidacion completada.")
        except Exception as exc:
            show_error(self, "Error validacion", str(exc))

    def on_export_rejected(self) -> None:
        if not self.rejected_rows:
            show_info(self, "Rechazados", "No hay filas rechazadas.")
            return
        try:
            path = export_rejected(self.rejected_rows, self.config, ROOT)
            if path:
                show_info(self, "Exportado", f"Rechazados guardados en:\n{path}")
                self._log(f"Rechazados exportados: {path}")
        except Exception as exc:
            show_error(self, "Error", str(exc))

    def on_prepare_excel(self) -> None:
        self._ensure_template()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = ROOT / self.sim_config["paths"]["output_dir"] / f"sage_live_{timestamp}.xlsx"
        self.last_excel = copy_empty_workbook(ROOT, self.sim_config, output)
        self._log(f"Abriendo Excel: {self.last_excel.name}")
        os.startfile(str(self.last_excel))
        self.excel_open = True
        self._set_excel_status()
        self._add_job(f"Excel: {self.last_excel.name}", "ok")
        show_info(
            self,
            "Plantilla lista",
            f"Plantilla Sage abierta:\n{self.last_excel.name}\n\nAhora pulsa START.",
        )

    def on_start_automation(self) -> None:
        if self.current_invoice is None:
            show_warning(self, "Sin datos", "Selecciona una factura en el Editor y vuelve a intentar.")
            return
        inv = self.editor.selected_invoice if hasattr(self, "editor") else None
        if not inv and self.editor.dataframe["Invoice Number"].nunique() > 1:
            show_warning(
                self,
                "Varias facturas",
                "Hay varias facturas cargadas. Selecciona una en el Editor antes de usar START.",
            )
            return
        if not self.excel_open or self.last_excel is None:
            if not ask_confirm(self, "Abrir Excel", "Excel no está abierto. ¿Abrirlo ahora?"):
                return
            self.on_prepare_excel()

        self._go_step(3)
        self._add_job("Automatizacion START", "running")
        self._log("▶ START — automatización iniciada...")
        self.start_btn.configure(state="disabled", text="Ejecutando...")

        invoice = self.current_invoice

        def worker() -> None:
            try:
                run_excel_automation(
                    self.last_excel,
                    invoice,
                    ROOT,
                    on_step=lambda msg: self.after(0, self._log, msg),
                )
                self.after(0, lambda: self._add_job("Automatización OK", "ok"))
                self.after(0, lambda: self._log("✅ START completado."))
                self.after(0, lambda: show_info(self, "Completado", "Excel llenado automáticamente."))
            except Exception as exc:
                self.after(0, lambda: show_error(self, "Error", str(exc)))
                self.after(0, lambda: self._add_job("Automatización falló", "error"))
            finally:
                self.after(0, lambda: self.start_btn.configure(state="normal", text="▶ START"))

        threading.Thread(target=worker, daemon=True).start()

    def on_export(self) -> None:
        frame = self.editor.dataframe
        if frame is None or frame.empty:
            show_warning(self, "Sin datos", "No hay datos para exportar.")
            return
        if self.rejected_rows and not ask_confirm(
            self,
            "Rechazados pendientes",
            f"Hay {len(self.rejected_rows)} lineas rechazadas. ¿Exportar de todos modos?",
        ):
            return
        try:
            self.last_csv = export_csv(frame, self.config, ROOT)
            if self.valid_rows:
                save_watermark(self.config, ROOT, self.valid_rows)
            self._log(f"CSV exportado: {self.last_csv}")
            self._add_job(f"Export: {self.last_csv.name}", "ok")
            self.editor.mark_clean()
            self._dirty = False
            show_info(self, "Exportado", str(self.last_csv))
        except Exception as exc:
            show_error(self, "Error", str(exc))

    def _ensure_template(self) -> None:
        template = ROOT / self.sim_config["paths"]["template"]
        if not template.exists():
            create_sage_template(ROOT, self.sim_config)

    def on_reset(self) -> None:
        import subprocess

        if not ask_confirm(self, "Reiniciar", "¿Restablecer la base de datos local y el estado de sincronizacion?"):
            return
        subprocess.run([sys.executable, str(ROOT / "scripts" / "seed_database.py")], check=True)
        state = ROOT / self.config["extraction"]["watermark_file"]
        if state.exists():
            state.unlink()
        self.editor.load_dataframe(pd.DataFrame())
        self.current_invoice = None
        self.excel_open = False
        self.last_excel = None
        self._set_excel_status()
        self._log("Datos locales restablecidos.")


def main() -> None:
    _set_windows_app_id()
    _ensure_local_database()
    app = AutoHubApp()
    app.mainloop()


if __name__ == "__main__":
    main()
