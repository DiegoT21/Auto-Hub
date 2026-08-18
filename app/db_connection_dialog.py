from __future__ import annotations

import threading
from pathlib import Path
from tkinter import filedialog
from typing import Any, Callable

import customtkinter as ctk

from app import theme
from app.components import btn, glass_card, glass_input
from app.dialogs import ask_confirm, show_info
from src.connections import (
    DEFAULT_CONNECTIONS_PATH,
    SCHEMA_LABELS,
    SCHEMA_PRESETS,
    activate_connection,
    connection_summary,
    ensure_pskloud_view,
    get_connection,
    load_connections,
    new_connection_id,
    save_connections,
    save_config,
    test_connection,
)


class ConnectionBar(ctk.CTkFrame):
    """Selector compacto de conexion activa."""

    def __init__(
        self,
        parent: ctk.CTk,
        *,
        root: Path,
        config_path: Path,
        connections_path: Path = DEFAULT_CONNECTIONS_PATH,
        on_changed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, fg_color="transparent")
        self.root = root
        self.config_path = config_path
        self.connections_path = connections_path
        self.on_changed = on_changed
        self._data = load_connections(connections_path)

        self.grid_columnconfigure(0, weight=1)

        names = [item["name"] for item in self._data.get("connections", [])]
        if not names:
            names = ["Sin conexiones"]

        self._name_to_id = {item["name"]: item["id"] for item in self._data.get("connections", [])}
        active = get_connection(self._data)
        default_name = active["name"] if active else names[0]

        self.selector = ctk.CTkOptionMenu(
            self,
            values=names,
            command=self._on_select,
            fg_color=theme.GLASS_INPUT,
            button_color=theme.ACCENT,
            button_hover_color=theme.ACCENT_HOVER,
            dropdown_fg_color=theme.GLASS_BG,
            dropdown_hover_color=theme.GLASS_BG_HOVER,
            text_color=theme.TEXT_PRIMARY,
            width=220,
        )
        self.selector.set(default_name)
        self.selector.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        btn(self, text="Configurar", variant="ghost", width=100, command=self._open_dialog).grid(
            row=0, column=1, sticky="e"
        )

    def refresh(self) -> None:
        self._data = load_connections(self.connections_path)
        names = [item["name"] for item in self._data.get("connections", [])]
        if not names:
            names = ["Sin conexiones"]
        self._name_to_id = {item["name"]: item["id"] for item in self._data.get("connections", [])}
        self.selector.configure(values=names)
        active = get_connection(self._data)
        if active and active["name"] in names:
            self.selector.set(active["name"])

    def _on_select(self, name: str) -> None:
        conn_id = self._name_to_id.get(name)
        if not conn_id:
            return

        def worker() -> None:
            try:
                activate_connection(
                    conn_id,
                    connections_path=self.connections_path,
                    config_path=self.config_path,
                    root=self.root,
                )
                self.after(0, lambda: self._after_select_ok())
            except Exception as exc:
                self.after(0, lambda: show_info(self.winfo_toplevel(), "Conexion", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _after_select_ok(self) -> None:
        if self.on_changed:
            self.on_changed()

    def _open_dialog(self) -> None:
        app = self.winfo_toplevel()

        def on_saved() -> None:
            self.refresh()
            if self.on_changed:
                self.on_changed()

        DatabaseConnectionDialog(app, root=self.root, config_path=self.config_path, on_saved=on_saved)


class DatabaseConnectionDialog(ctk.CTkToplevel):
    """Dialogo para crear, editar, probar y activar conexiones."""

    def __init__(
        self,
        parent: ctk.CTk,
        *,
        root: Path,
        config_path: Path,
        connections_path: Path = DEFAULT_CONNECTIONS_PATH,
        on_saved: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.title("Conexion a base de datos")
        self.geometry("780x640")
        self.minsize(720, 600)
        self.transient(parent)
        self.grab_set()
        self.configure(fg_color=theme.BG_DARK)

        self.root = root
        self.config_path = config_path
        self.connections_path = connections_path
        self.on_saved = on_saved
        self._data = load_connections(connections_path)
        self._selected_id: str | None = self._data.get("active_id")
        self._list_buttons: dict[str, ctk.CTkButton] = {}

        shell = glass_card(self)
        shell.pack(fill="both", expand=True, padx=16, pady=16)
        inner = ctk.CTkFrame(shell, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=20, pady=20)
        inner.grid_columnconfigure(1, weight=1)
        inner.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            inner,
            text="Conexiones guardadas",
            font=theme.FONT_HEADING,
            text_color=theme.TEXT_PRIMARY,
        ).grid(row=0, column=0, sticky="w", pady=(0, 12))

        ctk.CTkLabel(
            inner,
            text="Datos de conexion",
            font=theme.FONT_HEADING,
            text_color=theme.TEXT_PRIMARY,
        ).grid(row=0, column=1, sticky="w", padx=(16, 0), pady=(0, 12))

        list_wrap = ctk.CTkScrollableFrame(inner, fg_color=theme.GLASS_INPUT, corner_radius=12, width=220)
        list_wrap.grid(row=1, column=0, sticky="nsew")
        self._list_wrap = list_wrap

        form_shell = glass_card(inner, radius=theme.BENTO_RADIUS_SM)
        form_shell.grid(row=1, column=1, sticky="nsew", padx=(16, 0))
        form_shell.grid_rowconfigure(0, weight=1)
        form_shell.grid_columnconfigure(0, weight=1)
        form = ctk.CTkScrollableFrame(form_shell, fg_color="transparent", corner_radius=0)
        form.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        form.grid_columnconfigure(1, weight=1)
        self._form = form

        self._fields: dict[str, Any] = {}
        self._row_widgets: dict[str, tuple[ctk.CTkLabel, ctk.CTkBaseClass]] = {}
        self._loading_profile = False
        self._busy = False
        self._action_buttons: list[ctk.CTkButton] = []
        self._build_form_fields(form)

        status_row = ctk.CTkFrame(inner, fg_color="transparent")
        status_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self._status = ctk.CTkLabel(
            status_row,
            text="",
            font=theme.FONT_SMALL,
            text_color=theme.TEXT_SECONDARY,
            wraplength=680,
            justify="left",
        )
        self._status.pack(anchor="w")

        actions = ctk.CTkFrame(inner, fg_color="transparent")
        actions.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(16, 0))

        btn(actions, text="Nueva", variant="ghost", width=90, command=self._new_connection).pack(side="left")
        self._action_buttons.append(
            btn(actions, text="Eliminar", variant="danger", width=90, command=self._delete_connection)
        )
        self._action_buttons[-1].pack(side="left", padx=(8, 0))
        self._action_buttons.append(
            btn(actions, text="Crear vista PsKloud", variant="secondary", width=150, command=self._create_view)
        )
        self._action_buttons[-1].pack(side="left", padx=(8, 0))
        self._test_btn = btn(actions, text="Probar", variant="secondary", width=90, command=self._test)
        self._test_btn.pack(side="right", padx=(8, 0))
        self._action_buttons.append(self._test_btn)
        self._save_btn = btn(actions, text="Guardar", variant="secondary", width=100, command=self._save)
        self._save_btn.pack(side="right", padx=(8, 0))
        self._action_buttons.append(self._save_btn)
        self._use_btn = btn(actions, text="Usar conexion", variant="primary", width=130, command=self._use_connection)
        self._use_btn.pack(side="right")
        self._action_buttons.append(self._use_btn)

        self._render_list()
        if self._selected_id:
            self._load_profile(self._selected_id)
        else:
            self._apply_driver_visibility("sqlite")

        parent.wait_window(self)

    def _build_form_fields(self, form: ctk.CTkFrame) -> None:
        row = 0

        def add_row(label: str, widget: ctk.CTkBaseClass, key: str) -> None:
            nonlocal row
            lbl = ctk.CTkLabel(form, text=label, font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY)
            lbl.grid(row=row, column=0, sticky="nw", padx=(0, 10), pady=8)
            widget.grid(row=row, column=1, sticky="ew", pady=8)
            self._fields[key] = widget
            self._row_widgets[key] = (lbl, widget)
            row += 1

        menu_defaults = dict(
            fg_color=theme.GLASS_INPUT,
            button_color=theme.ACCENT,
            button_hover_color=theme.ACCENT_HOVER,
            text_color=theme.TEXT_PRIMARY,
            dropdown_fg_color=theme.GLASS_BG,
            dropdown_hover_color=theme.GLASS_BG_HOVER,
            dropdown_text_color=theme.TEXT_PRIMARY,
            height=36,
            font=theme.FONT_BODY,
            dropdown_font=theme.FONT_BODY,
        )

        name_entry = glass_input(form, placeholder_text="Ej. MySQL produccion")
        add_row("Nombre", name_entry, "name")

        driver_menu = ctk.CTkOptionMenu(
            form,
            values=["sqlite", "mysql"],
            command=self._on_driver_change,
            **menu_defaults,
        )
        add_row("Tipo", driver_menu, "driver")

        schema_menu = ctk.CTkOptionMenu(
            form,
            values=[SCHEMA_LABELS[key] for key in SCHEMA_PRESETS],
            command=self._on_schema_label_change,
            **menu_defaults,
        )
        schema_menu.set(SCHEMA_LABELS["normalized_tables"])
        add_row("Esquema", schema_menu, "schema")
        self._schema_value_by_label = {label: key for key, label in SCHEMA_LABELS.items()}
        self._schema_label_by_value = SCHEMA_LABELS

        sqlite_row = ctk.CTkFrame(form, fg_color="transparent")
        sqlite_row.grid_columnconfigure(0, weight=1)
        sqlite_entry = glass_input(sqlite_row, placeholder_text="data/pskloud_demo.db")
        sqlite_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        btn(sqlite_row, text="...", variant="ghost", width=36, command=self._browse_sqlite).grid(row=0, column=1)
        add_row("Archivo SQLite", sqlite_row, "sqlite_path")
        self._fields["sqlite_path"] = sqlite_entry

        host_entry = glass_input(form, placeholder_text="127.0.0.1")
        add_row("Host", host_entry, "host")

        port_entry = glass_input(form, width=100, placeholder_text="3306")
        add_row("Puerto", port_entry, "port")

        database_entry = glass_input(form, placeholder_text="adminposper")
        add_row("Base de datos", database_entry, "database")

        user_entry = glass_input(form, placeholder_text="root")
        add_row("Usuario", user_entry, "user")

        password_entry = glass_input(form, placeholder_text="Contrasena MySQL", show="•")
        add_row("Contrasena", password_entry, "password")

        view_entry = glass_input(form, placeholder_text="autohub_v_facturas")
        add_row("Vista canonica", view_entry, "canonical_view")

        self._mysql_fields = ["host", "port", "database", "user", "password", "canonical_view"]
        self._sqlite_fields = ["sqlite_path"]

    def _render_list(self) -> None:
        for child in self._list_wrap.winfo_children():
            child.destroy()
        self._list_buttons.clear()

        for item in self._data.get("connections", []):
            conn_id = item["id"]
            is_active = conn_id == self._data.get("active_id")
            label = f"{'● ' if is_active else ''}{item['name']}"
            list_btn = ctk.CTkButton(
                self._list_wrap,
                text=label,
                anchor="w",
                height=36,
                fg_color=theme.ACCENT if conn_id == self._selected_id else "transparent",
                hover_color=theme.GLASS_BG_HOVER,
                text_color="white" if conn_id == self._selected_id else theme.TEXT_PRIMARY,
                command=lambda cid=conn_id: self._load_profile(cid),
            )
            list_btn.pack(fill="x", pady=2, padx=4)
            self._list_buttons[conn_id] = list_btn

    def _set_field(self, key: str, value: str) -> None:
        widget = self._fields[key]
        widget.delete(0, "end")
        if value:
            widget.insert(0, value)

    def _load_profile(self, conn_id: str) -> None:
        profile = get_connection(self._data, conn_id)
        if not profile:
            return
        self._selected_id = conn_id
        self._render_list()

        self._loading_profile = True
        try:
            self._set_field("name", profile.get("name", ""))
            self._fields["driver"].set(profile.get("driver", "sqlite"))
            self._fields["schema"].set(
                self._schema_label_by_value.get(
                    profile.get("schema", "normalized_tables"),
                    SCHEMA_LABELS["normalized_tables"],
                )
            )
            self._set_field("sqlite_path", profile.get("sqlite_path", "data/pskloud_demo.db"))
            self._set_field("host", profile.get("host", "127.0.0.1"))
            self._set_field("port", str(profile.get("port", 3306)))
            self._set_field("database", profile.get("database", ""))
            self._set_field("user", profile.get("user", ""))
            self._set_field("password", profile.get("password", ""))
            self._set_field("canonical_view", profile.get("canonical_view", "autohub_v_facturas"))
            self._apply_driver_visibility(profile.get("driver", "sqlite"))
        finally:
            self._loading_profile = False

        self._status.configure(
            text=connection_summary(profile),
            text_color=theme.TEXT_SECONDARY,
        )

    def _current_profile(self) -> dict[str, Any]:
        driver = self._fields["driver"].get()
        profile: dict[str, Any] = {
            "id": self._selected_id or new_connection_id(self._data.get("connections", [])),
            "name": self._fields["name"].get().strip() or "Sin nombre",
            "driver": driver,
            "schema": self._schema_value_by_label.get(self._fields["schema"].get(), "normalized_tables"),
        }
        if driver == "sqlite":
            profile["sqlite_path"] = self._fields["sqlite_path"].get().strip() or "data/pskloud_demo.db"
        else:
            profile["host"] = self._fields["host"].get().strip() or "127.0.0.1"
            try:
                profile["port"] = int(self._fields["port"].get().strip() or "3306")
            except ValueError:
                profile["port"] = 3306
            profile["database"] = self._fields["database"].get().strip()
            profile["user"] = self._fields["user"].get().strip()
            profile["password"] = self._fields["password"].get()
            if profile["schema"] == "pskloud_canonical":
                profile["canonical_view"] = (
                    self._fields["canonical_view"].get().strip() or "autohub_v_facturas"
                )
        return profile

    def _set_row_visible(self, key: str, visible: bool) -> None:
        pair = self._row_widgets.get(key)
        if not pair:
            return
        lbl, widget = pair
        if visible:
            lbl.grid()
            widget.grid()
        else:
            lbl.grid_remove()
            widget.grid_remove()

    def _apply_driver_visibility(self, driver: str) -> None:
        for key in self._mysql_fields:
            self._set_row_visible(key, driver == "mysql")
        for key in self._sqlite_fields:
            self._set_row_visible(key, driver == "sqlite")

        if driver == "sqlite":
            self._fields["schema"].configure(state="disabled")
            self._set_row_visible("canonical_view", False)
        else:
            self._fields["schema"].configure(state="normal")
            schema = self._schema_value_by_label.get(self._fields["schema"].get(), "normalized_tables")
            self._set_row_visible("canonical_view", schema == "pskloud_canonical")

    def _on_driver_change(self, driver: str) -> None:
        if self._loading_profile:
            return
        self._apply_driver_visibility(driver)
        if driver == "sqlite":
            self._fields["schema"].set(SCHEMA_LABELS["normalized_tables"])

    def _on_schema_label_change(self, label: str) -> None:
        schema = self._schema_value_by_label.get(label, "normalized_tables")
        self._on_schema_change(schema)

    def _on_schema_change(self, schema: str) -> None:
        if self._fields["driver"].get() != "mysql":
            return
        self._set_row_visible("canonical_view", schema == "pskloud_canonical")
        if schema == "pskloud_canonical" and not self._fields["canonical_view"].get().strip():
            self._fields["canonical_view"].insert(0, "autohub_v_facturas")

    def _browse_sqlite(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Seleccionar base SQLite",
            filetypes=[("SQLite", "*.db *.sqlite *.sqlite3"), ("Todos", "*.*")],
        )
        if not path:
            return
        try:
            rel = Path(path).resolve().relative_to(self.root.resolve())
            value = rel.as_posix()
        except ValueError:
            value = str(Path(path))
        self._fields["sqlite_path"].delete(0, "end")
        self._fields["sqlite_path"].insert(0, value)

    def _validate_profile(self, profile: dict[str, Any]) -> str | None:
        if profile.get("driver") == "mysql":
            missing = []
            if not profile.get("database"):
                missing.append("base de datos")
            if not profile.get("user"):
                missing.append("usuario")
            if missing:
                return f"Completa: {', '.join(missing)}"
        return None

    def _upsert_current(self) -> dict[str, Any]:
        profile = self._current_profile()
        error = self._validate_profile(profile)
        if error:
            raise ValueError(error)

        connections = self._data.setdefault("connections", [])
        saved_profile = profile
        replaced = False
        for index, item in enumerate(connections):
            if item.get("id") == profile["id"]:
                merged = dict(item)
                merged.update(profile)
                for key in ("host", "database", "user", "password", "canonical_view", "sqlite_path"):
                    if (merged.get(key) in {"", None}) and (item.get(key) not in {"", None}):
                        merged[key] = item.get(key)
                if merged.get("driver") == "mysql" and not merged.get("port") and item.get("port"):
                    merged["port"] = item.get("port")
                connections[index] = merged
                saved_profile = merged
                replaced = True
                break
        if not replaced:
            connections.append(profile)
        self._selected_id = saved_profile["id"]
        save_connections(self._data, self.connections_path)
        self._render_list()
        return saved_profile

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        for button in self._action_buttons:
            try:
                button.configure(state=state)
            except Exception:
                pass
        if message:
            self._status.configure(text=message, text_color=theme.TEXT_SECONDARY)

    def _run_async(self, pending: str, work: Callable[[], tuple[bool, str] | str]) -> None:
        if self._busy:
            return
        self._set_busy(True, pending)

        def worker() -> None:
            try:
                result = work()
                if isinstance(result, tuple):
                    ok, message = result
                    color = theme.SUCCESS if ok else theme.DANGER
                else:
                    message, color = result, theme.SUCCESS
            except Exception as exc:
                message, color = str(exc), theme.DANGER
            self.after(0, lambda: self._finish_async(message, color))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_async(self, message: str, color: str) -> None:
        self._set_busy(False)
        self._status.configure(text=message, text_color=color)

    def _save(self) -> None:
        try:
            profile = self._upsert_current()
        except ValueError as exc:
            self._status.configure(text=str(exc), text_color=theme.DANGER)
            return
        path = self.connections_path.resolve()
        self._status.configure(
            text=f"Guardado en {path.name} · {connection_summary(profile)}",
            text_color=theme.SUCCESS,
        )
        if self.on_saved:
            self.on_saved()

    def _test(self) -> None:
        try:
            profile = self._upsert_current()
        except ValueError as exc:
            self._status.configure(text=str(exc), text_color=theme.DANGER)
            return

        def work() -> tuple[bool, str]:
            return test_connection(profile, self.root, quick=True)

        self._run_async("Probando conexion...", work)

    def _create_view(self) -> None:
        try:
            profile = self._upsert_current()
        except ValueError as exc:
            self._status.configure(text=str(exc), text_color=theme.DANGER)
            return
        if profile.get("schema") != "pskloud_canonical":
            self._status.configure(text="Selecciona esquema PsKloud MySQL para crear la vista.")
            return

        def work() -> tuple[bool, str]:
            return ensure_pskloud_view(profile, self.root)

        self._run_async("Creando vista en el servidor...", work)

    def _use_connection(self) -> None:
        try:
            profile = self._upsert_current()
        except ValueError as exc:
            self._status.configure(text=str(exc), text_color=theme.DANGER)
            return

        def work() -> tuple[bool, str]:
            _, config, summary = activate_connection(
                profile["id"],
                connections_path=self.connections_path,
                config_path=self.config_path,
                root=self.root,
            )
            save_config(config, self.config_path)
            return True, f"Activa · {summary}"

        def on_done(message: str, color: str) -> None:
            self._finish_async(message, color)
            if color == theme.SUCCESS:
                self._data = load_connections(self.connections_path)
                self._render_list()
                if self.on_saved:
                    self.on_saved()

        if self._busy:
            return
        self._set_busy(True, "Activando conexion...")

        def worker() -> None:
            try:
                ok, message = work()
                color = theme.SUCCESS if ok else theme.DANGER
            except Exception as exc:
                message, color = str(exc), theme.DANGER
            self.after(0, lambda: on_done(message, color))

        threading.Thread(target=worker, daemon=True).start()

    def _new_connection(self) -> None:
        conn_id = new_connection_id(self._data.get("connections", []))
        self._selected_id = conn_id
        self._fields["name"].delete(0, "end")
        self._fields["name"].insert(0, "Nueva conexion")
        self._fields["driver"].set("mysql")
        self._fields["schema"].set(SCHEMA_LABELS["pskloud_canonical"])
        self._fields["host"].delete(0, "end")
        self._fields["host"].insert(0, "127.0.0.1")
        self._fields["port"].delete(0, "end")
        self._fields["port"].insert(0, "3306")
        self._fields["database"].delete(0, "end")
        self._fields["database"].insert(0, "adminposper")
        self._fields["user"].delete(0, "end")
        self._fields["user"].insert(0, "root")
        self._fields["password"].delete(0, "end")
        self._fields["canonical_view"].delete(0, "end")
        self._fields["canonical_view"].insert(0, "autohub_v_facturas")
        self._on_driver_change("mysql")
        self._render_list()

    def _delete_connection(self) -> None:
        if not self._selected_id:
            return
        if not ask_confirm(self, "Eliminar", "¿Eliminar esta conexion guardada?"):
            return
        self._data["connections"] = [
            item for item in self._data.get("connections", []) if item.get("id") != self._selected_id
        ]
        if self._data.get("active_id") == self._selected_id:
            first = self._data["connections"][0]["id"] if self._data["connections"] else None
            self._data["active_id"] = first
        save_connections(self._data, self.connections_path)
        self._selected_id = self._data.get("active_id")
        self._render_list()
        if self._selected_id:
            self._load_profile(self._selected_id)
        if self.on_saved:
            self.on_saved()
