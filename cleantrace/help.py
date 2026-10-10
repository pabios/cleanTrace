"""Aide intégrée (boutons « Aide » et « ? »), en français et en anglais."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .i18n import _, get_language
from .theme import C

# Clé de section (utilisée par les boutons « ? ») -> (titre FR, texte FR, titre EN, texte EN)
SECTIONS = [
    ("Démarrer", "Démarrer", """\
1. « Ouvrir des fichiers… » : choisissez un ou plusieurs exports (Graphtec, nanodac…).
   Ouvrez le fichier d'origine de l'appareil, sans le passer par Excel (Excel coupe
   au-delà de 1 048 576 lignes).
2. Cochez les voies à afficher. Cliquer sur un nom de fichier coche / décoche toutes
   ses voies. Chaque voie s'affiche sous le nom de la centrale : « Channel 4 ».
3. Nettoyez, corrigez, puis « Exporter » : seules les voies cochées sont exportées,
   avec les nettoyages et corrections.
4. Langue : liste « FR / EN » en haut à droite (choix mémorisé).""",
     "Getting started", """\
1. “Open files…”: choose one or more exports (Graphtec, nanodac…). Open the original
   file from the device, without going through Excel (Excel truncates beyond
   1,048,576 rows).
2. Tick the channels to display. Clicking a file name ticks / unticks all its
   channels. Each channel is shown with the data logger name: “Channel 4”.
3. Clean, correct, then “Export”: only ticked channels are exported, with their
   cleaning and corrections.
4. Language: “FR / EN” list at the top right (remembered)."""),

    ("Nettoyage", "Nettoyage", """\
Le nettoyage s'applique aux voies COCHÉES, quand vous cliquez sur « Nettoyer… ». La
fenêtre montre, voie par voie, ce qui sera modifié AVANT d'appliquer (« Aperçu »).
Tout est noté dans le journal et tout est réversible (« Annuler le nettoyage »).

Pics parasites (activé par défaut)
  Un groupe de points est un pic parasite s'il est étroit (5 points au plus, réglable ;
  à 100 ms, 5 points = 0,5 s) et s'il s'écarte nettement de la courbe des deux côtés
  (plus de 8 fois le bruit de mesure). Sa hauteur ne compte pas : un parasite de 1 A
  est retiré comme un de 10 A. Il est remplacé par le niveau de la courbe autour de lui.
  Les fronts de créneaux, paliers et décharges ne sont jamais touchés. Les trous courts
  (« +++++++ », « BURNOUT ») sont comblés par les points voisins.
  Option « Seulement la saturation » : ne retire que les pics au-delà de 98 % du max.

Réduire le bruit (activé par défaut : LISSAGE)
  Le bruit est lissé morceau par morceau entre les fronts : un créneau reste vertical,
  un palier garde sa valeur moyenne mesurée, une décharge garde sa forme. RIEN n'est
  mis à 0 : un petit courant réel (même 5 mA) est conservé. « Lissage sur … points »
  règle la force du lissage (plus de points = plus lisse).
  Option « Forcer à 0 sous le seuil » (règle d'origine) : pendant les repos, les valeurs
  sous le seuil de la voie sont mises à 0. Le seuil est calculé sur le bruit réel de
  chaque voie (colonne « Suggestion »). En rouge : plus de 90 % de la voie serait mise
  à 0 — c'est sans doute un vrai signal.

Décalage de zéro (option, désactivé par défaut)
  Si le repos d'une voie n'est pas exactement à 0 (ex. −0,04 A), ce niveau peut être
  soustrait à toute la voie. À n'utiliser que si vous êtes sûr qu'il s'agit d'une dérive
  du capteur et non d'un vrai courant.

Vérifier le résultat
  « Montrer les données brutes (en gris) » affiche, sous chaque voie nettoyée ou
  corrigée, ses données d'origine : on voit exactement ce qui a été modifié.""",
     "Cleaning", """\
Cleaning applies to the TICKED channels when you click “Clean…”. The window shows,
channel by channel, what will change BEFORE applying (“Preview”). Everything is
recorded in the log and can be undone (“Undo cleaning”).

Spurious spikes (on by default)
  A group of points is a spurious spike if it is narrow (5 points at most, adjustable;
  at 100 ms, 5 points = 0.5 s) and clearly departs from the curve on both sides (more
  than 8 times the measurement noise). Its height does not matter: a 1 A spike is
  removed like a 10 A one. It is replaced by the surrounding curve level. Square-wave
  edges, plateaus and discharges are never touched. Short gaps (“+++++++”,
  “BURNOUT”) are filled from neighbouring points.
  Option “Saturation only”: removes only spikes above 98 % of the maximum.

Reduce noise (on by default: SMOOTHING)
  Noise is smoothed piece by piece between edges: a square wave stays vertical, a
  plateau keeps its measured mean value, a discharge keeps its shape. NOTHING is set to
  0: a small real current (even 5 mA) is kept. “Smoothing over … points” sets the
  strength (more points = smoother).
  Option “Force to 0 below the threshold” (original rule): during rest phases, values
  below the channel threshold are set to 0. The threshold is computed from each
  channel's real noise (“Suggestion” column). In red: more than 90 % of the channel
  would be set to 0 — it is probably a real signal.

Zero offset (optional, off by default)
  If a channel's rest level is not exactly 0 (e.g. −0.04 A), this level can be
  subtracted from the whole channel. Use it only if you are sure it is a sensor drift
  and not a real current.

Checking the result
  “Show raw data (in grey)” displays, under each cleaned or corrected channel, its
  original data: you see exactly what was changed."""),

    ("Correction au clic", "Correction au clic", """\
Clic gauche sur un point abîmé : il est remplacé par l'interpolation de ses deux
voisins. Désactivez d'abord la loupe / le déplacement de la barre d'outils (bouton
enfoncé = le clic sert à zoomer). Zoomez pour viser un point précis.""",
     "Click correction", """\
Left-click a damaged point: it is replaced by the interpolation of its two
neighbours. First disable the zoom / pan tool of the toolbar (pressed button = the
click zooms). Zoom in to target a precise point."""),

    ("Base de temps", "Base de temps", """\
Pour superposer plusieurs fichiers :
• Heure réelle : chaque mesure à son heure (même essai, appareils à l'heure).
• Période commune : seulement la période où tous les fichiers mesurent ; ils
  commencent et finissent ensemble.
• Débuts à 0 : chaque fichier démarre à 0 (horloges pas à l'heure).
• Durée étirée : chaque fichier de 0 à 100 % de sa durée, pour comparer la forme de
  deux essais (le temps est déformé).
Grille d'export : celle du fichier de référence, ou une grille commune (100 ms, 1 s…)
pour avoir une valeur de chaque appareil sur chaque ligne (mesure la plus proche).

Décalage enceinte climatique : décale les courbes des fichiers ne contenant que des
°C / %HR (nanodac) si l'enceinte réagit avec retard.""",
     "Time base", """\
To overlay several files:
• Real time: each measurement at its clock time (same test, devices on time).
• Common period: only the period where all files are recording; they start and
  end together.
• Starts at 0: each file starts at 0 (device clocks not set).
• Stretched duration: each file from 0 to 100 % of its duration, to compare the
  shape of two tests (time is distorted).
Export grid: the reference file's grid, or a common grid (100 ms, 1 s…) to get one
value from each device on every row (nearest measurement).

Climatic chamber shift: shifts the curves of files that only contain °C / %RH
(nanodac) if the chamber lags."""),

    ("Livrables pour le client", "Livrables pour le client", """\
Menu « Exporter » :
• Données nettoyées (CSV + journal) : le CSV « ; » des voies cochées, et à côté un fichier
  « …_journal.txt » qui liste tous les traitements appliqués (traçabilité).
• Image du graphique (PNG, PDF, SVG) : le graphique tel qu'affiché (même zoom), au
  format A4 paysage, pour l'insérer dans un rapport.
• Rapport PDF pour le client : synthèse (fichiers sources, appareils, périodes, base de
  temps), statistiques par voie sur la période affichée (min, max, moyenne,
  écart-type, points modifiés), graphique et journal des traitements.
Astuce : zoomez sur la période utile avant d'exporter l'image ou le rapport.""",
     "Customer deliverables", """\
“Export” menu:
• Cleaned data (CSV + log): the “;” CSV of the ticked channels, plus a
  “…_journal.txt” file listing every treatment applied (traceability).
• Chart image (PNG, PDF, SVG): the chart as displayed (same zoom), A4 landscape, to
  insert in a report.
• PDF report for the customer: summary (source files, devices, periods, time base),
  per-channel statistics over the period shown (min, max, mean, standard deviation,
  modified points), chart and processing log.
Tip: zoom on the useful period before exporting the image or the report."""),

    ("En cas de problème", "En cas de problème", """\
Les longues opérations (ouverture, nettoyage, exports) affichent leur avancement ; la
fenêtre reste utilisable. En cas d'erreur, un message l'explique et les détails
techniques sont enregistrés dans le fichier « cleantrace_erreurs.log » de votre
dossier personnel (C:\\Users\\<vous>) : envoyez-le au développeur avec une capture.

Fichier refusé : le message indique ce qui a été lu. Répondez « Oui » pour enregistrer
un extrait (début et fin du fichier, quelques Ko) et envoyez-le au développeur.
Vérifiez aussi la version dans le titre de la fenêtre.""",
     "Troubleshooting", """\
Long operations (opening, cleaning, exports) show their progress; the window stays
usable. If an error occurs, a message explains it and the technical details are saved
to the “cleantrace_erreurs.log” file in your home folder (C:\\Users\\<you>): send it to
the developer with a screenshot.

Rejected file: the message shows what was read. Answer “Yes” to save an excerpt
(beginning and end of the file, a few KB) and send it to the developer. Also check
the version in the window title."""),
]


class HelpWindow(tk.Toplevel):
    """Fenêtre d'aide ; ``show(section)`` fait défiler jusqu'à une section."""

    _instance = None

    @classmethod
    def open(cls, master, section: str = "Démarrer") -> "HelpWindow":
        if cls._instance is None or not cls._instance.winfo_exists():
            cls._instance = cls(master)
        cls._instance.show(section)
        return cls._instance

    def __init__(self, master):
        super().__init__(master)
        english = get_language() == "en"
        self.title(_("Aide") + " — CleanTrace")
        self.geometry("760x660")
        self.configure(background=C["background"])
        outer = tk.Frame(self, background=C["card"], highlightbackground=C["border"], highlightthickness=1)
        outer.pack(fill=tk.BOTH, expand=True, padx=16, pady=(16, 8))
        frame = ttk.Frame(outer, style="Card.TFrame", padding=4)
        frame.pack(fill=tk.BOTH, expand=True)
        self.text = tk.Text(frame, wrap=tk.WORD, padx=18, pady=12, font=("TkDefaultFont", 10), relief=tk.FLAT,
                            background=C["card"], foreground=C["fg_soft"], highlightthickness=0, bd=0,
                            spacing1=1, spacing3=1)
        scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.tag_configure("title", font=("TkDefaultFont", 13, "bold"), foreground=C["fg"],
                                spacing1=14, spacing3=6)
        for key, title_fr, body_fr, title_en, body_en in SECTIONS:
            self.text.mark_set("section-" + key, self.text.index("end-1c"))
            self.text.mark_gravity("section-" + key, tk.LEFT)
            self.text.insert(tk.END, (title_en if english else title_fr) + "\n", "title")
            self.text.insert(tk.END, (body_en if english else body_fr) + "\n\n")
        self.text.configure(state=tk.DISABLED)
        ttk.Button(self, text=_("Fermer"), style="Primary.TButton", command=self.destroy).pack(
            anchor=tk.E, padx=16, pady=(0, 16))

    def show(self, section: str) -> None:
        self.deiconify()
        self.lift()
        mark = "section-" + section
        if mark in self.text.mark_names():
            self.update_idletasks()
            self.text.yview(mark)
