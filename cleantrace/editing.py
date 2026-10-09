"""US-05 — Correction manuelle d'un point au clic gauche sur le graphique.

Le point cliqué est remplacé par l'interpolation temporelle de ses voisins immédiats :

    y[idx] = y_gauche + alpha * (y_droite - y_gauche)
    alpha  = (x[idx] - x_gauche) / (x_droite - x_gauche)

Seule la courbe concernée est mise à jour, puis ``fig.canvas.draw_idle()`` rafraîchit
l'écran : pas de retracé complet.
"""
from __future__ import annotations

from typing import Callable, Optional, Tuple

import numpy as np


def interpolate_at(x, y, idx: int) -> float:
    """Valeur interpolée au point ``idx`` à partir de ses voisins immédiats."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 2:
        return float(y[idx])
    if idx <= 0:
        return float(y[1])
    if idx >= n - 1:
        return float(y[n - 2])
    x_left, x_right = x[idx - 1], x[idx + 1]
    y_left, y_right = y[idx - 1], y[idx + 1]
    if x_right == x_left:
        return float((y_left + y_right) / 2.0)
    alpha = (x[idx] - x_left) / (x_right - x_left)
    return float(y_left + alpha * (y_right - y_left))


class ClickCorrector:
    """Branche la correction au clic gauche sur une figure Matplotlib.

    Seules les courbes portant un ``gid`` sont corrigeables. Après chaque correction,
    ``on_correct(gid, idx, nouvelle_valeur)`` est appelé pour mettre à jour les données.
    """

    def __init__(
        self,
        figure,
        on_correct: Callable[[str, int, float], None],
        is_enabled: Callable[[], bool] = lambda: True,
        pickradius: float = 6.0,
    ):
        self.figure = figure
        self.on_correct = on_correct
        self.is_enabled = is_enabled
        self.pickradius = pickradius
        self._cid = figure.canvas.mpl_connect("button_press_event", self._on_press)

    def disconnect(self) -> None:
        self.figure.canvas.mpl_disconnect(self._cid)

    def _on_press(self, event) -> None:
        if event.button != 1 or event.inaxes is None or not self.is_enabled():
            return
        toolbar = getattr(self.figure.canvas, "toolbar", None)
        if toolbar is not None and getattr(toolbar, "mode", ""):
            return  # zoom ou déplacement en cours : le clic n'est pas une correction
        hit = self.find_point(event)
        if hit is None:
            return
        line, idx = hit
        x = np.asarray(line.get_xdata(), dtype=float)
        y = np.array(line.get_ydata(), dtype=float)
        y[idx] = interpolate_at(x, y, idx)
        line.set_ydata(y)
        self.on_correct(line.get_gid(), idx, float(y[idx]))
        self.figure.canvas.draw_idle()

    def find_point(self, event) -> Optional[Tuple[object, int]]:
        """Courbe et indice du point le plus proche du clic (toutes les axes, y compris twinx)."""
        best = None
        for ax in self.figure.axes:
            for line in ax.get_lines():
                if line.get_gid() is None or not line.get_visible():
                    continue
                line.set_pickradius(self.pickradius)
                inside, info = line.contains(event)
                if not inside or not len(info.get("ind", [])):
                    continue
                xd = np.asarray(line.get_xdata(), dtype=float)
                yd = np.asarray(line.get_ydata(), dtype=float)
                ind = np.asarray(info["ind"])
                cand = np.unique(np.clip(np.concatenate([ind, ind + 1]), 0, len(xd) - 1))
                pts = line.axes.transData.transform(np.column_stack([xd[cand], yd[cand]]))
                dist = np.hypot(pts[:, 0] - event.x, pts[:, 1] - event.y)
                k = int(np.nanargmin(dist))
                if best is None or dist[k] < best[0]:
                    best = (dist[k], line, int(cand[k]))
        if best is None:
            return None
        return best[1], best[2]
