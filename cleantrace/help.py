"""Aide intégrée (bouton « ? ») : comment utiliser chaque partie de l'application."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .theme import C

SECTIONS = [
    ("Démarrer", """\
1. « Ouvrir des fichiers… » : choisissez un ou plusieurs exports (Graphtec, nanodac…).
   Ouvrez le fichier d'origine de l'appareil, sans le passer par Excel (Excel coupe
   au-delà de 1 048 576 lignes).
2. Cochez les voies à afficher. Cliquer sur un nom de fichier coche / décoche toutes
   ses voies.
3. Nettoyez, corrigez, puis « Exporter en CSV… » : seules les voies cochées sont
   exportées, avec les nettoyages et corrections."""),

    ("Nettoyage", """\
Le nettoyage s'applique aux voies COCHÉES, quand vous cliquez sur « Nettoyer… ».
Une fenêtre montre, voie par voie, le seuil utilisé et le nombre de points qui seront
modifiés AVANT d'appliquer (bouton « Aperçu »).

Ordre des traitements : 1. décalage de zéro, 2. pics parasites, 3. bruit de repos.
Chaque traitement appliqué est noté dans le journal (bouton « Journal »).

Décalage de zéro
  Si le niveau de repos d'une voie n'est pas exactement 0 (ex. −0,04 A au lieu de 0 :
  dérive du capteur ou du shunt), ce décalage est mesuré et soustrait à toute la voie.
  Il n'est proposé que pour les voies qui reviennent au repos près de 0 ; jamais pour
  une tension d'alimentation (24 V permanents) ni un petit courant permanent. La
  valeur est modifiable (ou à vider) dans la colonne « DÉCALAGE 0 ».

Pics parasites
  Un groupe de points est un pic parasite si :
  • il est étroit : 5 points consécutifs au plus (réglable ; à 100 ms, 5 points = 0,5 s) ;
  • il s'écarte du niveau de la courbe autour de lui de plus de 8 fois le bruit de mesure
    ET de plus de 5 % de l'amplitude utile de la voie (calculée sans les pics).
  Sa hauteur ne compte pas : un parasite de 1 A est retiré comme un de 10 A. Il est
  remplacé par le niveau de la courbe autour de lui (médiane locale). Rien d'autre n'est
  touché : créneaux, paliers, décharges et bruit normal restent identiques. Les trous
  courts (« +++++++ », « BURNOUT ») sont comblés par les points voisins.
  Option « Seulement la saturation » : ne retire que les pics au-delà de 98 % du maximum
  de la voie (règle d'origine du cahier des charges).
  Limites : un vrai phénomène plus court que la largeur réglée serait retiré ; un
  parasite plus large ne l'est pas (augmentez la largeur, ou corrigez au clic).

Bruit de repos (forcer à 0)
  Pendant les arrêts, un courant ou une tension oscille autour de 0 : les valeurs dont
  la valeur absolue est sous le SEUIL de la voie (au moins 3 points d'affilée) sont
  mises à 0. Le seuil est réglable voie par voie :
  • par défaut : 10 mA / 0,010 A / 5 mV / 0,005 V selon l'unité, SAUF si la voie ne
    revient jamais à 0 (« pas de repos à 0 ») : alors aucune mise à 0 ;
  • « Suggestion » : 1,5 × le bruit mesuré pendant les repos à 0 (« Utiliser les
    suggestions » remplit tous les seuils) ;
  • en rouge dans l'aperçu : plus de 90 % de la voie serait mise à 0 — à vérifier ;
  • seuil vide = pas de mise à 0 pour cette voie ;
  • ATTENTION aux petits courants : une voie qui mesure 3 mA en permanence serait
    entièrement mise à 0 avec un seuil de 10 mA.
  « 0 point » est normal sur une voie qui ne revient jamais à 0 (ex. courant toujours
  entre 80 et 160 mA).

Vérifier le résultat
  « Montrer les données brutes (en gris) » affiche, sous chaque voie nettoyée ou
  corrigée, ses données d'origine : on voit exactement ce qui a été modifié.

Annuler
  « Annuler le nettoyage » remet les données brutes : annule nettoyages ET corrections au clic des voies
  cochées."""),

    ("Correction au clic", """\
Clic gauche sur un point abîmé : il est remplacé par l'interpolation de ses deux
voisins. Désactivez d'abord la loupe / le déplacement de la barre d'outils (bouton
enfoncé = le clic sert à zoomer). Zoomez pour viser un point précis."""),

    ("Base de temps", """\
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
°C / %HR (nanodac) si l'enceinte réagit avec retard."""),

    ("Livrables pour le client", """\
Menu « Exporter » :
• Données nettoyées (CSV + journal) : le CSV « ; » des voies cochées, et à côté un fichier
  « …_journal.txt » qui liste tous les traitements appliqués (traçabilité).
• Image du graphique (PNG, PDF, SVG) : le graphique tel qu'affiché (même zoom), au
  format A4 paysage, pour l'insérer dans un rapport.
• Rapport PDF pour le client : synthèse (fichiers sources, appareils, périodes, base de
  temps), statistiques par voie sur la période affichée (min, max, moyenne,
  écart-type, points modifiés), graphique et journal des traitements.
Astuce : zoomez sur la période utile avant d'exporter l'image ou le rapport."""),

    ("En cas de problème", """\
Les longues opérations (ouverture, nettoyage, exports) affichent leur avancement ; la
fenêtre reste utilisable. En cas d'erreur, un message l'explique et les détails
techniques sont enregistrés dans le fichier « cleantrace_erreurs.log » de votre
dossier personnel (C:\\Users\\<vous>) : envoyez-le au développeur avec une capture."""),

    ("Fichier refusé", """\
Si un fichier n'est pas reconnu, le message indique ce qui a été lu. Répondez « Oui »
pour enregistrer un extrait (début et fin du fichier, quelques Ko) et envoyez-le au
développeur. Vérifiez aussi la version dans le titre de la fenêtre."""),
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
        self.title("Aide — CleanTrace")
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
        for title, body in SECTIONS:
            self.text.mark_set("section-" + title, self.text.index("end-1c"))
            self.text.mark_gravity("section-" + title, tk.LEFT)
            self.text.insert(tk.END, title + "\n", "title")
            self.text.insert(tk.END, body + "\n\n")
        self.text.configure(state=tk.DISABLED)
        ttk.Button(self, text="Fermer", style="Primary.TButton", command=self.destroy).pack(
            anchor=tk.E, padx=16, pady=(0, 16))

    def show(self, section: str) -> None:
        self.deiconify()
        self.lift()
        mark = "section-" + section
        if mark in self.text.mark_names():
            self.update_idletasks()
            self.text.yview(mark)
