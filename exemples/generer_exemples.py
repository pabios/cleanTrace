"""Génère des fichiers de mesure fictifs mais réalistes pour tester CleanTrace.

Essai simulé : 3 cycles charge / repos / décharge / repos d'une batterie (2 h),
enregistrés simultanément par 4 centrales aux formats différents :

* essai_Graphset.csv  — référence : « ; », décimale « , », 1 s, date/heure jj/mm/aaaa
* essai_Graphtec.csv  — préambule centrale, « , », colonnes No./Time/ms/CH1..CH3, 500 ms,
                        pics de saturation et bruit de repos sur CH2 (shunt courant)
* essai_Nanodac.txt   — tabulation, cp1252, colonnes Date + Heure séparées, 10 s, courant en mA
* essai_Clim.csv      — enceinte climatique, « ; », cp1252, 1 min, température et humidité
                        enregistrées avec 4 min de retard (à recaler avec le curseur)

Usage : python exemples/generer_exemples.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
START = pd.Timestamp("2026-10-01 09:00:00")
DURATION_S = 2 * 3600
rng = np.random.default_rng(42)


def current_profile(t):
    """Courant (A) : 3 cycles de 40 min — charge 15 min, repos 5, décharge 15, repos 5."""
    phase = (t % 2400) / 60.0
    i = np.zeros_like(t, dtype=float)
    i[(phase >= 0) & (phase < 15)] = 2.0
    i[(phase >= 20) & (phase < 35)] = -2.0
    return i


def voltage_response(t, i):
    """Tension (V) : réponse du 1er ordre vers 4,2 V (charge) / 3,0 V (décharge) / 3,7 V (repos)."""
    v = np.empty_like(t, dtype=float)
    v[0] = 3.7
    target = np.where(i > 0, 4.2, np.where(i < 0, 3.0, 3.7))
    tau = np.where(i != 0, 300.0, 120.0)
    dt = np.diff(t, prepend=t[0])
    for k in range(1, len(t)):
        v[k] = v[k - 1] + (target[k] - v[k - 1]) * (1 - np.exp(-dt[k] / tau[k]))
    return v


def temperature(t, i):
    """Échauffement de l'enceinte : 25 °C + effet Joule filtré (constante 10 min)."""
    temp = np.empty_like(t, dtype=float)
    temp[0] = 25.0
    dt = np.diff(t, prepend=t[0])
    for k in range(1, len(t)):
        target = 25.0 + 1.5 * abs(i[k])
        temp[k] = temp[k - 1] + (target - temp[k - 1]) * (1 - np.exp(-dt[k] / 600.0))
    return temp


def add_spikes(y, n, level, width_max=3):
    y = y.copy()
    for pos in rng.choice(len(y) - 10, size=n, replace=False):
        w = rng.integers(1, width_max + 1)
        y[pos:pos + w] = level * rng.uniform(0.99, 1.0, size=w)
    return y


def graphset():
    t = np.arange(0, DURATION_S, 1.0)
    i = current_profile(t)
    v = voltage_response(t, i)
    df = pd.DataFrame({
        "Date/Heure": (START + pd.to_timedelta(t, unit="s")).strftime("%d/%m/%Y %H:%M:%S"),
        "Courant (A)": np.round(i + rng.normal(0, 0.002, len(t)), 4),
        "Tension (V)": np.round(v + rng.normal(0, 0.001, len(t)), 4),
    })
    df.to_csv(OUT / "essai_Graphset.csv", sep=";", decimal=",", index=False, encoding="utf-8")


def graphtec():
    t = np.arange(0, DURATION_S, 0.5) + 30.0  # démarre 30 s après le Graphset
    i = current_profile(t)
    v = voltage_response(t, i)
    shunt_mv = i * 50.0 + rng.normal(0, 1.5, len(t))  # shunt 50 mV/A, bruit ±3 mV au repos
    shunt_mv = add_spikes(shunt_mv, 40, 1000.0)  # saturation pleine échelle ±1 V
    shunt_mv = add_spikes(shunt_mv, 15, -1000.0)
    stamps = START + pd.to_timedelta(t, unit="s")
    df = pd.DataFrame({
        "No.": np.arange(1, len(t) + 1),
        "Time": stamps.strftime("%Y/%m/%d %H:%M:%S"),
        "ms": (stamps.microsecond // 1000),
        "CH1": np.round(v * 1000 + rng.normal(0, 0.8, len(t)), 2),
        "CH2": np.round(shunt_mv, 2),
        "CH3": np.round(temperature(t, i) * 10 + rng.normal(0, 0.5, len(t)), 2),  # thermocouple mV fictif
    })
    preamble = (
        "Model,GL840\n"
        "Title,Essai endurance cellule 18650\n"
        "Trigger Time,'2026/10/01 09:00:30\n"
        "Sampling interval,500ms\n"
        "\n"
    )
    with open(OUT / "essai_Graphtec.csv", "w", encoding="utf-8", newline="") as f:
        f.write(preamble)
        df.to_csv(f, sep=",", index=False)


def nanodac():
    t = np.arange(0, DURATION_S, 10.0)
    i = current_profile(t)
    current_ma = i * 1000 + rng.normal(0, 3.0, len(t))  # bruit ±6 mA au repos
    current_ma = add_spikes(current_ma, 6, 5000.0, width_max=1)
    stamps = START + pd.to_timedelta(t, unit="s")
    df = pd.DataFrame({
        "Date": stamps.strftime("%d/%m/%Y"),
        "Heure": stamps.strftime("%H:%M:%S"),
        "Courant (mA)": np.round(current_ma, 1),
        "Température cellule (°C)": np.round(temperature(t, i) + 2 + rng.normal(0, 0.05, len(t)), 2),
    })
    df.to_csv(OUT / "essai_Nanodac.txt", sep="\t", decimal=",", index=False, encoding="cp1252")


def clim():
    t = np.arange(0, DURATION_S, 60.0)
    lag = 4 * 60.0  # retard du banc thermique
    i_lagged = current_profile(np.clip(t - lag, 0, None))
    temp = temperature(t, i_lagged)
    hum = 45.0 - (temp - 25.0) * 1.2 + rng.normal(0, 0.2, len(t))
    df = pd.DataFrame({
        "Date/Heure": (START + pd.to_timedelta(t, unit="s")).strftime("%d/%m/%Y %H:%M"),
        "Température (°C)": np.round(temp, 2),
        "Humidité (%HR)": np.round(hum, 1),
    })
    df.to_csv(OUT / "essai_Clim.csv", sep=";", decimal=",", index=False, encoding="cp1252")


if __name__ == "__main__":
    graphset()
    graphtec()
    nanodac()
    clim()
    print("Fichiers d'exemple générés dans", OUT)
