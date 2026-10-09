"""Un même enregistrement GL980 écrit de toutes les façons possibles doit être lu à l'identique.

Le GL980 permet de choisir la décimale (« . » ou « , ») et le séparateur (« , », tabulation
ou « ; ») de ses CSV. S'y ajoutent les variantes produites quand le fichier passe par Excel
(lignes complétées par des séparateurs, dates jj/mm/aaaa, BOM, guillemets...).
"""
import itertools

import numpy as np
import pandas as pd
import pytest

from cleantrace.loader import TIME_COL, load_measurement

START = pd.Timestamp("2026-06-01 17:01:39")
N = 300  # points à 100 ms
LABELS = ["Channel 3 - U_alim (V)", "Channel 4 - I_s1 (A)", "Channel 5 - I_s2 (A)"]


def reference_values():
    rng = np.random.default_rng(1)
    t = np.arange(N)
    u = np.round(24.0 + rng.normal(0, 0.01, N), 3)
    i1 = np.round(np.where((t // 50) % 2 == 0, 5.0, -5.0) + rng.normal(0, 0.004, N), 4)
    i2 = np.round(np.where((t // 70) % 2 == 0, 0.0, 2.5) + rng.normal(0, 0.004, N), 4)
    return u, i1, i2


def write_gl980(path, sep=",", decimal=".", quote="none", sign_space=False, excel_padded=False,
                dmy=False, encoding="utf-8", eol="\r\n", over_range=True):
    u, i1, i2 = reference_values()
    stamps = START + pd.to_timedelta(np.arange(N) * 0.1, unit="s")

    def num(v, d):
        text = "{:+.{}f}".format(v, d)
        if sign_space:
            text = text[0] + " " + text[1:]
        return text.replace(".", decimal)

    def date(ts):
        return ts.strftime("%d/%m/%Y") if dmy else ts.strftime("%Y/%m/%d")

    preamble = [
        ["Vendor", "GRAPHTEC Corporation"], ["Model", "GL980"], ["Version", "Ver1" + decimal + "35", "Rev0001"],
        ["MaxChannel", "8"], ["Logic/Pulse", "Off"], ["TempUnit", "C"], ["Sampling interval", "100ms"],
        ["Total data points", str(N)], ["Trigger", "0"],
        ["Start time", date(START), START.strftime("%H:%M:%S")],
        ["End time", date(START), "17:02:09"],  # 3 lignes date + heure d'affilée : piège à
        ["Trigger time", date(START), START.strftime("%H:%M:%S")],  # éviter une fois complétées
        ["AMP settings"],
        ["CH", "Signal name", "Amp", "Input", "Range", "Filter", "Span", "", "Unit"],
        ["CH3", "U_alim", "M", "DC", "50V", "Off", "25", "-25", "V"],
        ["CH4", "I_s1", "M", "DC", "50mV", "Off", "10", "-10", "A"],
        ["CH5", "I_s2", "M", "DC", "50mV", "Off", "10", "-10", "A"],
        ["XY settings"], ["XY", "Trace", "X-Axis", "Y-Axis"], ["XY1", "On", "CH1", "CH2"],
        ["Position/Vernier settings"], ["CH", "Position", "Vernier"], ["CH3", "50%", "100" + decimal + "00%"],
        ["Data"],
        ["Number", "Date", "Time", "us", "CH3", "CH4", "CH5", "Alarm", "AlarmOut"],
    ]
    rows = []
    for k in range(N):
        i1_text = "+++++++" if over_range and k == 123 else num(i1[k], 4)
        rows.append([str(k + 1), date(stamps[k]), stamps[k].strftime("%H:%M:%S"), str(stamps[k].microsecond),
                     num(u[k], 3), i1_text, num(i2[k], 4), "LLLLLLLLLL", "LLLL"])
    width = len(rows[0])
    if excel_padded:  # Excel complète chaque ligne jusqu'à la largeur du tableau
        preamble = [r + [""] * (width - len(r)) if len(r) < width else r for r in preamble]

    def field(text, is_number):
        needs = sep in text or (decimal == sep and is_number)
        if quote == "all" or (quote == "strings" and not is_number) or needs:
            return '"' + text + '"'
        return text

    def line(cells, numbers=()):
        text = sep.join(field(c, j in numbers) for j, c in enumerate(cells))
        if quote == "line":
            text = '"' + text.replace('"', '""') + '"'
        return text

    lines = [line(r) for r in preamble] + [line(r, numbers={0, 3, 4, 5, 6}) for r in rows]
    if sep == "," and decimal == "," and quote == "none":
        # cas ambigu : le GL980 écrit les nombres sans guillemets -> reconstitution par le signe
        lines = [sep.join(r) for r in preamble] + [
            sep.join(r) for r in rows
        ]
    path.write_bytes((eol.join(lines) + eol).encode(encoding))
    return path


CORE = list(itertools.product([",", ";", "\t"], [".", ","], ["none", "strings", "all", "line"]))


@pytest.mark.parametrize("k, sep, decimal, quote", [(k,) + c for k, c in enumerate(CORE)],
                         ids=["sep={!r}-dec={!r}-{}".format(*c) for c in CORE])
def test_every_gl980_layout_reads_the_same(tmp_path, k, sep, decimal, quote):
    # Les autres variantes tournent d'un cas à l'autre pour toutes les croiser
    path = write_gl980(
        tmp_path / "Mes-_260601-170139.CSV", sep=sep, decimal=decimal, quote=quote,
        sign_space=k % 2 == 1, excel_padded=k % 3 == 0, dmy=k % 4 >= 2,
        encoding=["utf-8", "cp1252", "utf-8-sig", "utf-16"][k % 4], eol=["\r\n", "\n"][k % 2],
    )
    m = load_measurement(path)
    assert [c.label for c in m.channels] == LABELS
    assert m.start == START
    assert m.period_s == pytest.approx(0.1)
    assert len(m.data) == N
    u, i1, i2 = reference_values()
    i1 = i1.copy()
    i1[123] = np.nan  # « +++++++ » : hors échelle
    np.testing.assert_allclose(m.data[LABELS[0]].to_numpy(), u)
    np.testing.assert_allclose(m.data[LABELS[1]].to_numpy(), i1)
    np.testing.assert_allclose(m.data[LABELS[2]].to_numpy(), i2)
    assert m.data[TIME_COL].iloc[-1] == pytest.approx((N - 1) * 0.1 / 60)


def test_excel_resaved_without_seconds(tmp_path):
    """Réenregistré par Excel : « 10/09/2026 14:53 », secondes perdues -> temps recalculé."""
    lines = ["Vendor;GRAPHTEC Corporation;;;", "Model;GL860;;;", "Sampling;1s;;;", "Data;;;;",
             "No.;Date&Time;ms;CH1;CH2", "NO.;Time;ms;V;mA"]
    start = pd.Timestamp("2026-09-10 14:53:39")
    for k in range(150):
        ts = start + pd.Timedelta(seconds=k)
        lines.append("{};{};0;+28,{:02d};+122,8".format(k + 1, ts.strftime("%d/%m/%Y %H:%M"), k % 100))
    path = tmp_path / "1s.csv"
    path.write_text("\n".join(lines) + "\n", encoding="cp1252")
    m = load_measurement(path)
    assert m.period_s == pytest.approx(1.0)
    assert m.data[TIME_COL].iloc[-1] == pytest.approx(149 / 60)
    assert any("recalculé" in w for w in m.warnings)
    assert [c.label for c in m.channels] == ["Channel 1 (V)", "Channel 2 (mA)"]


def write_excel_resaved(path, n=N, declared=None, padded=True, utf8_bom=False):
    """Fichier GL980 converti dans Excel (Données > Convertir) puis « Enregistrer sous » CSV.

    Ce qu'Excel change : séparateur « ; » et décimale « , » (Windows français), signes « + »
    et zéros finaux supprimés (« +5,0000 » -> « 5 »), très petites valeurs en notation
    scientifique, dates jj/mm/aaaa, lignes courtes complétées par des « ; ».
    """
    u, i1, i2 = reference_values()
    reps = int(np.ceil(n / N))
    u, i1, i2 = (np.tile(x, reps)[:n] for x in (u, i1, i2))
    i2 = i2.copy()
    i2[7] = 0.000012  # -> « 1,2E-05 »
    stamps = START + pd.to_timedelta(np.arange(n) * 0.1, unit="s")

    def xl(v):
        text = "{:.10G}".format(v)
        if "E" in text:
            mant, exp = text.split("E")
            text = "{}E{}{:02d}".format(mant, exp[0], abs(int(exp)))
        return text.replace(".", ",")

    pre = [
        ["Vendor", "GRAPHTEC Corporation"], ["Model", "GL980"], ["Version", "Ver1,35", "Rev0001"],
        ["Sampling interval", "100ms"], ["Total data points", str(declared or n)],
        ["Start time", "01/06/2026", "17:01:39"], ["End time", "03/06/2026", "16:45:35"],
        ["Trigger time", "01/06/2026", "17:01:39"], ["AMP settings"],
        ["CH", "Signal name", "Amp", "Input", "Range", "Filter", "Span", "", "Unit"],
        ["CH3", "U_alim", "M", "DC", "50V", "Off", "25", "-25", "V"],
        ["CH4", "I_s1", "M", "DC", "50mV", "Off", "10", "-10", "A"],
        ["CH5", "I_s2", "M", "DC", "50mV", "Off", "10", "-10", "A"],
        ["Data"], ["Number", "Date", "Time", "us", "CH3", "CH4", "CH5", "Alarm", "AlarmOut"],
    ]
    width = 9
    lines = [";".join(r + ([""] * (width - len(r)) if padded else [])) for r in pre]
    dates, hours, micro = stamps.strftime("%d/%m/%Y"), stamps.strftime("%H:%M:%S"), stamps.microsecond
    for k in range(n):
        lines.append(";".join([str(k + 1), dates[k], hours[k], str(micro[k]), xl(u[k]), xl(i1[k]), xl(i2[k]),
                               "LLLLLLLLLL", "LLLL"]))
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8-sig" if utf8_bom else "cp1252"))
    return path, (u, i1, i2)


@pytest.mark.parametrize("padded, utf8_bom", [(True, False), (False, False), (True, True)])
def test_excel_converted_then_resaved(tmp_path, padded, utf8_bom):
    path, (u, i1, i2) = write_excel_resaved(tmp_path / "Mes-_260601-170139.csv", padded=padded, utf8_bom=utf8_bom)
    assert "1,2E-05" in path.read_bytes().decode("utf-8-sig" if utf8_bom else "cp1252")
    m = load_measurement(path)
    assert [c.label for c in m.channels] == LABELS
    assert m.start == START and m.period_s == pytest.approx(0.1) and len(m.data) == N
    np.testing.assert_allclose(m.data[LABELS[0]].to_numpy(), u)
    np.testing.assert_allclose(m.data[LABELS[1]].to_numpy(), i1)
    np.testing.assert_allclose(m.data[LABELS[2]].to_numpy(), i2)
    assert not any("tronqué" in w for w in m.warnings)


def test_excel_row_limit_is_reported(tmp_path):
    """Excel s'arrête à 1 048 576 lignes : un fichier réenregistré peut avoir perdu des mesures."""
    path, _ = write_excel_resaved(tmp_path / "Mes-_260601-170139.csv", n=1000, declared=1718363)
    m = load_measurement(path)
    assert len(m.data) == 1000
    assert any("1 718 363" in w and "1 000" in w for w in m.warnings)
