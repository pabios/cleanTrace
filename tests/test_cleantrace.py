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
FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Maquettes calquées sur les vrais exports du labo (exemples/)
GL980 = "GL980_Mes-_260601-170139.CSV"
NANODAC = "nanodac_Rd_Z.txt"
GL860 = EXAMPLES / "autres_formats" / "GL860_1s.CSV"
ALL_EXAMPLES = [GL980, NANODAC]
SHUNT = (GL980, "Channel 4")

# Formats d'après les manuels constructeurs (tests/fixtures/)
GL980_MANUEL = FIXTURES / "gl980_manuel.csv"
NANODAC_MANUEL = FIXTURES / "nanodac_manuel.csv"


# ------------------------------------------------------------------- US-01 import


@pytest.mark.parametrize(
    "path, source, sep, decimal, period_s, n_channels",
    [
        (EXAMPLES / GL980, "Graphtec", ",", ",", 0.1, 6),
        (EXAMPLES / NANODAC, "Nanodac", "\t", ",", 60.0, 1),
        (GL860, "Graphtec", ",", ".", 1.0, 10),
        (GL980_MANUEL, "Graphtec", ",", ".", 0.5, 3),
        (NANODAC_MANUEL, "Nanodac", "\t", ",", 10.0, 3),
    ],
)
def test_import_formats(path, source, sep, decimal, period_s, n_channels):
    m = load_measurement(path)
    assert m.source == source
    assert m.separator == sep
    assert m.decimal == decimal
    assert m.period_s == pytest.approx(period_s)
    assert len(m.channels) == n_channels
    assert m.start is not None
    assert m.data[TIME_COL].iloc[0] == 0


def test_real_gl980_layout():
    """Export GL980 réel : Vendor/Model…, AMP settings, XY, Position/Vernier, Data."""
    m = load_measurement(EXAMPLES / GL980)
    assert [c.label for c in m.channels] == [
        "Channel 3", "Channel 4", "Channel 5",
        "Channel 6", "Channel 7", "Channel 8",
    ]
    assert m.start == pd.Timestamp("2026-06-01 17:01:39")  # colonnes Date + Time + us
    assert m.duration_min == pytest.approx(40, abs=0.01)


def test_real_nanodac_unit_from_descriptor():
    """« Date/Heure  Channel 2  (ENAN2);Group 1;M402-M210;°C » : c'est une température."""
    m = load_measurement(EXAMPLES / NANODAC)
    assert [c.label for c in m.channels] == ["Channel 2"]
    assert m.channels[0].quantity == TEMPERATURE
    assert m.is_thermal
    assert m.start == pd.Timestamp("2026-06-01 16:57:00")  # année sur 2 chiffres


def test_nanodac_descriptor_in_separate_column(tmp_path):
    f = tmp_path / "Rd_Z.txt"
    f.write_bytes("Date/Heure\tChannel 2\t\t(ENAN2);Group 1;M402-M210;°C\r\n"
                  "03/06/26 16:42:00\t27,89\r\n03/06/26 16:43:00\t27,84\r\n03/06/26 16:44:00\t28,02\r\n"
                  .encode("cp1252"))
    m = load_measurement(f)
    assert [c.label for c in m.channels] == ["Channel 2"]
    assert m.start == pd.Timestamp("2026-06-03 16:42:00")


def test_files_from_different_tests_start_at_zero():
    """1s.CSV (10/09) et Rd_Z (03/06) : rien en commun, chacun démarre à 0 avec une explication."""
    ms = [load_measurement(GL860), load_measurement(EXAMPLES / NANODAC)]
    ref = align_time_axes(ms)
    other = ms[0] if ref is ms[1] else ms[1]
    assert other.data[TIME_COL].iloc[0] == 0
    assert "même période" in other.align_note
    assert ref.align_note == ""


def test_real_gl860_double_header():
    """En-têtes sur deux lignes : No.,Date&Time,ms,CH1… puis NO.,Time,ms,V,mA…,A1234567890."""
    m = load_measurement(GL860)
    labels = [c.label for c in m.channels]
    assert labels[:3] == ["Channel 1", "Channel 2", "Channel 3"]
    assert labels[-2:] == ["Channel 11", "Channel 13"]
    assert m.start == pd.Timestamp("2026-09-10 14:53:39")


def test_gl980_amp_settings_and_over_range():
    m = load_measurement(GL980_MANUEL)
    # noms de signaux et unités du tableau « Amp settings », voie CH4 (Off) ignorée,
    # colonnes d'alarme (texte) ignorées
    assert [c.label for c in m.channels] == [
        "Channel 1", "Channel 2", "Channel 3",
    ]
    assert m.start == pd.Timestamp("2026-10-01 09:00:30")
    assert m.period_s == pytest.approx(0.5)  # colonne « ms » prise en compte
    assert m.data["Channel 2"].isna().sum() == 12  # « +++++++ » / « ------- »
    assert any("hors échelle" in w for w in m.warnings)
    assert not m.is_thermal


def test_nanodac_spreadsheet_date_and_ascii_units():
    m = load_measurement(NANODAC_MANUEL)
    assert [c.label for c in m.channels] == ["T enceinte (°C)", "HR enceinte (%HR)", "Consigne T (°C)"]
    assert m.start == pd.Timestamp("2026-10-01 09:00:00")  # 46296,375 jours depuis 1899
    assert m.is_thermal


def test_nanodac_text_date_comma_separator(tmp_path):
    f = tmp_path / "nanodac_texte.csv"
    f.write_bytes(
        b"Instrument,nanodac\r\n\r\n"
        b"Date/Time,Four Z1,Messages\r\n,degC,\r\n"
        b"01/10/2026 09:00:00,25.1,\r\n"
        b"01/10/2026 09:00:01,25.2,Alarm 1 on\r\n"
        b"01/10/2026 09:00:02,25.3,\r\n"
    )
    m = load_measurement(f)
    assert [c.label for c in m.channels] == ["Four Z1 (°C)"]
    assert m.start == pd.Timestamp("2026-10-01 09:00:00")
    assert m.period_s == 1.0


def test_reference_prefers_fine_sampling_among_longest():
    """Le nanodac (1 min) couvre un peu plus large, mais l'export doit garder les 100 ms du GL980."""
    ms = [load_measurement(EXAMPLES / f) for f in ALL_EXAMPLES]
    assert ms[1].duration_min > ms[0].duration_min
    ref = align_time_axes(ms)
    assert ref.name == GL980
    assert ms[1].data[TIME_COL].iloc[0] == pytest.approx(-4.65)  # nanodac démarre 4 min 39 s avant


def test_reference_is_longest_file():
    ms = [load_measurement(p) for p in (GL980_MANUEL, NANODAC_MANUEL)]
    assert align_time_axes(ms).path == GL980_MANUEL
    assert ms[1].data[TIME_COL].iloc[0] == pytest.approx(-0.5)  # démarre 30 s avant


def test_graphset_is_preferred_reference(tmp_path):
    a = tmp_path / "graphset.csv"
    b = tmp_path / "long.csv"
    a.write_text("Temps (s);U (V)\n0;1\n1;1\n2;1\n3;1\n")
    b.write_text("Temps (s);U (V)\n0;1\n1;1\n2;1\n3;1\n4;1\n5;1\n")
    ms = [load_measurement(a), load_measurement(b)]
    assert align_time_axes(ms).path == a


def test_gl980_mostly_text_columns(tmp_path):
    """Lignes où la majorité des colonnes ne sont pas des nombres (cas réel refusé avant)."""
    head = (
        '"Model","GL980"\n"Title",""\n"Trigger Time","\'2026/06/01 17:01:39"\n\n"Data"\n'
        '"NO.","Time","us","CH1","CH2","CH3","CH4","CH5","CH6","CH7","CH8",'
        '"Logic1-4","Pulse1","Alarm1-10","Alarm11-20","AlarmPulse","AlarmOut"\n'
        '"","","","V","V","degC","degC","degC","degC","degC","degC","","","","","",""\n'
    )
    rows = "".join(
        '{},2026/06/01 17:01:{:02d},{},+1.234,+0.512,BURNOUT,BURNOUT,BURNOUT,BURNOUT,BURNOUT,+++++++,'
        'LLLL,LLLL,LLLLLLLLLL,LLLLLLLLLL,LLLL,LLLL\n'.format(k + 1, 39 + k // 10, (k % 10) * 100000)
        for k in range(150)
    )
    f = tmp_path / "Mes-_260601-170139.CSV"
    f.write_text(head + rows)
    m = load_measurement(f)
    assert m.source == "Graphtec"
    assert [c.label for c in m.channels] == ["Channel 1", "Channel 2"]
    assert m.period_s == pytest.approx(0.1)  # colonne « us »
    assert m.start == pd.Timestamp("2026-06-01 17:01:39")


def test_unreadable_file_error_shows_diagnostic(tmp_path):
    f = tmp_path / "bizarre.csv"
    f.write_text("Rapport\nfoo;bar\nbaz;qux\nquux;corge\n")
    with pytest.raises(LoadError, match="Diagnostic : encodage utf-8, séparateur point-virgule"):
        load_measurement(f)


def test_binary_export_is_explained(tmp_path):
    f = tmp_path / "essai.GBD"
    f.write_bytes(b"GBD\x00\x01\x02" * 100)
    with pytest.raises(LoadError, match="binaire"):
        load_measurement(f)


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
        ("CH1", "Channel 1", "autre"),  # unité inconnue : jamais supposée hors Graphtec
        ("CH03[V]", "Channel 3", VOLTAGE),
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


def test_graphtec_channel_default_unit():
    assert make_channel("CH1", default_unit="mV").label == "Channel 1"


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


def test_noisy_plateau_top_is_not_shaved():
    """Créneau bruité dont le palier haut est au maximum : le haut du bruit n'est pas un pic."""
    rng = np.random.default_rng(3)
    t = np.arange(670)
    y = np.where((t // 60) % 2 == 0, 160.0, 85.0) + rng.normal(0, 1.2, len(t))
    out, n = remove_saturation_peaks(y)
    assert n == 0
    np.testing.assert_array_equal(out, y)
    y[200] = y[400] = 300.0  # vrais pics de saturation (palier bas à 200, haut à 400) : ils partent
    out, n = remove_saturation_peaks(y)
    assert n == 2 and abs(out[200] - 85) < 5 and abs(out[400] - 160) < 5  # remis au niveau du palier


def test_spikes_of_any_height_removed_edges_untouched():
    """Parasites de hauteurs variées (pas seulement la saturation), y compris juste avant un
    front de créneau : tous retirés, et le front lui-même n'est pas déformé."""
    rng = np.random.default_rng(0)
    n = 20000
    i = np.arange(n)
    clean = np.where((i // 2000) % 2 == 1, 0.3 * np.exp(-((i % 2000) / 1500)), 0.0) + rng.normal(0, 0.003, n)
    y = clean.copy()
    spikes = list(rng.choice(np.arange(50, n - 50), 40, replace=False)) + [1995]  # 1995 : juste avant un front
    for pos in spikes:
        y[pos:pos + 2] = rng.choice([-1, 1]) * rng.uniform(0.8, 3.6)
    out, n_fixed = remove_saturation_peaks(y)
    assert np.sum(np.abs(out) > 0.5) == 0  # plus aucun parasite
    hit = np.zeros(n, bool)
    for pos in spikes:
        hit[pos:pos + 2] = True
    np.testing.assert_array_equal(out[~hit], y[~hit])  # rien d'autre n'a bougé (fronts compris)
    # l'ancienne règle (saturation seule) laissait la plupart des parasites
    old, _ = remove_saturation_peaks(y, saturation_only=True)
    assert np.sum(np.abs(old) > 0.5) > 20


def test_burst_of_adjacent_spikes_removed_but_real_pulse_kept():
    """Deux parasites accolés (6 points erratiques) : retirés. Une vraie impulsion de 7 points
    (plateau régulier) : conservée."""
    rng = np.random.default_rng(11)
    y = 160 + rng.normal(0, 1.0, 600)
    y[200:206] = [493, 499, 497, 305, 200, 279]  # rafale de parasites
    y[400:407] = 260 + rng.normal(0, 1.0, 7)  # vraie impulsion courte et stable
    out, n = remove_saturation_peaks(y)
    assert np.all(out[200:206] < 170)
    np.testing.assert_array_equal(out[400:407], y[400:407])


def test_pure_noise_channel_untouched():
    """Voie sans signal (0,02 mA ± bruit) : rien n'est un pic."""
    rng = np.random.default_rng(4)
    y = np.round(0.02 + rng.normal(0, 0.01, 670), 2)
    assert remove_saturation_peaks(y)[1] == 0


def test_noise_threshold_suggestion():
    from cleantrace.cleaning import suggest_noise_threshold

    rng = np.random.default_rng(5)
    y = np.r_[np.full(500, 5.0), np.zeros(500), np.full(500, -5.0)] + rng.normal(0, 0.015, 1500)
    s = suggest_noise_threshold(y)
    assert 0.03 < s < 0.1  # bruit ±30-45 mA -> seuil ~50-70 mA (le seuil fixe de 10 mA était trop bas)
    out, report = clean_signal(y, "A", CleaningOptions(remove_peaks=False, remove_noise=False, zero_rest=True), noise_threshold=s)
    assert report.noise_points >= 495 and (out[500:1000] == 0).mean() > 0.99
    # petit courant permanent : aucune suggestion, et seuil vide = rien d'effacé
    small = 3.0 + rng.normal(0, 0.05, 670)
    assert suggest_noise_threshold(small) is None
    out, report = clean_signal(small, "mA", CleaningOptions(remove_peaks=False, remove_noise=False, zero_rest=True),
                               noise_threshold=None)
    assert report.noise_points == 0


def test_session_thresholds_preview_and_apply():
    s = Session()
    s.load_files([GL860])
    key = (GL860.name, "Channel 11")
    before = s.measurements[key[0]].data[key[1]].copy()
    assert s.noise_threshold(key) is None  # 2 à 4 mA permanents : pas de mise à 0 par défaut
    zero = CleaningOptions(remove_noise=False, zero_rest=True)
    assert s.preview_cleaning([key], zero)[key].noise_points == 0
    # seuil imposé à 10 mA : l'aperçu montre que tout serait effacé, sans rien modifier
    assert s.preview_cleaning([key], zero, {key: 10.0})[key].noise_points == len(before)
    pd.testing.assert_series_equal(s.measurements[key[0]].data[key[1]], before)
    s.apply_cleaning([key], zero, thresholds={key: 0.5})
    assert s.noise_threshold(key) == 0.5  # réglage mémorisé
    assert (s.measurements[key[0]].data[key[1]] != 0).all()
    s2 = Session()
    s2.load_files([EXAMPLES / GL980])
    # voie avec repos à 0 : seuil calculé sur le bruit réel des repos (pas un seuil fixe)
    assert s2.noise_threshold(SHUNT) == s2.suggest_noise_threshold(SHUNT) != 0.010


def test_genuine_plateau_at_max_is_kept():
    y = square_wave()
    out, n = remove_saturation_peaks(y)
    assert n == 0
    np.testing.assert_array_equal(out, y)


def test_cycle_extremes_preserved_with_noise():
    rng = np.random.default_rng(0)
    y = square_wave() + rng.normal(0, 0.003, 500)
    y[120] = 5.0
    out, _ = clean_signal(y, "A", CleaningOptions(remove_noise=False, zero_rest=True))  # règle d'origine (forcer à 0)
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


def test_smoothing_keeps_edges_levels_and_shapes():
    """Lisser sans mettre à 0 : bruit réduit, créneaux verticaux, niveaux et décharge conservés."""
    from cleantrace.cleaning import smooth_preserving_edges

    rng = np.random.default_rng(8)
    t = np.arange(6000)
    clean = np.where((t // 1000) % 3 == 0, 0.0, np.where((t // 1000) % 3 == 1, 5.0, 0.3 * np.exp(-(t % 1000) / 300)))
    y = clean + rng.normal(0, 0.02, len(t))
    out, n = smooth_preserving_edges(y, 11)
    assert n > 0.9 * len(t)
    assert np.std(out - clean) < 0.4 * np.std(y - clean)  # bruit nettement réduit
    for edge in (1000, 2000, 4000):  # fronts : toujours verticaux (pas de pente)
        assert abs(out[edge - 1] - clean[edge - 1]) < 0.05 and abs(out[edge] - clean[edge]) < 0.05
    assert abs(np.mean(out[1100:1900]) - 5.0) < 0.01  # le palier garde son vrai niveau
    assert np.all(out[200:800] != 0)  # rien n'est forcé à 0 : on garde le niveau mesuré
    np.testing.assert_allclose(out[2050:2900], clean[2050:2900], atol=0.02)  # décharge conservée


def test_default_cleaning_never_zeroes_real_signal():
    """Petit courant réel (0,005 A, sous l'ancien seuil fixe de 10 mA) : gardé tel quel en moyenne."""
    rng = np.random.default_rng(9)
    y = np.r_[np.zeros(2000), np.full(2000, 0.005)] + rng.normal(0, 0.0005, 4000)
    out, report = clean_signal(y, "A", CleaningOptions())
    assert report.noise_points == 0
    assert abs(np.mean(out[2200:3800]) - 0.005) < 0.0002


def test_options_disable_treatments():
    y = square_wave() + 0.001
    y[150] = 5.0
    out, report = clean_signal(y, "A", CleaningOptions(remove_noise=False, remove_peaks=False))
    np.testing.assert_array_equal(out, y)
    assert report.total == 0


def test_short_over_range_gaps_repaired():
    y = square_wave()
    y[150] = np.nan  # « +++++++ » isolé sur le palier
    y[[20, 21]] = np.nan
    y[250:300] = np.nan  # longue coupure : reste vide
    out, n = remove_saturation_peaks(y)
    assert n == 3
    assert out[150] == 2.0 and out[20] == 0.0
    assert np.isnan(out[250:300]).all()


def test_nan_values_are_kept():
    y = square_wave()
    y[10:30] = np.nan  # coupure de mesure plus longue qu'un pic : pas inventée
    y[150] = 5.0
    out, n = remove_saturation_peaks(y)
    assert np.isnan(out[10:30]).all() and n == 1


# ------------------------------------------------------------ US-04 / US-05


def test_format_hms():
    from cleantrace.export import hms_column

    values = [0, 61.5, -0.5, 1234.567]
    assert list(hms_column(np.array(values))) == [format_hms(v) for v in values]
    assert format_hms(0) == "0:00:00"
    assert format_hms(61.5) == "1:01:30"
    assert format_hms(-0.5) == "-0:00:30"


def test_time_axis_ticks_stay_readable():
    from cleantrace.plotting import TimeLocator, format_axis_time

    ticks = TimeLocator().tick_values(0, 140_000)  # ~97 jours (deux essais très éloignés)
    assert 2 <= len(ticks) <= 9
    assert format_axis_time(ticks[1]) == "336:00:00"
    assert list(TimeLocator().tick_values(0, 40)) == [0, 5, 10, 15, 20, 25, 30, 35, 40]
    assert format_axis_time(90) == "1:30:00"
    assert format_axis_time(48 * 60) == "48:00:00"  # pas de « 2 j » : H:MM:SS demandé par le client


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
    corrector = ClickCorrector(fig, lambda gid, idx: calls.append((gid, idx)))  # noqa: F841 (référence à garder : Matplotlib ne garde qu une référence faible)
    px, py = twin.transData.transform((2, 9))
    event = MouseEvent("button_press_event", fig.canvas, px, py, button=1)
    fig.canvas.callbacks.process("button_press_event", event)
    assert calls == [("b", 2)]


def test_decimation_keeps_spikes_and_maps_indices():
    from cleantrace.plotting import decimate_indices

    y = np.zeros(1_000_000)
    y[123_457] = 999.0  # pic isolé au milieu d'un million de points
    y[800_001] = -999.0
    idx = decimate_indices(y, 0, len(y), buckets=1000)
    assert len(idx) <= 2002
    assert 123_457 in idx and 800_001 in idx  # aucun pic ne disparaît
    assert idx[0] == 0 and idx[-1] == len(y) - 1
    np.testing.assert_array_equal(decimate_indices(y, 10, 50), np.arange(10, 50))  # zoom : tout


# ------------------------------------------------------------ session + US-06


def test_session_end_to_end(tmp_path):
    s = Session()
    loaded, errors = s.load_files([EXAMPLES / f for f in ALL_EXAMPLES])
    assert len(loaded) == 2 and not errors
    keys = s.all_keys()
    assert len(keys) == 7

    shunt = SHUNT
    raw = s.measurements[shunt[0]].data[shunt[1]].to_numpy().copy()
    report = s.apply_cleaning([shunt], CleaningOptions())
    cleaned = s.measurements[shunt[0]].data[shunt[1]].to_numpy()
    assert report.peak_points > 0 and report.smoothed_points > 0 and report.noise_points == 0  # lissé, pas mis à 0
    assert np.nanmax(cleaned) < 5.1  # plus de saturation à 10 A
    assert np.nanmax(cleaned) > 4.95  # mais les paliers de charge (5 A) sont intacts
    assert np.nanmin(cleaned) < -4.95

    s.set_value(shunt, 10, 42.0)
    assert s.measurements[shunt[0]].data[shunt[1]].iloc[10] == 42.0
    data = s.measurements[shunt[0]].data
    expected = (data[shunt[1]].iloc[9] + data[shunt[1]].iloc[11]) / 2  # pas de temps régulier
    assert s.correct_point(shunt, 10) == pytest.approx(expected)
    s.restore_raw([shunt])
    np.testing.assert_array_equal(s.measurements[shunt[0]].data[shunt[1]].to_numpy(), raw)

    # seul le fichier de l'enceinte suit le curseur de décalage
    shiftable = {sr.label: sr.shiftable for sr in s.series(keys)}
    assert shiftable["Channel 2 — nanodac_Rd_Z.txt"]
    assert not any(v for k, v in shiftable.items() if k.endswith(GL980))

    s.time_offset_min = -4
    out = tmp_path / "export.csv"
    df = s.export_csv(out, keys)
    assert len(df) == len(s.reference.data)
    text = out.read_text(encoding="utf-8-sig")
    header = text.splitlines()[0].split(";")
    assert header[:2] == ["Time_min", "Temps (H:MM:SS)"]
    assert "nanodac_Rd_Z.txt | Channel 2" in header
    back = pd.read_csv(out, sep=";", decimal=",", encoding="utf-8-sig")
    assert back.shape == df.shape


def test_session_reports_bad_file(tmp_path):
    bad = tmp_path / "vide.csv"
    bad.write_text("")
    s = Session()
    loaded, errors = s.load_files([EXAMPLES / NANODAC, bad])
    assert len(loaded) == 1 and len(errors) == 1
    assert errors[0][0] == bad and "vide.csv" in errors[0][1]


def test_write_extract_keeps_head_and_tail(tmp_path):
    from cleantrace.loader import write_extract

    out = write_extract(EXAMPLES / GL980, tmp_path / "extrait.txt")
    text = out.read_bytes().decode("cp1252")
    assert text.startswith("Vendor,GRAPHTEC Corporation")
    assert "Number,Date,Time,us,CH3" in text  # début des données inclus
    assert "[...]" in text and out.stat().st_size < 20_000


def test_gl860_example_saturation_spikes_cleaned():
    """Exemple GL860 : pics de saturation (±pleine échelle), parasites intermédiaires et « +++++++ »
    sur les voies de puissance. Tous retirés par défaut ; paliers et petits courants intacts."""
    s = Session()
    s.load_files([GL860])
    name = GL860.name
    data = s.measurements[name].data
    power = ["Channel 1", "Channel 2", "Channel 3", "Channel 5", "Channel 6", "Channel 7", "Channel 8"]
    small = ["Channel 4", "Channel 11", "Channel 13"]
    raw = {label: data[label].to_numpy().copy() for label in power + small}
    assert all(np.nanmax(np.abs(raw[label])) > 1.3 * np.nanpercentile(np.abs(raw[label]), 95) for label in power)
    assert sum(np.isnan(raw[label]).sum() for label in power) == 7  # un « +++++++ » par voie

    report = s.apply_cleaning([(name, label) for label in power + small], CleaningOptions())
    assert report.peak_points >= 7 * 8  # au moins un point par pic (8 pics par voie)
    for label in power:
        cleaned = data[label].to_numpy()
        assert not np.isnan(cleaned).any()  # hors échelle comblés
        plateau = np.percentile(raw[label][np.isfinite(raw[label])], [5, 95])  # paliers bas et haut
        margin = 0.1 * (plateau[1] - plateau[0])
        assert cleaned.max() < plateau[1] + margin and cleaned.min() > plateau[0] - margin, label
    for label in small:  # pas de pics : seulement lissées, niveau moyen conservé, jamais mises à 0
        cleaned = data[label].to_numpy()
        assert abs(np.mean(cleaned) - np.mean(raw[label])) < 0.01 * (abs(np.mean(raw[label])) + 0.01)
        assert np.mean(cleaned == 0) < 0.5


def _rest_square(rest, amp, noise, spikes=0.0, seed=1):
    rng = np.random.default_rng(seed)
    y = np.tile(np.r_[np.full(300, rest), np.full(300, amp)], 10) + rng.normal(0, noise, 6000)
    if spikes:
        y[rng.choice(6000, 30, replace=False)] = spikes
    return y


@pytest.mark.parametrize("rest, spikes", [(-0.04, 0.0), (-0.04, 10.0), (0.0, 10.0), (0.03, 0.0)])
def test_zero_rest_works_with_offset_rest_and_spikes(rest, spikes):
    """Retour client v0.8.1 : « Forcer à 0 » ne changeait rien (repos à −0,04 A non reconnu)
    ou mettait tout à 0 (seuil faussé par un pic de saturation à 10 A)."""
    from cleantrace.cleaning import has_rest_phase, suggest_noise_threshold

    y = _rest_square(rest, 0.5, 0.005, spikes)
    assert has_rest_phase(y)
    threshold = suggest_noise_threshold(y)
    assert abs(rest) < threshold < 0.25
    options = CleaningOptions(remove_noise=True, zero_rest=True)  # lisser ET forcer à 0
    out, report = clean_signal(y, "A", options, noise_threshold=threshold)
    phases = out.reshape(10, 2, 300)
    assert (phases[:, 0, 5:-5] == 0).all()  # repos exactement à 0
    assert abs(np.median(phases[:, 1, :]) - 0.5) < 0.01  # paliers intacts
    assert out.max() < 0.6  # pics retirés
    assert report.smoothed_points and report.noise_points >= 2900


def test_zero_rest_off_by_default_and_never_on_permanent_signal():
    from cleantrace.cleaning import has_rest_phase

    assert not CleaningOptions().zero_rest
    supply = 24 + np.random.default_rng(0).normal(0, 0.02, 5000)
    assert not has_rest_phase(supply)


def test_parse_hms_for_axis_limits():
    from cleantrace.plotting import parse_hms

    assert parse_hms("1:30:00") == 90
    assert parse_hms("48:00:00") == 48 * 60
    assert parse_hms("0:00:30") == 0.5
    assert parse_hms("2:15") == 135
    assert parse_hms("-0:01:00") == -1
    assert parse_hms("  ") is None
    for bad in ("abc", "1:75:00", "90", "1::"):
        with pytest.raises(ValueError):
            parse_hms(bad)


def test_plot_settings_are_applied_and_kept(tmp_path):
    from matplotlib.figure import Figure

    from cleantrace.plotting import MAIN_AXIS, AxisSettings, CurveStyle, PlotManager, PlotSeries, PlotSettings

    x = np.linspace(0, 600, 6001)
    series = [PlotSeries(gid="0", label="Channel 4", x=x, y=np.sin(x) + 2, unit="A", quantity="courant",
                         key=("f.csv", "Channel 4"))]
    settings = PlotSettings(title="Essai 42", x=AxisSettings(min=60, max=120, label="Durée"),
                            y={MAIN_AXIS: AxisSettings(min=0.5, max=5, label="Courant", log=True)},
                            curves={("f.csv", "Channel 4"): CurveStyle(name="Shunt", color="#ff0000", width=2.5,
                                                                        style="--", marker="o")})
    fig = Figure()
    plot = PlotManager(fig)
    plot.draw(series, settings=settings)
    ax = plot.axes[MAIN_AXIS]
    assert ax.get_xlim() == (60, 120) and ax.get_ylim() == (0.5, 5)
    assert ax.get_yscale() == "log" and ax.get_ylabel() == "Courant" and ax.get_xlabel() == "Durée"
    assert ax.get_title(loc="left") == "Essai 42"
    line = ax.get_lines()[0]
    assert (line.get_label(), line.get_color(), line.get_linewidth(), line.get_linestyle(), line.get_marker()) == \
        ("Shunt", "#ff0000", 2.5, "--", "o")
    assert plot.colors["0"] == "#ff0000"  # pastille de la liste des voies assortie
    # seuls les points de la période choisie sont tracés (pas toute la courbe)
    assert line.get_xdata().min() >= 59 and line.get_xdata().max() <= 121
    fig.canvas.draw()  # mise en page automatique sans erreur

    settings.clear_limits()  # bouton « Maison »
    plot.draw(series, settings=settings)
    assert ax is not plot.axes[MAIN_AXIS] and plot.axes[MAIN_AXIS].get_xlim()[1] >= 600
    assert plot.axes[MAIN_AXIS].get_ylabel() == "Courant"  # libellés gardés


def test_report_uses_plot_settings(tmp_path):
    from cleantrace.plotting import AxisSettings, PlotSettings
    from cleantrace.report import _plot_figure

    s = Session()
    s.load_files([str(EXAMPLES / "GL980_Mes-_260601-170139.CSV")])
    name = next(iter(s.measurements))
    fig = _plot_figure(s, [(name, "Channel 4")], None, "Rapport",
                       PlotSettings(title="Mon essai", x=AxisSettings(min=5, max=10)))
    assert fig.axes[0].get_xlim() == (5, 10)
    assert fig.axes[0].get_title(loc="left") == "Mon essai"
