from __future__ import annotations

import customtkinter as ctk
from PIL import Image, ImageDraw


def create_background_image(width: int, height: int) -> Image.Image:
    """Fondo plano. El blur de PIL congelaba PCs lentas junto a Sage."""
    width = max(width, 800)
    height = max(height, 600)
    img = Image.new("RGB", (width, height), "#F5F7FB")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, width, int(height * 0.42)), fill="#EEF3FA")
    return img


class GlassBackground(ctk.CTkLabel):
    """Capa de fondo estatica (sin regenerar en cada resize)."""

    def __init__(self, master: ctk.CTk, **kwargs) -> None:
        super().__init__(master, text="", **kwargs)
        self._ctk_image: ctk.CTkImage | None = None
        self.configure(fg_color="#F5F7FB")

    def place_fill(self) -> None:
        self.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.lower()
