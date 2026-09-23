"""Incremental history: keep existing widgets and the reader's scroll anchor."""
import json
from collections import Counter
import customtkinter as ctk
from app import theme
from app.components import invoice_card


def card_keys(cards):
    seen = Counter()
    result = []
    for card in cards:
        key = json.dumps(card, sort_keys=True, ensure_ascii=False)
        seen[key] += 1
        result.append(((key, seen[key]), card))
    return result


class HistoryPanel:
    def __init__(self, host):
        self.host = host
        self.sections = {}
        self.last = None
        self.groups = []
        for child in host.winfo_children():
            child.destroy()
        host.grid_columnconfigure(0, weight=1)

    def update(self, groups):
        signature = tuple((title, tuple(key for key, _ in card_keys(cards))) for title, cards in groups)
        if signature == self.last:
            return
        self.last = signature
        self.groups = groups
        canvas = self.host._parent_canvas
        at_top = canvas.yview()[0] <= 0.001
        anchor = None
        if not at_top:
            top = canvas.winfo_rooty()
            for section in self.sections.values():
                for widget in section["widgets"].values():
                    if (widget.winfo_rooty() + widget.winfo_height() > top
                            and widget.winfo_rooty() < top + canvas.winfo_height()):
                        anchor = (widget, widget.winfo_rooty())
                        break
                if anchor:
                    break
        for pos, (title, cards) in enumerate(groups):
            section = self.sections.get(title)
            if section is None:
                frame = ctk.CTkFrame(self.host, fg_color="transparent")
                frame.grid(row=pos, column=0, sticky="ew")
                frame.grid_columnconfigure(0, weight=1)
                historical = title == "Historial de intentos fallidos"
                label = (ctk.CTkButton(frame, text="", command=lambda t=title: self.toggle(t))
                         if historical else ctk.CTkLabel(frame, text="", font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED))
                label.grid(row=0, column=0, sticky="w", pady=4)
                more = ctk.CTkButton(frame, text="Mostrar mas", command=lambda t=title: self.more(t))
                section = self.sections[title] = dict(frame=frame, label=label, more=more,
                    widgets={}, limit=50, count=len(cards), collapsed=historical)
            # New logs must not evict cards that the user was reading.
            section["limit"] += max(0, len(cards) - section["count"])
            section["count"] = len(cards)
            section["label"].configure(text=("Mostrar " if section["collapsed"] else "") + f"{title} ({len(cards)})")
            desired = [] if section["collapsed"] else list(reversed(card_keys(cards)))[:section["limit"]]
            wanted = {key for key, _ in desired}
            widgets = section["widgets"]
            for key in list(widgets):
                if key not in wanted:
                    widgets.pop(key).destroy()
            for row, (key, payload) in enumerate(desired, 1):
                if key not in widgets:
                    widgets[key] = invoice_card(section["frame"], payload)
                widgets[key].grid(row=row, column=0, sticky="ew", pady=(0, 4))
            remaining = len(cards) - len(desired)
            if remaining and not section["collapsed"]:
                section["more"].configure(text=f"Mostrar mas ({remaining} restantes)")
                section["more"].grid(row=len(desired) + 1, column=0, sticky="ew", pady=6)
            else:
                section["more"].grid_remove()
        def restore():
            if not self.host.winfo_exists():
                return
            if at_top:
                canvas.yview_moveto(0)
            elif anchor and anchor[0].winfo_exists():
                delta = anchor[0].winfo_rooty() - anchor[1]
                box = canvas.bbox("all")
                if box and box[3] > box[1]:
                    canvas.yview_moveto((canvas.canvasy(0) + delta - box[1]) / (box[3] - box[1]))
        self.host.after_idle(restore)

    def more(self, title):
        self.sections[title]["limit"] += 50
        self.last = None
        self.update(self.groups)

    def toggle(self, title):
        section = self.sections[title]
        section["collapsed"] = not section["collapsed"]
        self.last = None
        self.update(self.groups)
