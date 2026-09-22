from pathlib import Path

import pytest
import scipy.stats as sp

from laplaces_hoard.engines import stats
from laplaces_hoard.engines.data import Catalog


def test_welch_ttest_matches_scipy_exactly():
    d1, d2 = [1, 2, 3, 4, 5], [2, 3, 4, 5, 9]
    r = stats.run("ttest_ind", data=d1, data2=d2)
    ref = sp.ttest_ind(d1, d2, equal_var=False)
    assert r["statistic"] == pytest.approx(ref.statistic)
    assert r["p_value"] == pytest.approx(ref.pvalue)
    assert r["df"] == pytest.approx(ref.df)


def test_describe_basic_stats():
    r = stats.run("describe", data=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    assert r["n"] == 10
    assert r["mean"] == 5.5
    assert r["median"] == 5.5


def test_pearson_correlation():
    r = stats.run("pearson", data=[1, 2, 3, 4], data2=[2, 4, 6, 9])
    ref = sp.pearsonr([1, 2, 3, 4], [2, 4, 6, 9])
    assert r["r"] == pytest.approx(ref.statistic)


def test_proportion_ci_is_wilson_score_and_json_safe():
    r = stats.run("proportion_ci", successes=45, trials=100)
    assert isinstance(r["ci_low"], float)
    assert isinstance(r["ci_high"], float)
    assert 0.3 < r["ci_low"] < r["proportion"] < r["ci_high"] < 0.6


def test_stats_from_dataset_column_with_group_by(data_dir: Path, sample_csv: Path):
    cat = Catalog(data_dir)
    cat.register(str(sample_csv), name="sample")
    r = stats.run(
        "ttest_ind", dataset="sample", column="amount", group_by="region", catalog=cat,
        where="region IN ('North', 'South')",
    )
    assert r["n1"] == 2 and r["n2"] == 2


def test_where_clause_rejects_injection_attempts(data_dir: Path, sample_csv: Path):
    cat = Catalog(data_dir)
    cat.register(str(sample_csv), name="sample")
    with pytest.raises(stats.StatsError):
        stats.run(
            "ttest_ind", dataset="sample", column="amount", group_by="region", catalog=cat,
            where="1=1; DROP TABLE sample",
        )


def test_unknown_test_name_is_rejected():
    with pytest.raises(stats.StatsError):
        stats.run("not_a_real_test", data=[1, 2, 3])
