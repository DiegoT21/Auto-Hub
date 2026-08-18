from __future__ import annotations

import customtkinter as ctk

from app import theme
from app.components import btn, glass_card


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

    window = ctk.CTkToplevel(parent)
    window.title(title)
    window.geometry("420x180")
    window.resizable(False, False)
    window.transient(parent)
    window.grab_set()

    window.configure(fg_color=theme.BG_DARK)
    frame = glass_card(window, radius=theme.BENTO_RADIUS)
    frame.pack(fill="both", expand=True, padx=16, pady=16)
    inner = ctk.CTkFrame(frame, fg_color="transparent")
    inner.pack(fill="both", expand=True, padx=20, pady=20)

    ctk.CTkLabel(inner, text=message, wraplength=360, font=theme.FONT_BODY).pack(anchor="w", pady=(0, 20))

    buttons = ctk.CTkFrame(inner, fg_color="transparent")
    buttons.pack(fill="x")

    def on_yes() -> None:
        result[0] = True
        window.destroy()

    def on_no() -> None:
        window.destroy()

    btn(buttons, text="Cancelar", variant="ghost", width=100, command=on_no).pack(side="right", padx=(8, 0))
    btn(buttons, text="Confirmar", variant="primary", width=100, command=on_yes).pack(side="right")

    parent.wait_window(window)
    return result[0]


def show_info(parent: ctk.CTk, title: str, message: str) -> None:
    window = ctk.CTkToplevel(parent)
    window.title(title)
    window.geometry("460x200")
    window.resizable(False, False)
    window.transient(parent)
    window.grab_set()

    window.configure(fg_color=theme.BG_DARK)
    shell = glass_card(window, radius=theme.BENTO_RADIUS)
    shell.pack(fill="both", expand=True, padx=16, pady=16)
    frame = ctk.CTkFrame(shell, fg_color="transparent")
    frame.pack(fill="both", expand=True, padx=20, pady=20)

    ctk.CTkLabel(frame, text=message, wraplength=400, justify="left", font=theme.FONT_BODY).pack(
        anchor="w", pady=(0, 20)
    )
    btn(frame, text="OK", variant="primary", width=100, command=window.destroy).pack(anchor="e")

    parent.wait_window(window)


def show_error(parent: ctk.CTk, title: str, message: str) -> None:
    show_info(parent, title, message)


def show_warning(parent: ctk.CTk, title: str, message: str) -> None:
    show_info(parent, title, message)
