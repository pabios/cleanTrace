"""Superposition de plusieurs fichiers : bases de temps et grille d'export."""
import numpy as np
import pandas as pd
import pytest

from cleantrace.loader import TIME_COL
from cleantrace.session import Session


def write(path, start, n, step_s, value):
    stamps = pd.Timestamp(start) + pd.to_timedelta(np.arange(n) * step_s, unit="s")
    lines = ["Date/Heure;U (V)"] + ["{};{}".format(t.strftime("%d/%m/%Y %H:%M:%S"), str(value + k * 0.001).replace(".", ","))
                                   for k, t in enumerate(stamps)]
    path.write_text("\n".join(lines) + "\n")
    return path


@pytest.fixture
def session(tmp_path):
    """A : 10:00 -> 10:10 (1 s) ; B : 10:05 -> 10:20 (10 s). Elles se recouvrent de 10:05 à 10:10."""
    s = Session()
    s.load_files([write(tmp_path / "A.csv", "2026-06-01 10:00:00", 601, 1, 1.0),
                  write(tmp_path / "B.csv", "2026-06-01 10:05:00", 91, 10, 2.0)])
    assert s.reference.name == "A.csv"  # le plus fin parmi les plus longs
    return s


def first_last(s, name):
    x = s.measurements[name].data[TIME_COL]
    return x.iloc[0], x.iloc[-1]


def test_real_time(session):
    assert first_last(session, "A.csv") == (0, 10)
    assert first_last(session, "B.csv") == pytest.approx((5, 20))


def test_common_period_starts_and_ends_together(session, tmp_path):
    session.set_time_mode("common")
    assert session.window == pytest.approx((5, 10))
    assert session.window_start == pd.Timestamp("2026-06-01 10:05:00")
    for sr in session.series(session.all_keys()):
        assert sr.x[0] == pytest.approx(5) and sr.x[-1] == pytest.approx(10)
    a = session.series([("A.csv", "U (V)")])[0]
    assert a.index_base == 300  # le 1er point affiché est le 301e du fichier
    df = session.export_csv(tmp_path / "export.csv", session.all_keys())
    assert df[TIME_COL].iloc[0] == pytest.approx(5) and df[TIME_COL].iloc[-1] == pytest.approx(10)
    assert len(df) == 301 and df.notna().all().all()  # une valeur de chaque fichier sur chaque ligne


def test_starts_at_zero(session):
    session.set_time_mode("zero")
    assert first_last(session, "A.csv") == (0, 10)
    assert first_last(session, "B.csv") == pytest.approx((0, 15))


def test_stretched_to_same_duration(session, tmp_path):
    session.set_time_mode("stretch")
    assert first_last(session, "A.csv") == pytest.approx((0, 100))
    assert first_last(session, "B.csv") == pytest.approx((0, 100))
    assert not any(sr.shiftable for sr in session.series(session.all_keys()))
    df = session.export_csv(tmp_path / "export.csv", session.all_keys())
    assert list(df.columns)[0] == "Avancement (%)" and "Temps (H:MM:SS)" not in df.columns
    assert df.notna().all().all()


@pytest.mark.parametrize("step_s, rows", [(1.0, 301), (10.0, 31), (60.0, 6)])
def test_common_export_grid(session, tmp_path, step_s, rows):
    session.set_time_mode("common")
    session.export_step_s = step_s
    df = session.export_csv(tmp_path / "export.csv", session.all_keys())
    assert len(df) == rows
    assert np.diff(df[TIME_COL]) == pytest.approx(step_s / 60)
    assert df.notna().all().all()


def test_export_grid_over_whole_span(session, tmp_path):
    session.export_step_s = 60.0
    df = session.export_csv(tmp_path / "export.csv", session.all_keys())
    assert df[TIME_COL].iloc[0] == 0 and df[TIME_COL].iloc[-1] == pytest.approx(20)
    assert df["A.csv | U (V)"].iloc[-1] != df["A.csv | U (V)"].iloc[-1]  # A ne mesure plus : vide (NaN)


def test_click_on_cropped_curve_targets_real_point(session):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    from cleantrace.plotting import PlotManager

    session.set_time_mode("common")
    fig = Figure()
    FigureCanvasAgg(fig)
    plot = PlotManager(fig)
    series = session.series([("A.csv", "U (V)")])
    plot.draw(series)
    assert plot.original_index(series[0].gid, 0) == 300
