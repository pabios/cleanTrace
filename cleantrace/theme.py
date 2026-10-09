"""Thème visuel de CleanTrace, inspiré de shadcn/ui : palette zinc, cartes, boutons.

Tkinter pur (aucune dépendance en plus) : un style ``ttk`` « clam » entièrement
reconfiguré, et quelques composants (carte, case à cocher dessinée, zone défilante).
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from typing import Dict, Optional, Tuple

# Jetons de couleur (zinc, comme shadcn/ui)
C = {
    "background": "#fafafa",  # fond de l'application
    "card": "#ffffff",  # cartes, graphique
    "border": "#e4e4e7",
    "border_strong": "#d4d4d8",
    "muted": "#f4f4f5",  # survol, fonds discrets
    "muted_fg": "#71717a",  # texte secondaire
    "fg": "#09090b",  # texte
    "fg_soft": "#3f3f46",
    "primary": "#18181b",  # bouton principal
    "primary_hover": "#3f3f46",
    "primary_fg": "#fafafa",
    "ring": "#a1a1aa",
    "destructive": "#dc2626",
    "success": "#16a34a",
}

# Couleurs des courbes (Tailwind 600) : lisibles sur fond blanc, bien distinctes
SERIES_COLORS = [
    "#2563eb", "#ea580c", "#059669", "#7c3aed", "#e11d48", "#0891b2", "#ca8a04",
    "#4f46e5", "#db2777", "#65a30d", "#0d9488", "#9333ea", "#c2410c", "#475569",
]
TEMPERATURE_COLOR = "#dc2626"
HUMIDITY_COLOR = "#2563eb"


class Fonts:
    """Polices de l'interface (police système : Segoe UI sous Windows)."""

    def __init__(self, root: tk.Misc):
        families = set(tkfont.families(root))
        candidates = ["Segoe UI", "SF Pro Text", "Helvetica Neue", "Inter", "Cantarell", "DejaVu Sans"]
        family = next((f for f in candidates if f in families), tkfont.nametofont("TkDefaultFont").actual("family"))
        semibold = "Segoe UI Semibold" if sys.platform == "win32" and "Segoe UI Semibold" in families else family
        weight = "normal" if semibold != family else "bold"
        self.base = (family, 10)
        self.small = (family, 9)
        self.strong = (semibold, 10, weight)
        self.title = (semibold, 11, weight)
        self.brand = (semibold, 14, weight)
        self.mono = ("Consolas" if sys.platform == "win32" else "DejaVu Sans Mono", 9)


def apply_theme(root: tk.Tk) -> Fonts:
    """Configure tous les styles ttk de l'application. Renvoie les polices."""
    fonts = Fonts(root)
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        tkfont.nametofont(name).configure(family=fonts.base[0], size=fonts.base[1])
    root.configure(background=C["background"])
    root.option_add("*TCombobox*Listbox.background", C["card"])
    root.option_add("*TCombobox*Listbox.foreground", C["fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", C["muted"])
    root.option_add("*TCombobox*Listbox.selectForeground", C["fg"])
    root.option_add("*TCombobox*Listbox.font", fonts.base)
    root.option_add("*TCombobox*Listbox.borderWidth", 0)

    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=C["background"], foreground=C["fg"], font=fonts.base,
                bordercolor=C["border"], lightcolor=C["card"], darkcolor=C["card"],
                troughcolor=C["muted"], focuscolor=C["ring"], selectbackground=C["muted"],
                selectforeground=C["fg"], insertcolor=C["fg"], borderwidth=1)

    # Cadres et textes
    s.configure("TFrame", background=C["background"])
    s.configure("Card.TFrame", background=C["card"])
    s.configure("TLabel", background=C["background"])
    s.configure("Card.TLabel", background=C["card"])
    s.configure("Title.Card.TLabel", background=C["card"], font=fonts.title)
    s.configure("Strong.Card.TLabel", background=C["card"], font=fonts.strong)
    s.configure("Muted.Card.TLabel", background=C["card"], foreground=C["muted_fg"], font=fonts.small)
    s.configure("Muted.TLabel", background=C["background"], foreground=C["muted_fg"], font=fonts.small)
    s.configure("Brand.TLabel", background=C["card"], font=fonts.brand)
    s.configure("Badge.TLabel", background=C["muted"], foreground=C["fg_soft"], font=fonts.small, padding=(6, 1))

    # Boutons : contour (par défaut), principal (noir), discret
    s.configure("TButton", background=C["card"], foreground=C["fg"], bordercolor=C["border"],
                lightcolor=C["card"], darkcolor=C["card"], padding=(12, 6), focusthickness=0,
                focuscolor=C["card"])
    s.map("TButton",
          background=[("disabled", C["card"]), ("pressed", C["border"]), ("active", C["muted"])],
          lightcolor=[("pressed", C["border"]), ("active", C["muted"])],
          darkcolor=[("pressed", C["border"]), ("active", C["muted"])],
          foreground=[("disabled", C["ring"])])
    s.configure("Primary.TButton", background=C["primary"], foreground=C["primary_fg"],
                bordercolor=C["primary"], lightcolor=C["primary"], darkcolor=C["primary"],
                focuscolor=C["primary"])
    s.map("Primary.TButton",
          background=[("disabled", C["ring"]), ("pressed", C["fg"]), ("active", C["primary_hover"])],
          lightcolor=[("disabled", C["ring"]), ("pressed", C["fg"]), ("active", C["primary_hover"])],
          darkcolor=[("disabled", C["ring"]), ("pressed", C["fg"]), ("active", C["primary_hover"])],
          bordercolor=[("disabled", C["ring"]), ("active", C["primary_hover"])],
          foreground=[("disabled", C["muted"])])
    s.configure("Ghost.TButton", background=C["card"], bordercolor=C["card"], lightcolor=C["card"],
                darkcolor=C["card"])
    s.map("Ghost.TButton", bordercolor=[("active", C["muted"])], background=[("active", C["muted"])])
    s.configure("Small.TButton", padding=(8, 3), font=fonts.small)
    s.configure("Icon.TButton", padding=(7, 3))

    # Champs
    for style in ("TEntry", "TSpinbox", "TCombobox"):
        s.configure(style, fieldbackground=C["card"], background=C["card"], bordercolor=C["border_strong"],
                    lightcolor=C["card"], darkcolor=C["card"], arrowcolor=C["muted_fg"], padding=(6, 4),
                    selectbackground=C["muted"], selectforeground=C["fg"])
        s.map(style, bordercolor=[("focus", C["ring"])], lightcolor=[("focus", C["card"])],
              fieldbackground=[("readonly", C["card"])], selectbackground=[("readonly", C["card"])],
              background=[("active", C["muted"])], arrowcolor=[("disabled", C["ring"])])

    # Curseur, barre de progression, barres de défilement
    s.configure("Horizontal.TScale", background=C["primary"], troughcolor=C["border"],
                bordercolor=C["border"], lightcolor=C["primary"], darkcolor=C["primary"], sliderlength=14,
                gripcount=0, troughrelief="flat", sliderrelief="flat", borderwidth=0)
    s.map("Horizontal.TScale", background=[("disabled", C["ring"])])
    s.configure("Horizontal.TProgressbar", background=C["primary"], troughcolor=C["muted"],
                bordercolor=C["muted"], lightcolor=C["primary"], darkcolor=C["primary"], thickness=4)
    for orient in ("Vertical", "Horizontal"):
        s.configure(orient + ".TScrollbar", background=C["border"], troughcolor=C["card"],
                    bordercolor=C["card"], lightcolor=C["border"], darkcolor=C["border"],
                    arrowcolor=C["muted_fg"], gripcount=0, arrowsize=11)
        s.map(orient + ".TScrollbar", background=[("active", C["border_strong"])])

    # Tableau des voies
    s.configure("Treeview", background=C["card"], fieldbackground=C["card"], foreground=C["fg"],
                bordercolor=C["card"], lightcolor=C["card"], darkcolor=C["card"], rowheight=26,
                font=fonts.base, indent=14)
    s.map("Treeview", background=[("selected", C["card"])], foreground=[("selected", C["fg"])])
    s.configure("Treeview.Heading", background=C["card"], foreground=C["muted_fg"], font=fonts.small,
                bordercolor=C["border"], lightcolor=C["card"], darkcolor=C["card"], relief="flat",
                padding=(4, 4))
    s.map("Treeview.Heading", background=[("active", C["card"])])
    s.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])  # sans cadre

    # Case à cocher : même dessin que dans le tableau des voies
    images = CheckImages(root)
    # Référence gardée sur la fenêtre : sans elle, Python libère les images et Tk ne les affiche plus
    root._cleantrace_check_images = (images.get("off", size=16), images.get("on", size=16))
    for style, bg in (("TCheckbutton", C["background"]), ("Card.TCheckbutton", C["card"])):
        element = "CleanTrace{}.indicator".format(style.split(".")[0] if "." in style else "")
        try:
            off, on = root._cleantrace_check_images
            s.element_create(element, "image", off, ("selected", on), border=0, sticky="")
        except tk.TclError:  # déjà créé (fenêtre rouverte dans la même session)
            pass
        s.layout(style, [("Checkbutton.padding", {"sticky": "nswe", "children": [
            (element, {"side": "left", "sticky": ""}),
            ("Checkbutton.label", {"side": "left", "sticky": "nswe"}),
        ]})])
        s.configure(style, background=bg, padding=(0, 3), focuscolor=bg)
        s.map(style, background=[("active", bg)])

    s.configure("TPanedwindow", background=C["background"])
    s.configure("Sash", sashthickness=8, background=C["background"], gripcount=0)
    return fonts


def card(parent, title: str = "", description: str = "", padding: int = 14, actions=None):
    """Carte blanche bordée (comme un <Card> shadcn). Renvoie (cadre extérieur, contenu).

    ``actions(header)`` peut ajouter des boutons à droite du titre.
    """
    outer = bordered(parent)
    body = ttk.Frame(outer, style="Card.TFrame", padding=padding)
    body.pack(fill=tk.BOTH, expand=True)
    if title:
        header = ttk.Frame(body, style="Card.TFrame")
        header.pack(fill=tk.X)
        if actions:  # à droite du titre, placées en premier pour ne jamais être masquées
            buttons = ttk.Frame(header, style="Card.TFrame")
            buttons.pack(side=tk.RIGHT, anchor=tk.N)
            actions(buttons)
        text = ttk.Frame(header, style="Card.TFrame")
        text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(text, text=title, style="Title.Card.TLabel").pack(anchor=tk.W)
        if description:
            ttk.Label(text, text=description, style="Muted.Card.TLabel", wraplength=230 if actions else 320,
                      justify=tk.LEFT).pack(anchor=tk.W, pady=(1, 0))
        ttk.Frame(body, style="Card.TFrame", height=10).pack(fill=tk.X)
    return outer, body


def bordered(parent) -> tk.Frame:
    """Cadre blanc avec une bordure fine (identique avec ou sans focus)."""
    return tk.Frame(parent, background=C["card"], highlightbackground=C["border"],
                    highlightcolor=C["border"], highlightthickness=1, bd=0, takefocus=0)


def separator(parent, background: str = None) -> tk.Frame:
    line = tk.Frame(parent, height=1, background=background or C["border"], bd=0)
    line.pack(fill=tk.X)
    return line


class ScrollFrame(ttk.Frame):
    """Zone à défilement vertical (panneau latéral sur petit écran)."""

    def __init__(self, parent, width: int = 360):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, background=C["background"], highlightthickness=0, bd=0, width=width)
        self.scrollbar = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor=tk.NW)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._scrollbar_shown = False
        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.bind_all("<MouseWheel>", self._on_wheel, add="+")
        self.bind_all("<Button-4>", self._on_wheel, add="+")
        self.bind_all("<Button-5>", self._on_wheel, add="+")

    def _on_canvas(self, event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)
        self._on_inner()

    def _on_inner(self, _event=None) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        needs = self.inner.winfo_reqheight() > self.canvas.winfo_height() > 1
        if needs and not self._scrollbar_shown:
            # placée avant le canvas : sinon il a déjà pris toute la place
            self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y, before=self.canvas)
            self._scrollbar_shown = True
        elif not needs and self._scrollbar_shown:
            self.scrollbar.pack_forget()
            self._scrollbar_shown = False

    def _on_wheel(self, event) -> None:
        widget = event.widget
        # Ne défile que si la souris est au-dessus du panneau (et pas dans le tableau des voies)
        try:
            path = str(widget)
        except Exception:
            return
        if not path.startswith(str(self)) or isinstance(widget, ttk.Treeview):
            return
        if not self._scrollbar_shown:
            return
        step = -1 if (getattr(event, "num", 0) == 4 or getattr(event, "delta", 0) > 0) else 1
        self.canvas.yview_scroll(step, "units")


class CheckImages:
    """Images des lignes du tableau : case à cocher dessinée + pastille de la couleur de la courbe."""

    SIZE = (34, 16)

    def __init__(self, master):
        self.master = master
        self._cache: Dict[Tuple[str, Optional[str]], tk.PhotoImage] = {}

    def get(self, state: str, color: Optional[str] = None, size: Optional[int] = None) -> tk.PhotoImage:
        """``state`` : "on", "off" ou "partial" ; ``size`` : largeur (case seule : 16 + marge)."""
        key = (state, color, size)
        if key not in self._cache:
            self._cache[key] = self._draw(state, color, size)
        return self._cache[key]

    def _draw(self, state, color, size=None):
        w, h = self.SIZE
        if size:
            w = size + 8  # case seule + espace avant le texte
        px = [[C["card"]] * w for _ in range(h)]
        x0, y0, size = 1, 1, 14
        for y in range(y0, y0 + size):
            for x in range(x0, x0 + size):
                edge = x in (x0, x0 + size - 1) or y in (y0, y0 + size - 1)
                corner = (x in (x0, x0 + size - 1)) and (y in (y0, y0 + size - 1))
                if corner:
                    continue  # coins arrondis
                if state == "off":
                    px[y][x] = C["ring"] if edge else C["card"]
                else:
                    px[y][x] = C["primary"]
        if state == "on":  # coche blanche
            for x, y in [(4, 8), (5, 9), (6, 10), (7, 9), (8, 8), (9, 7), (10, 6), (11, 5),
                         (4, 7), (5, 8), (6, 9), (7, 8), (8, 7), (9, 6), (10, 5), (11, 4)]:
                px[y][x] = C["primary_fg"]
        elif state == "partial":
            for x in range(4, 12):
                px[7][x] = px[8][x] = C["primary_fg"]
        if color and w >= 30:  # pastille de la courbe
            cx, cy, r = 25, 8, 4.2
            for y in range(h):
                for x in range(20, w):
                    if (x - cx) ** 2 + (y - cy + 0.5) ** 2 <= r * r:
                        px[y][x] = color
        img = tk.PhotoImage(master=self.master, width=w, height=h)
        img.put(" ".join("{" + " ".join(row) + "}" for row in px))
        return img
