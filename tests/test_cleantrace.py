"""Tests automatiques de la logique métier (sans interface graphique)."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cleantrace.channels import CURRENT, HUMIDITY, TEMPERATURE, VOLTAGE, make_channel
from cleantrace.cleaning import CleaningOptions, clean_signal, remove_saturation_peaks, zero_rest_noise
from cleantrace.editing import interpolate_at
from cleantrace.loader import TIME_COL, LoadError, align_time_axes, load_measurement
from cleantrace.plotting import format_hms
from cleantrace.session import Session

EXAMPLES = Path(__file__).resolve().parent.parent / "exemples"
ALL_EXAMPLES = ["essai_Graphset.csv", "essai_Graphtec.csv", "essai_Nanodac.txt", "essai_Clim.csv"]


# ------------------------------------------------------------------- US-01 import


@pytest.mark.parametrize(
    "filename, source, sep, encoding, period_s, n_channels",
    [
        ("essai_Graphset.csv", "Graphset", ";", "utf-8", 1.0, 2),
        ("essai_Graphtec.csv", "Graphtec", ",", "utf-8", 0.5, 3),
        ("essai_Nanodac.txt", "Nanodac", "\t", "cp1252", 10.0, 2),
        ("essai_Clim.csv", "Clim", ";", "cp1252", 60.0, 2),
    ],
)
def test_import_examples(filename, source, sep, encoding, period_s, n_channels):
    m = load_measurement(EXAMPLES / filename)
    assert m.source == source
    assert m.separator == sep
    assert m.encoding == encoding
    assert m.period_s == pytest.approx(period_s)
    assert len(m.channels) == n_channels
    assert m.start is not None
    assert m.data[TIME_COL].iloc[0] == 0
    assert m.duration_min == pytest.approx(120, abs=1.1)


def test_graphtec_labels_and_ms_column():
    m = load_measurement(EXAMPLES / "essai_Graphtec.csv")
    assert [c.label for c in m.channels] == ["Channel 1 (mV)", "Channel 2 (mV)", "Channel 3 (mV)"]
    assert m.start == pd.Timestamp("2026-10-01 09:00:30")


def test_alignment_on_graphset_reference():
    ms = [load_measurement(EXAMPLES / f) for f in ALL_EXAMPLES]
    ref = align_time_axes(ms)
    assert ref.source == "Graphset"
    graphtec = ms[1]
    assert graphtec.data[TIME_COL].iloc[0] == pytest.approx(0.5)  # démarre 30 s après


def test_reference_is_longest_without_graphset(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("Temps (s);U (V)\n0;1\n1;1\n2;1\n3;1\n")
    b.write_text("Temps (s);U (V)\n0;1\n1;1\n2;1\n3;1\n4;1\n5;1\n")
    ms = [load_measurement(a), load_measurement(b)]
    assert align_time_axes(ms).path == b


@pytest.mark.parametrize(
    "header, values, expected_period",
    [
        ("Temps (ms)", ["0", "100", "200", "300"], 0.1),
        ("Temps (s)", ["0", "1", "2", "3"], 1.0),
        ("Temps (min)", ["0", "1", "2", "3"], 60.0),
        ("Durée", ["0:00:00", "0:00:05", "0:00:10", "0:00:15"], 5.0),
    ],
)
def test_time_units(tmp_path, header, values, expected_period):
    f = tmp_path / "essai.txt"
    f.write_text(header + "\tU (V)\n" + "\n".join(v + "\t1,5" for v in values) + "\n")
    m = load_measurement(f)
    assert m.period_s == pytest.approx(expected_period)
    assert m.data["U (V)"].iloc[0] == 1.5


def test_latin1_and_unit_row(tmp_path):
    f = tmp_path / "temp_enceinte.dat"
    content = "Heure;T;H\n;°C;%RH\n10:00:00;20,5;40\n10:00:10;20,6;41\n10:00:20;20,7;42\n"
    f.write_bytes(content.encode("latin-1"))
    m = load_measurement(f)
    assert [c.label for c in m.channels] == ["T (°C)", "H (%HR)"]
    assert m.channels[0].quantity == TEMPERATURE


@pytest.mark.parametrize(
    "content, message",
    [
        ("", "vide"),
        ("juste une ligne de texte\nencore du texte\n", "séparateur"),
        ("a;b\nx;y\nz;w\n", "données numériques"),
    ],
)
def test_invalid_files(tmp_path, content, message):
    f = tmp_path / "mauvais.csv"
    f.write_text(content)
    with pytest.raises(LoadError, match=message):
        load_measurement(f)


# --------------------------------------------------------------- US-02 libellés


@pytest.mark.parametrize(
    "raw, label, quantity",
    [
        ("CH1", "Channel 1 (mV)", VOLTAGE),
        ("CH03[V]", "Channel 3 (V)", VOLTAGE),
        ("Courant (mA)", "Courant (mA)", CURRENT),
        ("Température", "Température (°C)", TEMPERATURE),
        ("HR (%)", "HR (%HR)", HUMIDITY),
        ('"Pression"', "Pression", "autre"),
    ],
)
def test_channel_labels(raw, label, quantity):
    ch = make_channel(raw)
    assert ch.label == label
    assert ch.quantity == quantity


# --------------------------------------------------------------- US-03 nettoyage


def square_wave():
    """Créneaux 0 / 2 A / 0 / -2 A, 100 points par palier, avec bruit de repos."""
    y = np.concatenate([np.zeros(100), np.full(100, 2.0), np.zeros(100), np.full(100, -2.0), np.zeros(100)])
    return y


def test_peaks_removed_square_wave_untouched():
    clean = square_wave()
    noisy = clean.copy()
    noisy[150] = 5.0  # pic de saturation sur le palier haut
    noisy[[40, 41]] = 5.0  # pic double au repos
    noisy[350:353] = -5.0  # pic négatif sur le palier de décharge
    out, n = remove_saturation_peaks(noisy)
    assert n == 6
    np.testing.assert_allclose(out, clean, atol=1e-9)


def test_genuine_plateau_at_max_is_kept():
    y = square_wave()
    out, n = remove_saturation_peaks(y)
    assert n == 0
    np.testing.assert_array_equal(out, y)


def test_cycle_extremes_preserved_with_noise():
    rng = np.random.default_rng(0)
    y = square_wave() + rng.normal(0, 0.003, 500)
    y[120] = 5.0
    out, _ = clean_signal(y, "A", CleaningOptions())
    # max initial du cycle (palier de charge) et min final (palier de décharge) inchangés
    assert out[100:200].max() == pytest.approx(y[100:200][np.arange(100) != 20].max())
    assert out[300:400].min() == pytest.approx(y[300:400].min())
    # pas de pente : les fronts restent verticaux
    assert out[99] == 0.0 and out[100] == y[100]


def test_exponential_discharge_not_deformed():
    t = np.linspace(0, 10, 1000)
    y = 4.2 * np.exp(-t / 3)
    out, n = remove_saturation_peaks(y)
    assert n == 0
    np.testing.assert_array_equal(out, y)


def test_rest_noise_forced_to_zero():
    y = np.array([0.004, -0.008, 0.009, 2.0, 2.01, 1.99, -0.003, 0.002, 0.001])
    out, n = zero_rest_noise(y, "A")
    np.testing.assert_array_equal(out, [0, 0, 0, 2.0, 2.01, 1.99, 0, 0, 0])
    assert n == 6
    mv, _ = zero_rest_noise(np.array([3.0, -4.0, 2.0, 100.0]), "mV")
    np.testing.assert_array_equal(mv, [0, 0, 0, 100.0])
    # point isolé à peine au-dessus du seuil au milieu d'une phase d'arrêt
    gap, _ = zero_rest_noise(np.array([1.0, -2.0, 1.0, -6.0, 2.0, 1.0, -1.0]), "mV")
    np.testing.assert_array_equal(gap, np.zeros(7))
    # ... mais un vrai signal faible (> 2 × seuil) est conservé
    kept, _ = zero_rest_noise(np.array([1.0, -2.0, 1.0, 12.0, 2.0, 1.0, -1.0]), "mV")
    assert kept[3] == 12.0
    temp, n = zero_rest_noise(np.array([0.1, 0.2, 0.1]), "°C")
    assert n == 0  # pas de seuil pour les températures


def test_options_disable_treatments():
    y = square_wave() + 0.001
    y[150] = 5.0
    out, report = clean_signal(y, "A", CleaningOptions(remove_noise=False, remove_peaks=False))
    np.testing.assert_array_equal(out, y)
    assert report.total == 0


def test_nan_values_are_kept():
    y = square_wave()
    y[10] = np.nan
    y[150] = 5.0
    out, n = remove_saturation_peaks(y)
    assert np.isnan(out[10]) and n == 1


# ------------------------------------------------------------ US-04 / US-05


def test_format_hms():
    assert format_hms(0) == "0:00:00"
    assert format_hms(61.5) == "1:01:30"
    assert format_hms(-0.5) == "-0:00:30"


def test_interpolation_formula():
    x = np.array([0.0, 1.0, 3.0])
    y = np.array([10.0, 999.0, 30.0])
    assert interpolate_at(x, y, 1) == pytest.approx(10 + (1 / 3) * 20)
    assert interpolate_at(x, y, 0) == 999.0  # bord gauche : voisin immédiat
    assert interpolate_at(x, y, 2) == 999.0


def test_click_correction_on_figure():
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.backend_bases import MouseEvent
    from matplotlib.figure import Figure

    from cleantrace.editing import ClickCorrector

    fig = Figure()
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    twin = ax.twinx()
    ax.plot([0, 1, 2, 3, 4], [0, 0, 0, 0, 0], gid="a")
    twin.plot([0, 1, 2, 3, 4], [1, 1, 9, 1, 1], gid="b")  # point abîmé sur l'axe secondaire
    fig.canvas.draw()
    calls = []
    corrector = ClickCorrector(fig, lambda gid, idx, v: calls.append((gid, idx, v)))  # noqa: F841 (référence à garder : Matplotlib ne garde qu une référence faible)
    px, py = twin.transData.transform((2, 9))
    event = MouseEvent("button_press_event", fig.canvas, px, py, button=1)
    fig.canvas.callbacks.process("button_press_event", event)
    assert calls == [("b", 2, 1.0)]


# ------------------------------------------------------------ session + US-06


def test_session_end_to_end(tmp_path):
    s = Session()
    loaded, errors = s.load_files([EXAMPLES / f for f in ALL_EXAMPLES])
    assert len(loaded) == 4 and not errors
    keys = s.all_keys()
    assert len(keys) == 9

    shunt = ("essai_Graphtec.csv", "Channel 2 (mV)")
    raw = s.measurements[shunt[0]].data[shunt[1]].to_numpy().copy()
    report = s.apply_cleaning([shunt], CleaningOptions())
    cleaned = s.measurements[shunt[0]].data[shunt[1]].to_numpy()
    assert report.peak_points > 0 and report.noise_points > 0
    assert np.nanmax(cleaned) < 120  # plus de saturation à 1000 mV
    assert np.nanmax(cleaned) > 95  # mais les paliers de charge (100 mV) sont intacts

    s.set_value(shunt, 10, 42.0)
    assert s.measurements[shunt[0]].data[shunt[1]].iloc[10] == 42.0
    s.restore_raw([shunt])
    np.testing.assert_array_equal(s.measurements[shunt[0]].data[shunt[1]].to_numpy(), raw)

    s.time_offset_min = -4
    out = tmp_path / "export.csv"
    df = s.export_csv(out, keys)
    assert len(df) == len(s.reference.data)
    text = out.read_text(encoding="utf-8-sig")
    header = text.splitlines()[0].split(";")
    assert header[:2] == ["Time_min", "Temps (H:MM:SS)"]
    assert "essai_Clim.csv | Température (°C)" in header
    back = pd.read_csv(out, sep=";", decimal=",", encoding="utf-8-sig")
    assert back.shape == df.shape


def test_session_reports_bad_file(tmp_path):
    bad = tmp_path / "vide.csv"
    bad.write_text("")
    s = Session()
    loaded, errors = s.load_files([EXAMPLES / "essai_Clim.csv", bad])
    assert len(loaded) == 1 and len(errors) == 1 and "vide.csv" in errors[0]
