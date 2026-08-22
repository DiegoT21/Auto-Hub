from __future__ import annotations

import customtkinter as ctk

from app import theme
from app.components import btn


def _place_on_parent(window: ctk.CTkToplevel, parent: ctk.CTk, width: int, height: int) -> None:
    window.update_idletasks()
    try:
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = max(parent.winfo_width(), 400)
        ph = max(parent.winfo_height(), 300)
    except Exception:
        px, py, pw, ph = 80, 80, 900, 600
    x = px + max(20, (pw - width) // 2)
    y = py + max(20, (ph - height) // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")


def _open_modal(parent: ctk.CTk, window: ctk.CTkToplevel, width: int, height: int) -> None:
    window.configure(fg_color="#FFFFFF")
    window.resizable(False, False)
    window.transient(parent)
    _place_on_parent(window, parent, width, height)
    window.lift()
    window.attributes("-topmost", True)
    window.deiconify()
    window.focus_force()
    window.grab_set()
    window.after(400, lambda: window.attributes("-topmost", False) if window.winfo_exists() else None)


def ask_text(parent: ctk.CTk, title: str, prompt: str, initial: str = "") -> str | None:
    dialog = ctk.CTkInputDialog(text=prompt, title=title)
    if initial:
        try:
            dialog._entry.insert(0, initial)
            dialog._entry.select_range(0, "end")
        except Exception:
            pass
    value = dialog.get_input()
    if value is None or value == "":
        return None
    return value


def ask_confirm(parent: ctk.CTk, title: str, message: str) -> bool:
    result: list[bool] = [False]
    lines = message.count("\n") + 1
    height = min(420, max(260, 140 + lines * 22))
    width = 560

    window = ctk.CTkToplevel(parent)
    window.title(title)
    window.withdraw()

    shell = ctk.CTkFrame(
        window,
        fg_color="#FFFFFF",
        corner_radius=12,
        border_width=2,
        border_color=theme.ACCENT,
    )
    shell.pack(fill="both", expand=True, padx=10, pady=10)

    inner = ctk.CTkFrame(shell, fg_color="#FFFFFF")
    inner.pack(fill="both", expand=True, padx=22, pady=18)

    ctk.CTkLabel(
        inner,
        text=title,
        font=theme.FONT_HEADING,
        text_color=theme.TEXT_PRIMARY,
        anchor="w",
    ).pack(fill="x", pady=(0, 10))

    ctk.CTkLabel(
        inner,
        text=message,
        wraplength=width - 80,
        justify="left",
        font=theme.FONT_BODY,
        text_color=theme.TEXT_PRIMARY,
        anchor="w",
    ).pack(fill="x", pady=(0, 18))

    buttons = ctk.CTkFrame(inner, fg_color="#FFFFFF")
    buttons.pack(fill="x", side="bottom")

    def on_yes() -> None:
        result[0] = True
        window.destroy()

    def on_no() -> None:
        window.destroy()

    btn(buttons, text="Cancelar", variant="ghost", width=110, command=on_no).pack(side="right", padx=(8, 0))
    btn(buttons, text="Confirmar", variant="primary", width=120, command=on_yes).pack(side="right")

    _open_modal(parent, window, width, height)
    parent.wait_window(window)
    return result[0]


def show_info(parent: ctk.CTk, title: str, message: str) -> None:
    lines = message.count("\n") + max(1, len(message) // 70)
    height = min(460, max(240, 130 + lines * 20))
    width = 560

    window = ctk.CTkToplevel(parent)
    window.title(title)
    window.withdraw()

    shell = ctk.CTkFrame(
        window,
        fg_color="#FFFFFF",
        corner_radius=12,
        border_width=2,
        border_color=theme.ACCENT,
    )
    shell.pack(fill="both", expand=True, padx=10, pady=10)

    inner = ctk.CTkFrame(shell, fg_color="#FFFFFF")
    inner.pack(fill="both", expand=True, padx=22, pady=18)

    ctk.CTkLabel(
        inner,
        text=title,
        font=theme.FONT_HEADING,
        text_color=theme.TEXT_PRIMARY,
        anchor="w",
    ).pack(fill="x", pady=(0, 10))

    box = ctk.CTkTextbox(
        inner,
        fg_color="#F8FAFC",
        text_color=theme.TEXT_PRIMARY,
        font=theme.FONT_BODY,
        wrap="word",
        border_width=1,
        border_color=theme.GLASS_BORDER,
        corner_radius=8,
        height=max(80, height - 160),
    )
    box.pack(fill="both", expand=True, pady=(0, 16))
    box.insert("1.0", message)
    box.configure(state="disabled")

    btn(inner, text="OK", variant="primary", width=110, command=window.destroy).pack(anchor="e")

    _open_modal(parent, window, width, height)
    parent.wait_window(window)


def show_error(parent: ctk.CTk, title: str, message: str) -> None:
    show_info(parent, title, message)


def show_warning(parent: ctk.CTk, title: str, message: str) -> None:
    show_info(parent, title, message)
