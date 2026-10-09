"""Génère des fichiers de mesure fictifs, calqués sur de vrais exports du laboratoire.

La structure (en-têtes, colonnes, formats de date, séparateurs) reproduit des fichiers
réels ; seules les valeurs sont simulées : cycles charge / repos / décharge de 10 min.

exemples/
* GL980_Mes-_260601-170139.CSV  Graphtec GL980 tel qu'écrit par l'appareil (dans Excel,
      tout tient dans une seule colonne) : séparateur « , » et décimale « , », donc les
      nombres sont entre guillemets ("+24,003"). Bloc
      Vendor/Model/…, « AMP settings » (CH3 à CH8 actives, nom + unité), « XY settings »,
      « Position/Vernier settings », puis « Data » : Number;Date;Time;us;CH3…;Alarm;AlarmOut.
      100 ms. Pics de saturation et bruit de repos sur les courants.
* nanodac_Rd_Z.txt              Eurotherm nanodac — tabulation, décimale « , », date
      jj/mm/aa, une ligne d'en-tête dont l'unité est dans le descriptif de la voie :
      « Date/Heure  Channel 2  (ENAN2);Group 1;M402-M210;°C ». 1 min.

exemples/autres_formats/
* GL860_1s.CSV                  Graphtec GL860 — « , » et décimale « . », en-tête double
      (No.,Date&Time,ms,CH1… puis NO.,Time,ms,V,mA…,A1234567890), 1 s, 670 points.

Usage : python exemples/generer_exemples.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
OTHER = OUT / "autres_formats"
rng = np.random.default_rng(42)

GL980_START = pd.Timestamp("2026-06-01 17:01:39")
GL980_DURATION_S = 40 * 60  # 40 min (le vrai fichier fait 48 h, 1,7 million de points)


def cycles(t, period_s=600.0, level=1.0):
    """Créneaux : charge 4 min, repos 1 min, décharge 4 min, repos 1 min."""
    phase = (t % period_s) / period_s
    out = np.zeros_like(t, dtype=float)
    out[phase < 0.4] = level
    out[(phase >= 0.5) & (phase < 0.9)] = -level
    return out


def add_spikes(y, n, level, width_max=3):
    y = y.copy()
    for pos in rng.choice(len(y) - 10, size=n, replace=False):
        w = rng.integers(1, width_max + 1)
        y[pos:pos + w] = level * rng.uniform(0.99, 1.0, size=w)
    return y


def fr(values, decimals):
    """Nombre signé, virgule décimale : +1,234 / -0,012."""
    return ["{:+.{}f}".format(v, decimals).replace(".", ",") for v in values]


def gl980():
    t = np.arange(0, GL980_DURATION_S, 0.1)
    n = len(t)
    stamps = GL980_START + pd.to_timedelta(t, unit="s")
    end = stamps[-1]

    u_alim = 24.0 + rng.normal(0, 0.02, n)
    i_s1 = 5.0 * cycles(t) + rng.normal(0, 0.004, n)
    i_s1 = add_spikes(i_s1, 25, 9.99)  # saturation pleine échelle ±10 A
    i_s1 = add_spikes(i_s1, 10, -9.99)
    i_s2 = 3.0 * cycles(t + 120) + rng.normal(0, 0.004, n)
    i_s2 = add_spikes(i_s2, 15, 9.99)
    u_s12 = 12.0 + 0.8 * cycles(t) + rng.normal(0, 0.01, n)
    i_s3 = 2.0 * cycles(t + 300) + rng.normal(0, 0.004, n)
    i_s4 = 2.0 * cycles(t + 420) + rng.normal(0, 0.004, n)

    def d(ts):
        return ts.strftime("%d/%m/%Y")

    def h(ts):
        return ts.strftime("%H:%M:%S")

    lines = [
        "Vendor;GRAPHTEC Corporation",
        "Model;GL980",
        "Version;Ver1,35;Rev0001",
        "MaxChannel;8",
        "Logic/Pulse;Off",
        "TempUnit;C",
        "Sampling interval;100ms",
        "Total data points;{}".format(n),
        "Trigger;0",
        "Start time;{};{}".format(d(GL980_START), h(GL980_START)),
        "End time;{};{}".format(d(end), h(end)),
        "Trigger time;{};{}".format(d(GL980_START), h(GL980_START)),
        "AMP settings",
        "CH;Signal name;Amp;Input;Range;Filter;Span;;Unit;Color;;;Line Width",
        "CH3;U_alim;M;DC;50V;Off;25;-25;V;5;23;30;0",
        "CH4;I_s1;M;DC;50mV;Off;10;-10;A;21;0;21;0",
        "CH5;I_s2;M;DC;50mV;Off;10;-10;A;28;0;17;0",
        "CH6;U_s1&2;M;DC;50V;Off;25;-25;V;28;5;6;0",
        "CH7;I_s3;M;DC;50mV;Off;10;-10;A;30;23;1;0",
        "CH8;I_s4;M;DC;50mV;Off;10;-10;A;5;23;30;0",
        "XY settings",
        "XY;Trace;X-Axis;Y-Axis",
        "XY1;On;CH1;CH2",
        "XY2;Off;CH1;CH3",
        "XY3;Off;CH1;CH4",
        "XY4;Off;CH1;CH2",
        "Position/Vernier settings",
        "CH;Position;Vernier",
    ] + ["CH{};50%;100,00%".format(k) for k in range(1, 9)] + [
        "Data",
        "Number;Date;Time;us;CH3;CH4;CH5;CH6;CH7;CH8;Alarm;AlarmOut",
    ]
    columns = [fr(u_alim, 3), fr(i_s1, 4), fr(i_s2, 4), fr(u_s12, 3), fr(i_s3, 4), fr(i_s4, 4)]
    dates, hours = stamps.strftime("%d/%m/%Y"), stamps.strftime("%H:%M:%S")
    micro = stamps.microsecond
    for k in range(n):
        alarm = "LLLLLLLLLL" if abs(i_s1[k]) < 9.9 else "LHLLLLLLLL"
        lines.append(";".join(
            [str(k + 1), dates[k], hours[k], str(micro[k])] + [c[k] for c in columns] + [alarm, "LLLL"]
        ))
    # Séparateur « , » : les champs contenant une virgule (décimales) sont entre guillemets
    lines = [",".join('"{}"'.format(c) if "," in c else c for c in line.split(";")) for line in lines]
    (OUT / "GL980_Mes-_260601-170139.CSV").write_bytes(("\r\n".join(lines) + "\r\n").encode("cp1252"))


def nanodac():
    # L'enceinte suit les cycles avec ~3 min de retard (à recaler avec le curseur)
    t = np.arange(-4 * 60, GL980_DURATION_S + 4 * 60, 60.0)
    heat = np.abs(cycles(t - 180.0))
    temp = np.empty(len(t))
    temp[0] = 27.5
    for k in range(1, len(t)):
        target = 27.5 + 1.2 * heat[k]
        temp[k] = temp[k - 1] + (target - temp[k - 1]) * (1 - np.exp(-60.0 / 150.0))
    temp += rng.normal(0, 0.08, len(t))
    stamps = GL980_START.floor("min") + pd.to_timedelta(t, unit="s")
    lines = ["Date/Heure\tChannel 2\t\t(ENAN2);Group 1;M402-M210;°C"]
    for ts, v in zip(stamps, temp):
        lines.append("{}\t{}".format(ts.strftime("%d/%m/%y %H:%M:%S"), "{:.2f}".format(v).replace(".", ",")))
    (OUT / "nanodac_Rd_Z.txt").write_bytes(("\r\n".join(lines) + "\r\n").encode("cp1252"))


def gl860():
    start = pd.Timestamp("2026-09-10 14:53:39")
    n = 670
    t = np.arange(n, dtype=float)
    stamps = start + pd.to_timedelta(t, unit="s")
    amp = [  # CH, nom, plage, span, unité
        ("CH1", "U_alim", "50V", "0.100000,-0.100000", "V"),
        ("CH2", "I_spcC1", "200mV", "500.000000,-500.000000", "mA"),
        ("CH3", "CH3", "200mV", "25.000000,-25.000000", "mA"),
        ("CH4", "I_spc3", "200mV", "50.000000,-50.000000", "mA"),
        ("CH5", "CH5", "200mV", "100.000000,-100.000000", "mA"),
        ("CH6", "I_LH5", "200mV", "25.000000,-25.000000", "mA"),
        ("CH7", "CH7", "200mV", "100.000000,-100.000000", "mA"),
        ("CH8", "I_LB5", "50V", "0.025000,-0.025000", "V"),
        ("CH11", "I_LH7", "200mV", "500.000000,-500.000000", "mA"),
        ("CH13", "I_LB7", "100mV", "666.700000,-666.700000", "mA"),
    ]
    lines = [
        "Vendor,GRAPHTEC Corporation",
        "Model,GL860",
        "Firmware,Ver1.07",
        'Software,"Ver1.11"',
        "MaxChannel,30CH",
        "GSStartCH,30CH",
        "WLStartCH,30CH",
        "RTStartCH,30CH",
        "WLUnit,",
        "RTUnit,",
        "RTMaxCh,",
        "Sampling,1s",
        "Total data points,{}".format(n),
        "Trigger,0",
        "Start time,{},{}".format(start.strftime("%d/%m/%Y"), start.strftime("%H:%M:%S")),
        "Stop time,{},{}".format(stamps[-1].strftime("%d/%m/%Y"), stamps[-1].strftime("%H:%M:%S")),
        "Trigger time,{},{}".format(start.strftime("%d/%m/%Y"), start.strftime("%H:%M:%S")),
        "AC Mode,",
        "Logic/Pulse,Off",
        "Amp setting",
        "CH,Signal name,AMP,Input,Range,Temp Range,Filter,Span,,Unit",
    ] + ["{},{},SL3,DC,{},,Off,{},{}".format(ch, name, rng_, span, unit) for ch, name, rng_, span, unit in amp] + [
        "Data",
        "No.,Date&Time,ms," + ",".join(a[0] for a in amp) + ",Alarm1,Alarm2,Alarm3",
        "NO.,Time,ms," + ",".join(a[4] for a in amp) + ",A1234567890,A1234567890,A1234567890",
    ]
    base = [28.1, 122.8, 48.87, 0.02, 125.54, 48.65, 123.98, 27.81, 3.0, 6.67]
    values = [b + 0.3 * abs(b) * cycles(t, 120.0) + rng.normal(0, 0.01 * abs(b) + 0.01, n) for b in base]
    for k in range(n):
        lines.append(",".join(
            [str(k + 1), stamps[k].strftime("%Y/%m/%d %H:%M:%S"), "0"]
            + ["{:+.2f}".format(v[k]) for v in values]
            + ["LLLLLLLLLL"] * 3
        ))
    OTHER.mkdir(exist_ok=True)
    (OTHER / "GL860_1s.CSV").write_bytes(("\r\n".join(lines) + "\r\n").encode("cp1252"))


if __name__ == "__main__":
    for old in OUT.glob("essai_*"):
        old.unlink()
    gl980()
    nanodac()
    gl860()
    print("Fichiers d'exemple générés dans", OUT)
