"""Décalage de zéro, comparaison avec le brut, journal des traitements et livrables client."""
import numpy as np
import pandas as pd
import pytest

from cleantrace.cleaning import CleaningOptions, clean_signal, estimate_rest_offset
from cleantrace.session import Session, journal_path


def channel_with_offset(offset, n=20000, seed=0):
    rng = np.random.default_rng(seed)
    i = np.arange(n)
    return np.where((i // 4000) % 2 == 1, 0.3, 0.0) + offset + rng.normal(0, 0.004, n)


def test_rest_offset_detected_and_removed():
    y = channel_with_offset(-0.04)
    assert estimate_rest_offset(y) == pytest.approx(-0.04, abs=0.002)
    out, report = clean_signal(y, "A", CleaningOptions(remove_peaks=False, zero_offset=True, noise_mode="zero"),
                               offset=estimate_rest_offset(y))
    assert report.offset == pytest.approx(-0.04, abs=0.002)
    assert report.noise_points > 0.95 * 12000  # le repos (60 % des points) revient bien à 0
    assert np.median(out[4000:8000]) == pytest.approx(0.3, abs=0.005)  # le palier garde sa valeur


@pytest.mark.parametrize("y", [
    24 + np.random.default_rng(1).normal(0, 0.02, 5000),  # tension d'alimentation permanente
    3 + np.random.default_rng(2).normal(0, 0.05, 5000),   # petit courant permanent
    channel_with_offset(0.0),                             # repos déjà à 0
    np.full(5000, -0.04) + np.random.default_rng(3).normal(0, 0.004, 5000),  # que du « repos » : ambigu
])
def test_no_offset_where_it_makes_no_sense(y):
    """Alimentation, petit courant permanent, repos déjà à 0 : rien à corriger."""
    assert estimate_rest_offset(y) is None


@pytest.fixture
def session(tmp_path):
    path = tmp_path / "essai.csv"
    n = 12000  # repos + paliers (une voie qui ne serait QUE du repos décalé reste ambiguë : pas corrigée)
    stamps = pd.Timestamp("2026-06-01 17:00:00") + pd.to_timedelta(np.arange(n) * 0.1, unit="s")
    y = channel_with_offset(-0.04, n=n)
    y[6500:6502] = 3.0
    lines = ["Date/Heure;I (A);U (V)"] + ["{};{};24".format(t.strftime("%d/%m/%Y %H:%M:%S.%f")[:-3],
                                                            str(round(v, 4)).replace(".", ","))
                                         for t, v in zip(stamps, y)]
    path.write_text("\n".join(lines) + "\n")
    s = Session()
    s.load_files([path])
    return s


def test_journal_traces_every_treatment(session, tmp_path):
    key = ("essai.csv", "I (A)")
    session.apply_cleaning([key], CleaningOptions(zero_offset=True, noise_mode="zero"))
    session.correct_point(key, 10)
    text = session.journal_text()
    assert "Fichier ouvert : essai.csv" in text
    assert "décalage de zéro -0.04 A soustrait" in text
    assert "point(s) de pics parasites corrigés" in text and "mis à 0" in text
    assert "Correction au clic : I (A) [essai.csv] point n°11" in text
    out = tmp_path / "export.csv"
    session.export_csv(out, [key])
    assert "Export CSV : export.csv" in journal_path(out).read_text(encoding="utf-8")


def test_raw_comparison_series(session):
    key = ("essai.csv", "I (A)")
    assert [s.raw for s in session.series([key], with_raw=True)] == [False]  # rien de modifié
    session.apply_cleaning([key], CleaningOptions())
    series = session.series([key], with_raw=True)
    assert [s.raw for s in series] == [False, True]
    assert series[1].gid.startswith("raw:") and series[1].y[6500] == pytest.approx(3.0)
    assert session.modified_points(key) > 0


def test_report_and_image(session, tmp_path):
    from cleantrace.report import build_report, save_figure_image

    keys = session.all_keys()
    session.apply_cleaning(keys, CleaningOptions())
    pdf = build_report(session, keys, (0, 5), tmp_path / "rapport.pdf")
    content = pdf.read_bytes()
    assert content.startswith(b"%PDF") and content.count(b"/Type /Page") - content.count(b"/Type /Pages") == 3
    for ext in ("png", "pdf", "svg"):
        image = save_figure_image(session, keys, None, tmp_path / ("graphique." + ext))
        assert image.stat().st_size > 1000
