from __future__ import annotations

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFilter


def create_background_image(width: int, height: int) -> Image.Image:
    """Fondo claro con gradiente suave para el efecto glass."""
    width = max(width, 800)
    height = max(height, 600)
    img = Image.new("RGB", (width, height), "#F5F7FB")

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.rectangle((0, 0, width, int(height * 0.42)), fill=(224, 236, 255, 150))
    odraw.rectangle((0, int(height * 0.42), width, height), fill=(248, 250, 252, 120))

    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=70))
    base = img.convert("RGBA")
    base = Image.alpha_composite(base, overlay)

    wash = Image.new("RGBA", (width, height), (255, 255, 255, 30))
    base = Image.alpha_composite(base, wash)

    return base.convert("RGB")


class GlassBackground(ctk.CTkLabel):
    """Capa de fondo que se redimensiona con la ventana."""

    def __init__(self, master: ctk.CTk, **kwargs) -> None:
        super().__init__(master, text="", **kwargs)
        self._ctk_image: ctk.CTkImage | None = None
        self._pil_image: Image.Image | None = None
        self._last_size = (0, 0)
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, event) -> None:
        if event.width < 100 or event.height < 100:
            return
        if (event.width, event.height) == self._last_size:
            return
        self._last_size = (event.width, event.height)
        self._pil_image = create_background_image(event.width, event.height)
        self._ctk_image = ctk.CTkImage(
            light_image=self._pil_image,
            dark_image=self._pil_image,
            size=(event.width, event.height),
        )
        self.configure(image=self._ctk_image)

    def place_fill(self) -> None:
        self.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.lower()
