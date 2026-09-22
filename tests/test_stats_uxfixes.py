"""Regression from the first user walk (docs/USABILITY_REPORT.md): pearson/
spearman/linregress (and the paired tests) used to resolve each column's
NULLs independently, so a NULL in x on one row and a NULL in y on a
different row shrank the two samples to different lengths - "got 411 and
406" - even though every row with both values present was usable."""
import csv
from pathlib import Path

import pytest

from laplaces_hoard.engines import stats
from laplaces_hoard.engines.data import Catalog


def _write(path: Path, rows: list[tuple]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["x", "y"])
        w.writerows(rows)
    return path


@pytest.fixture()
def catalog_with_offset_nulls(tmp_path) -> Catalog:
    # x is NULL on row 2, y is NULL on row 4: 3 rows have both values.
    # Independently-dropped NULLs would give len(x)=4, len(y)=4 but on
    # DIFFERENT rows for the 4th value, silently pairing the wrong x with y.
    rows = [(1, 10), (None, 20), (3, 30), (4, None), (5, 50)]
    cat = Catalog(tmp_path / "data")
    cat.register(str(_write(tmp_path / "t.csv", rows)))
    return cat


def test_pearson_drops_nulls_in_pairs_not_independently(catalog_with_offset_nulls):
    r = stats.run("pearson", dataset="t", column="x", column2="y", catalog=catalog_with_offset_nulls)
    assert r["n"] == 3  # rows 1, 3, 5 only


def test_linregress_uses_the_same_paired_rows(catalog_with_offset_nulls):
    r = stats.run("linregress", dataset="t", column="x", column2="y", catalog=catalog_with_offset_nulls)
    assert r["n"] == 3
    # (1,10), (3,30), (5,50) is a perfect line y = 10x
    assert r["slope"] == pytest.approx(10.0)
    assert r["r_squared"] == pytest.approx(1.0)


def test_ttest_rel_uses_the_same_paired_rows(catalog_with_offset_nulls):
    r = stats.run("ttest_rel", dataset="t", column="x", column2="y", catalog=catalog_with_offset_nulls)
    assert r["n"] == 3


def test_inline_data_pairs_are_left_exactly_as_given():
    # inline data/data2 are trusted as already paired by the caller
    r = stats.run("pearson", data=[1, 2, 3, 4], data2=[2, 4, 6, 9])
    assert r["n"] == 4
