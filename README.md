# CleanTrace — MultiPlotter pour bancs d'essai

Application de bureau légère (Python · Tkinter · Matplotlib) pour **importer, synchroniser,
nettoyer, corriger et exporter** les mesures d'essais d'endurance, de caractérisation
électrique et de qualification thermique (courant, tension, température, humidité).

Les filtres classiques transforment les créneaux de courant en pentes. CleanTrace, lui,
supprime le bruit de repos et les pics de saturation **sans déformer la dynamique réelle
du signal**.

---

## Démarrage rapide avec Spyder (Anaconda)

1. Télécharger le projet (bouton **Code → Download ZIP** sur GitHub), puis le dézipper.
2. Ouvrir **Spyder**, puis `Fichier → Ouvrir…` et choisir **`main.py`**.
3. Appuyer sur **F5** (ou ▶ *Exécuter*). La fenêtre CleanTrace s'ouvre.
4. Cliquer sur **Ouvrir des fichiers…** et essayer les fichiers du dossier `exemples/`.

> Anaconda fournit déjà tout ce qu'il faut : `numpy`, `pandas`, `scipy`, `matplotlib`
> et `tkinter`. Il n'y a rien à installer.
>
> Sans Anaconda : `pip install -r requirements.txt`, puis `python main.py`.

**En cas de souci dans Spyder** (fenêtre qui ne répond pas, ou lancée deux fois) :
`Exécution → Configuration par fichier… → Exécuter dans une console dédiée`, ou bien
`Exécuter dans un terminal système externe`.

---

## Fonctionnalités

| User story | Ce que fait CleanTrace | Code |
|---|---|---|
| **US-01** Import multi-formats | Détecte l'encodage (utf-8, cp1252, latin-1), le séparateur (`;` `,` tabulation), la décimale, l'en-tête (le préambule de la centrale est ignoré), la colonne temps (date/heure, `H:MM:SS`, ms / s / min, colonnes Date + Heure séparées, colonne `ms` Graphtec) et la période d'échantillonnage. Tous les fichiers sont recalés sur l'axe commun **`Time_min`** du fichier de référence (**Graphset**, sinon le plus long). Un fichier non conforme déclenche un message d'erreur explicite. | `cleantrace/loader.py` |
| **US-02** Sélection des voies | Arborescence par fichier avec cases à cocher (cliquer sur un fichier coche ou décoche toutes ses voies), boutons *Tout sélectionner* / *Tout désélectionner*, libellés nettoyés (`CH1` → `Channel 1 (mV)`), bouton *Réinitialiser* | `cleantrace/channels.py`, `app.py` |
| **US-03** Nettoyage automatique | ☑ *Bruit de repos* : forcé à 0 sous 10 mA / 5 mV pendant les phases d'arrêt. ☑ *Pics de saturation* : groupes étroits au-delà de 98 % du max, remplacés par l'enveloppe minimale SciPy (`minimum_filter1d` + `maximum_filter1d`) puis lissés par `gaussian_filter1d`. **Seuls les points parasites sont modifiés.** | `cleantrace/cleaning.py` |
| **US-04** Multi-axes | V / A à gauche, axes `twinx` dédiés à **°C** et **%HR**, temps au format `H:MM:SS`, curseur de **décalage temporel** des courbes climatiques (retard de l'enceinte), légende multi-colonnes au-delà de 20 voies | `cleantrace/plotting.py` |
| **US-05** Correction au clic | Un clic gauche sur un point abîmé le remplace par l'interpolation `y = y_g + α·(y_d − y_g)` de ses voisins, sans retracer le graphique (`draw_idle`). La correction est désactivée pendant le zoom ou le déplacement. | `cleantrace/editing.py` |
| **US-06** Export CSV | Voies cochées fusionnées sur `Time_min` (point le plus proche, tolérance d'une période), séparateur `;`, décimale `,`, colonne `H:MM:SS` en plus. Le fichier s'ouvre directement dans Excel. | `cleantrace/export.py` |

### Garanties du nettoyage (US-03)

- Un créneau de courant **reste un créneau** : pas de pente, pas de droite.
- Un plateau réel au maximum est plus large qu'un pic parasite (plus de 5 échantillons) :
  il n'est **jamais** modifié. La valeur max initiale et la valeur min finale de chaque
  cycle sont conservées.
- Les décharges exponentielles naturelles ne sont pas touchées.
- Le bouton *Restaurer les données brutes* annule nettoyages et corrections.

Les réglages fins (seuils, largeur max d'un pic, σ du lissage) se trouvent dans
`CleaningOptions` et `NOISE_THRESHOLDS` (`cleantrace/cleaning.py`).

---

## Fichiers d'exemple

Le dossier `exemples/` simule un essai batterie de 2 h (3 cycles charge / repos /
décharge), enregistré par 4 centrales :

| Fichier | Format |
|---|---|
| `essai_Graphset.csv` | Référence temps · `;` · décimale `,` · 1 s |
| `essai_Graphtec.csv` | Préambule centrale · `,` · `No./Time/ms/CH1..CH3` · 500 ms · **pics de saturation et bruit** |
| `essai_Nanodac.txt` | Tabulation · cp1252 · colonnes Date + Heure séparées · 10 s |
| `essai_Clim.csv` | Enceinte climatique · cp1252 · 1 min · **4 min de retard** (à recaler avec le curseur, à −4) |

Pour les régénérer : `python exemples/generer_exemples.py`.

---

## Structure du projet

```
cleantrace/
├── main.py                 ← à lancer (F5 dans Spyder)
├── requirements.txt
├── cleantrace/
│   ├── loader.py           US-01  import, détection de format, axe Time_min
│   ├── channels.py         US-02  libellés, unités, grandeurs physiques
│   ├── cleaning.py         US-03  bruit de repos, pics de saturation
│   ├── plotting.py         US-04  graphique multi-axes
│   ├── editing.py          US-05  correction au clic
│   ├── export.py           US-06  fusion et export CSV
│   ├── session.py          état de travail (sans IHM, testable)
│   └── app.py              interface Tkinter
├── exemples/               fichiers de démonstration
├── tests/                  tests automatiques (pytest)
├── tools/smoke_gui.py      test de bout en bout de l'interface
├── docker/                 environnement de développement
└── dev.sh
```

---

## Développement (Docker, rien à installer sur la machine)

Il suffit d'avoir Docker Desktop.

```bash
./dev.sh build      # construit l'image de dev (une fois)
./dev.sh test       # tests automatiques
./dev.sh gui        # lance l'appli → http://localhost:6080/vnc.html?autoconnect=1&resize=scale
./dev.sh smoke      # parcours complet de l'IHM + captures d'écran dans .dev-out/
./dev.sh shell      # terminal dans le conteneur
./dev.sh clean      # supprime l'image
```

## Licence

MIT. Voir [LICENSE](LICENSE).
