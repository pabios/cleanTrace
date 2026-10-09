"""Aide intégrée (bouton « ? ») : comment utiliser chaque partie de l'application."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

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

Pics de saturation
  Un point est corrigé seulement si les 3 conditions sont réunies :
  • il est au-delà de 98 % du maximum de la voie (ou du minimum, côté négatif) ;
  • il fait partie d'un groupe de 5 points consécutifs au plus (au-delà, c'est un vrai
    palier) ;
  • il dépasse le niveau de la courbe autour de lui d'au moins 5 % de l'amplitude de
    la voie ET d'au moins 8 fois le bruit de mesure (le haut du bruit d'un palier réel
    n'est donc jamais pris pour un pic).
  Il est remplacé par le niveau de la courbe autour de lui (médiane locale). Rien d'autre n'est touché :
  créneaux, paliers et décharges restent identiques. Les trous courts (« +++++++ »,
  « BURNOUT ») sont comblés par les points voisins.
  Limites : un vrai pic de 5 points au plus qui atteint le maximum serait retiré ; un
  parasite qui ne monte pas près du maximum n'est pas détecté (corrigez-le au clic).

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

Annuler
  « Restaurer les données brutes » annule nettoyages ET corrections au clic des voies
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
        self.geometry("720x620")
        frame = ttk.Frame(self, padding=8)
        frame.pack(fill=tk.BOTH, expand=True)
        self.text = tk.Text(frame, wrap=tk.WORD, padx=10, pady=8, font=("TkDefaultFont", 10))
        scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.tag_configure("title", font=("TkDefaultFont", 12, "bold"), spacing1=10, spacing3=4)
        for title, body in SECTIONS:
            self.text.mark_set("section-" + title, self.text.index("end-1c"))
            self.text.mark_gravity("section-" + title, tk.LEFT)
            self.text.insert(tk.END, title + "\n", "title")
            self.text.insert(tk.END, body + "\n\n")
        self.text.configure(state=tk.DISABLED)
        ttk.Button(self, text="Fermer", command=self.destroy).pack(pady=(0, 8))

    def show(self, section: str) -> None:
        self.deiconify()
        self.lift()
        mark = "section-" + section
        if mark in self.text.mark_names():
            self.update_idletasks()
            self.text.yview(mark)
