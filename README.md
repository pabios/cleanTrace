# CleanTrace

Nettoyer les mesures de bancs d'essai **sans déformer le signal**.

Importe les fichiers de plusieurs centrales (Graphtec, Nanodac, Graphset, enceinte
climatique…), les recale sur un même axe temps, supprime le bruit et les pics de
saturation, puis exporte un CSV propre.

![Signal brut](docs/captures/1-signal-brut.png)
*Avant : pics de saturation parasites à ±1000 mV.*

![Signal nettoyé](docs/captures/2-signal-nettoye.png)
*Après « Nettoyer » : les créneaux restent intacts et le repos est à 0.*

---

## Lancer l'application

### Avec Spyder (Anaconda)

1. Télécharger le projet : **Code → Download ZIP**, puis dézipper.
2. Dans Spyder : **Fichier → Ouvrir… → `main.py`**.
3. Appuyer sur **F5**.

Rien à installer : Anaconda contient déjà tout.

### Sans Anaconda

```bash
pip install -r requirements.txt
python main.py
```

---

## Utilisation

1. **Ouvrir des fichiers…** (essayer ceux du dossier `exemples/`).
2. Cocher les voies à afficher.
3. **Nettoyer** : supprime le bruit de repos (< 10 mA, < 5 mV) et les pics de saturation.
4. **Clic gauche** sur un point abîmé pour le corriger (interpolation avec ses voisins).
5. Curseur **Décalage enceinte climatique** : recale les courbes du nanodac si l'enceinte est en retard.
6. **Exporter en CSV…** : fichier `;` prêt pour Excel.

![Multi-axes](docs/captures/3-multi-axes.png)
*Toutes les voies : V / A à gauche, °C et %HR à droite.*

---

## Formats reconnus

Prévu pour les enregistreurs **Graphtec GL980** (export CSV, tableau « Amp settings »,
valeurs hors échelle `+++++++`) et **Eurotherm nanodac** (archive CSV, date en texte ou
en nombre Excel, tabulation ou virgule). Un exemple de chacun est fourni dans `exemples/`.

Les gros fichiers (plusieurs millions de lignes) sont lus en quelques secondes, avec un
indicateur de chargement.

Plus généralement : CSV, TXT ou DAT · séparateur `;` `,` ou tabulation · encodage utf-8,
cp1252 ou latin-1 · temps en date/heure, `H:MM:SS`, ms, s ou min. Tout est détecté
automatiquement.

Un fichier ne s'ouvre pas ? Ouvrez une issue en joignant le fichier (quelques lignes suffisent).

---

## Développement

Tout se passe dans Docker : rien à installer sur la machine.

```bash
./dev.sh build   # une fois
./dev.sh test    # tests
./dev.sh gui     # appli dans le navigateur : http://localhost:6080/vnc.html
```

Le code est organisé par fonctionnalité dans `cleantrace/` : `loader` (import),
`cleaning` (nettoyage), `plotting` (graphique), `editing` (clic), `export`, `app` (interface).

## Licence

MIT
