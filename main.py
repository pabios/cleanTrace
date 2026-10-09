"""CleanTrace — point d'entrée.

Dans Spyder : ouvrir ce fichier puis appuyer sur F5 (Exécuter).
En ligne de commande : python main.py
"""
import os
import sys

# Permet de lancer main.py depuis n'importe quel répertoire de travail (Spyder, double-clic...)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REQUIRED = ("numpy", "pandas", "scipy", "matplotlib", "tkinter")


def _check_dependencies():
    missing = []
    for module in REQUIRED:
        try:
            __import__(module)
        except ImportError:
            missing.append(module)
    if missing:
        print("Modules manquants : " + ", ".join(missing))
        print("Installez-les avec :  pip install -r requirements.txt")
        print("(ou, sous Anaconda :  conda install " + " ".join(m for m in missing if m != "tkinter") + ")")
        return False
    return True


def _forget_previous_run():
    """Spyder garde en mémoire les modules d'un lancement précédent : sans ce nettoyage,
    un nouveau F5 réutiliserait l'ancienne version de CleanTrace (même après mise à jour)."""
    for name in list(sys.modules):
        if name == "cleantrace" or name.startswith("cleantrace."):
            del sys.modules[name]


if __name__ == "__main__":
    if _check_dependencies():
        _forget_previous_run()
        import cleantrace
        from cleantrace.app import run

        print("CleanTrace {} — {}".format(cleantrace.__version__, os.path.dirname(cleantrace.__file__)))
        run()
