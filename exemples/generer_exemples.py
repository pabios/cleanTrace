"""Génère des fichiers de mesure fictifs au format des enregistreurs du labo.

Essai simulé : 3 cycles charge / repos / décharge / repos d'une batterie (2 h) placée
dans une enceinte climatique, enregistrés par deux appareils :

* essai_GL980.csv   — Graphtec GL980 (export CSV de l'appareil) :
    préambule Model / Title / Trigger Time, tableau « Amp settings » (nom et unité de
    chaque voie), marqueur "Data", en-têtes NO./Time/ms/CH1.., ligne d'unités,
    colonnes d'alarme, période 500 ms. Pics de saturation, valeurs hors échelle
    « +++++++ » et bruit de repos sur le shunt de courant.
* essai_nanodac.csv — Eurotherm nanodac (archive CSV, séparateur tabulation car
    décimale « , ») : en-tête appareil, date au format « Spreadsheet » (jours depuis
    le 30/12/1899), unités en ASCII (degC, %RH), colonne Messages, période 10 s.
    Température et humidité de l'enceinte, avec 4 min de retard sur l'électrique
    (à recaler avec le curseur de décalage).

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


def first_order(t, target, tau, y0):
    """Réponse du 1er ordre vers ``target`` (constante de temps ``tau``)."""
    y = np.empty_like(t, dtype=float)
    y[0] = y0
    dt = np.diff(t, prepend=t[0])
    for k in range(1, len(t)):
        y[k] = y[k - 1] + (target[k] - y[k - 1]) * (1 - np.exp(-dt[k] / tau[k]))
    return y


def voltage(t, i):
    target = np.where(i > 0, 4.2, np.where(i < 0, 3.0, 3.7))
    return first_order(t, target, np.where(i != 0, 300.0, 120.0), 3.7)


def cell_temperature(t, i):
    return first_order(t, 25.0 + 1.5 * np.abs(i), np.full(len(t), 600.0), 25.0)


def add_spikes(y, n, level, width_max=3):
    y = y.copy()
    for pos in rng.choice(len(y) - 10, size=n, replace=False):
        w = rng.integers(1, width_max + 1)
        y[pos:pos + w] = level * rng.uniform(0.99, 1.0, size=w)
    return y


def fmt(values, decimals):
    """Format Graphtec : signe explicite, ex. +3.6991 / -0.0012."""
    return ["{:+.{}f}".format(v, decimals) for v in values]


def gl980():
    t = np.arange(0, DURATION_S, 0.5)
    i = current_profile(t)
    stamps = START + pd.to_timedelta(t + 30.0, unit="s")  # déclenché 30 s après le nanodac

    ch1 = voltage(t, i) + rng.normal(0, 0.0008, len(t))  # tension cellule (V)
    ch2 = i * 50.0 + rng.normal(0, 1.5, len(t))  # shunt 50 mV/A, gamme 1000 mV
    ch2 = add_spikes(ch2, 40, 999.9)
    ch2 = add_spikes(ch2, 15, -999.9)
    ch3 = cell_temperature(t, i) + rng.normal(0, 0.05, len(t))  # thermocouple K

    ch2_txt = fmt(ch2, 2)
    for pos in rng.choice(len(t) - 5, size=12, replace=False):  # hors échelle
        ch2_txt[pos] = "+++++++" if rng.random() < 0.7 else "-------"
    ch3_txt = fmt(ch3, 1)
    ch3_txt[5000] = "BURNOUT"  # thermocouple débranché un instant

    alarms = np.where(np.abs(ch2) > 900, "LHLLLLLLLL", "LLLLLLLLLL")

    lines = [
        '"Model","GL980"',
        '"Title","Essai endurance cellule 18650"',
        '"Trigger Time","\'2026/10/01 09:00:30"',
        '"Sampling interval","500ms"',
        '"Number of Data","{}"'.format(len(t)),
        "",
        '"Amp settings"',
        '"CH","Signal name","Input","Range","Filter","Span","Unit"',
        '"CH1","Tension cellule","DC","10V","Off","0.000,5.000","V"',
        '"CH2","Courant shunt","DC","1V","Off","-1000.00,1000.00","mV"',
        '"CH3","T cellule","TEMP","TC-K","Off","0.0,100.0","degC"',
        '"CH4","CH4","Off","","","",""',
        "",
        '"Data"',
        '"NO.","Time","ms","CH1","CH2","CH3","Alarm1-10","AlarmOut"',
        '"","","","V","mV","degC","",""',
    ]
    for k in range(len(t)):
        lines.append("{},{},{},{},{},{},{},{}".format(
            k + 1, stamps[k].strftime("%Y/%m/%d %H:%M:%S"), stamps[k].microsecond // 1000,
            fmt([ch1[k]], 4)[0], ch2_txt[k], ch3_txt[k], alarms[k], "LLLL",
        ))
    (OUT / "essai_GL980.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def nanodac():
    t = np.arange(0, DURATION_S, 10.0)
    lag = 4 * 60.0  # retard du banc thermique
    i_lagged = current_profile(np.clip(t - lag, 0, None))
    temp = first_order(t, 25.0 + 2.0 * np.abs(i_lagged), np.full(len(t), 400.0), 25.0)
    temp += rng.normal(0, 0.03, len(t))
    hum = 45.0 - (temp - 25.0) * 1.2 + rng.normal(0, 0.15, len(t))
    setpoint = np.full(len(t), 25.0)

    serial = (START + pd.to_timedelta(t, unit="s") - pd.Timestamp("1899-12-30")) / pd.Timedelta(days=1)
    messages = {0: "Démarrage enregistrement", 360: "Alarme 1 Voie 1 active", 400: "Alarme 1 Voie 1 inactive"}

    def num(v, d):
        return "{:.{}f}".format(v, d).replace(".", ",")

    lines = [
        "Instrument\tnanodac",
        "Serial Number\t21345678",
        "Software Version\t6.02",
        "Group Title\tEnceinte climatique CL-04",
        "Recording Interval\t10 s",
        "",
        "Date/Time\tT enceinte\tHR enceinte\tConsigne T\tMessages",
        "\tdegC\t%RH\tdegC\t",
    ]
    for k in range(len(t)):
        lines.append("\t".join([
            num(serial[k], 8), num(temp[k], 2), num(hum[k], 1), num(setpoint[k], 1),
            messages.get(k, ""),
        ]))
    # Le nanodac écrit en ASCII : les accents des messages deviennent des « ? »
    (OUT / "essai_nanodac.csv").write_bytes(("\r\n".join(lines) + "\r\n").encode("ascii", "replace"))


if __name__ == "__main__":
    for old in ("essai_Graphset.csv", "essai_Graphtec.csv", "essai_Nanodac.txt", "essai_Clim.csv"):
        (OUT / old).unlink(missing_ok=True)
    gl980()
    nanodac()
    print("Fichiers d'exemple générés dans", OUT)
