"""Test de bout en bout de l'interface (exécuté dans Docker, sur l'écran virtuel Xvfb).

Ouvre les fichiers d'exemple, nettoie, corrige un point au clic, décale la température,
exporte, et enregistre des captures d'écran dans le dossier passé en argument.

Usage : ./dev.sh smoke   (captures dans .dev-out/)
"""
import sys
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import ImageGrab  # noqa: E402

from cleantrace import app as app_module  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else ".dev-out")
OUT.mkdir(parents=True, exist_ok=True)
EXAMPLES = sorted(str(p) for p in (ROOT / "exemples").glob("essai_*"))

# Les boîtes de dialogue bloqueraient le test : on les remplace.
dialogs = []
app_module.messagebox.showinfo = lambda *a, **k: dialogs.append(("info",) + a)
app_module.messagebox.showwarning = lambda *a, **k: dialogs.append(("warning",) + a)
app_module.messagebox.showerror = lambda *a, **k: dialogs.append(("error",) + a)
app_module.filedialog.asksaveasfilename = lambda **k: str(OUT / "export.csv")


def pump(root, n=20):
    for _ in range(n):
        root.update()


def shot(root, name):
    pump(root)
    x, y = root.winfo_rootx(), root.winfo_rooty()
    w, h = root.winfo_width(), root.winfo_height()
    ImageGrab.grab(bbox=(x, y, x + w, y + h), xdisplay=":99").save(OUT / name)
    print("capture :", OUT / name)


def main():
    root = tk.Tk()
    root.geometry("1500x900+0+0")
    gui = app_module.CleanTraceApp(root)
    shot(root, "0_accueil.png")

    gui.open_files(EXAMPLES)
    assert len(gui.session.measurements) == 2, dialogs
    shot(root, "1_import.png")

    # Afficher uniquement le shunt Graphtec + la température enceinte
    gui.select_all(False)
    shunt = ("essai_GL980.csv", "Channel 2 - Courant shunt (mV)")
    gui._checked[shunt] = True
    gui._refresh_checkmarks()
    gui.redraw()
    shot(root, "2_shunt_brut.png")

    gui.clean_selected()
    print("état :", gui.status.get())
    shot(root, "3_shunt_nettoye.png")

    # Correction au clic : on abîme un point, puis on clique dessus sur le canevas
    df = gui.session.measurements[shunt[0]].data
    idx = 2000
    gui.session.set_value(shunt, idx, 60.0)
    gui.redraw()
    pump(root)
    line = gui.figure.axes[0].get_lines()[0]
    ax = line.axes
    ax.set_xlim(df["Time_min"].iloc[idx] - 0.2, df["Time_min"].iloc[idx] + 0.2)
    gui.canvas.draw()
    px, py = ax.transData.transform((df["Time_min"].iloc[idx], 60.0))
    widget = gui.canvas.get_tk_widget()
    height = widget.winfo_height()
    widget.event_generate("<Motion>", x=int(px), y=int(height - py))
    widget.event_generate("<ButtonPress-1>", x=int(px), y=int(height - py))
    widget.event_generate("<ButtonRelease-1>", x=int(px), y=int(height - py))
    pump(root)
    corrected = df[shunt[1]].iloc[idx]
    print("point corrigé :", corrected, "|", gui.status.get())
    assert corrected != 60.0, "la correction au clic n'a pas eu lieu"
    shot(root, "4_correction_clic.png")

    # Toutes les voies + décalage de la température de -4 min
    gui.select_all(True)
    gui._set_offset(-4.0)
    shot(root, "5_toutes_voies_decalage.png")

    gui.export_csv()
    assert (OUT / "export.csv").exists(), dialogs
    print("export :", dialogs[-1])
    errors = [d for d in dialogs if d[0] == "error"]
    assert not errors, errors
    root.destroy()
    print("SMOKE OK")


if __name__ == "__main__":
    main()
