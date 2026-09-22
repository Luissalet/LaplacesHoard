from pathlib import Path

import pytest

from laplaces_hoard.engines import charts
from laplaces_hoard.engines.data import Catalog


@pytest.fixture()
def catalog(data_dir: Path, sample_csv: Path) -> Catalog:
    cat = Catalog(data_dir)
    cat.register(str(sample_csv), name="sample")
    return cat


def test_bar_chart_renders_a_real_png(catalog, tmp_path):
    out = tmp_path / "chart.png"
    result = charts.build_chart(
        catalog, "SELECT region, SUM(amount) AS total FROM sample GROUP BY region",
        kind="bar", x="region", y="total", out_path=out,
    )
    assert result["png_bytes"][:8] == b"\x89PNG\r\n\x1a\n"
    assert out.exists()
    assert out.stat().st_size > 100


def test_unknown_chart_kind_is_rejected(catalog):
    with pytest.raises(charts.ChartError):
        charts.build_chart(catalog, "SELECT region FROM sample", kind="not_a_kind", x="region")


def test_chart_field_must_exist_in_result(catalog):
    with pytest.raises(charts.ChartError):
        charts.build_chart(catalog, "SELECT region FROM sample", kind="bar", x="does_not_exist")
