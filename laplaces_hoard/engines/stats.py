"""Descriptive statistics and hypothesis tests, backed by NumPy/SciPy.

Every test names itself, reports the standard numbers (statistic, p-value,
effect size where standard, n per group) and adds one neutral, textbook
sentence of interpretation — deliberately not a verdict, since only the
human knows what the numbers are for.

Data can be given as inline `data`/`data2` lists, or resolved from a
registered dataset + column via the `data` engine's `Catalog`.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import numpy as np
from scipy import stats as sp

from .data import Catalog, DataError

__all__ = ["run", "StatsError", "TESTS"]

TESTS = (
    "describe", "ttest_1samp", "ttest_ind", "ttest_rel", "mannwhitneyu",
    "wilcoxon", "chi2_contingency", "fisher_exact", "pearson", "spearman",
    "linregress", "proportion_ci", "normal_ci", "binom_test",
)


class StatsError(ValueError):
    pass


def _resolve_column(catalog: Catalog, dataset: str, column: str, where: Optional[str] = None) -> list[float]:
    safe_col = _quote_ident(column)
    sql = f'SELECT {safe_col} FROM {_quote_ident(dataset)} WHERE {safe_col} IS NOT NULL'
    if where:
        _validate_where(where)
        sql += f" AND ({where})"
    result = catalog.query_all(sql)
    return [float(row[column]) for row in result["rows"] if row[column] is not None]


def _resolve_grouped(catalog: Catalog, dataset: str, column: str, group_by: str, where: Optional[str] = None):
    safe_col = _quote_ident(column)
    safe_group = _quote_ident(group_by)
    sql = f"SELECT {safe_group} AS grp, {safe_col} AS val FROM {_quote_ident(dataset)} WHERE {safe_col} IS NOT NULL"
    if where:
        _validate_where(where)
        sql += f" AND ({where})"
    result = catalog.query_all(sql)
    groups: dict[str, list[float]] = {}
    for row in result["rows"]:
        groups.setdefault(str(row["grp"]), []).append(float(row["val"]))
    return groups


def _quote_ident(name: str) -> str:
    if not name or not all(c.isalnum() or c == "_" for c in name):
        raise StatsError(f"invalid identifier: {name!r}")
    return f'"{name}"'


def _validate_where(where: str) -> None:
    banned = (";", "--", "/*", "attach", "pragma", "insert", "update", "delete", "drop", "create")
    low = where.lower()
    if any(b in low for b in banned):
        raise StatsError("'where' may only be a simple filter expression")


def _get_data(
    values: Optional[list[float]],
    catalog: Optional[Catalog],
    dataset: Optional[str],
    column: Optional[str],
    where: Optional[str],
) -> list[float]:
    if values is not None:
        return [float(v) for v in values]
    if dataset and column:
        if catalog is None:
            raise StatsError("dataset/column given but no data catalog is available")
        return _resolve_column(catalog, dataset, column, where)
    raise StatsError("provide either inline data or dataset+column")


def _interp_p(p: float, alpha: float = 0.05) -> str:
    if p < alpha:
        return f"p = {p:.4g} < {alpha}: the difference is statistically significant at the {int(alpha*100)}% level; this says nothing about effect size or cause."
    return f"p = {p:.4g} >= {alpha}: no statistically significant difference was found at the {int(alpha*100)}% level; absence of evidence is not evidence of absence."


def _describe(data: list[float]) -> dict[str, Any]:
    arr = np.asarray(data, dtype=float)
    n = arr.size
    if n == 0:
        raise StatsError("no data")
    q1, med, q3 = np.percentile(arr, [25, 50, 75])
    return {
        "n": int(n),
        "mean": float(np.mean(arr)),
        "sd": float(np.std(arr, ddof=1)) if n > 1 else 0.0,
        "median": float(med),
        "iqr": float(q3 - q1),
        "min": float(np.min(arr)),
        "max": float(np.max(arr)),
        "skew": float(sp.skew(arr)) if n > 2 else None,
    }


def run(
    test: str,
    *,
    data: Optional[list[float]] = None,
    data2: Optional[list[float]] = None,
    dataset: Optional[str] = None,
    column: Optional[str] = None,
    column2: Optional[str] = None,
    group_by: Optional[str] = None,
    where: Optional[str] = None,
    catalog: Optional[Catalog] = None,
    mu: float = 0.0,
    confidence: float = 0.95,
    successes: Optional[int] = None,
    trials: Optional[int] = None,
    p0: float = 0.5,
) -> dict[str, Any]:
    if test not in TESTS:
        raise StatsError(f"unknown test: {test}; choose one of {TESTS}")

    if test == "describe":
        d = _get_data(data, catalog, dataset, column, where)
        return {"test": "describe", **_describe(d)}

    if test == "ttest_1samp":
        d = _get_data(data, catalog, dataset, column, where)
        stat, p = sp.ttest_1samp(d, mu)
        return {
            "test": "One-sample t-test", "statistic": float(stat), "p_value": float(p),
            "n": len(d), "mean": float(np.mean(d)), "mu": mu,
            "interpretation": _interp_p(float(p)),
        }

    if test in ("ttest_ind", "mannwhitneyu"):
        if group_by and dataset and column:
            groups = _resolve_grouped(catalog, dataset, column, group_by, where)
            if len(groups) != 2:
                raise StatsError(f"group_by must select exactly 2 groups, found {len(groups)}: {sorted(groups)}")
            (name1, d1), (name2, d2) = sorted(groups.items())
        else:
            d1 = _get_data(data, catalog, dataset, column, where)
            d2 = _get_data(data2, catalog, dataset, column2, where)
            name1, name2 = "group1", "group2"
        if test == "ttest_ind":
            res = sp.ttest_ind(d1, d2, equal_var=False)
            pooled_sd = math.sqrt((np.var(d1, ddof=1) + np.var(d2, ddof=1)) / 2)
            cohens_d = (np.mean(d1) - np.mean(d2)) / pooled_sd if pooled_sd else 0.0
            return {
                "test": "Welch's two-sample t-test", "statistic": float(res.statistic),
                "p_value": float(res.pvalue), "df": float(res.df),
                "n1": len(d1), "n2": len(d2), "mean1": float(np.mean(d1)), "mean2": float(np.mean(d2)),
                "group1": name1, "group2": name2, "cohens_d": float(cohens_d),
                "interpretation": _interp_p(float(res.pvalue)),
            }
        res = sp.mannwhitneyu(d1, d2, alternative="two-sided")
        return {
            "test": "Mann-Whitney U", "statistic": float(res.statistic), "p_value": float(res.pvalue),
            "n1": len(d1), "n2": len(d2), "group1": name1, "group2": name2,
            "interpretation": _interp_p(float(res.pvalue)),
        }

    if test == "ttest_rel":
        d1 = _get_data(data, catalog, dataset, column, where)
        d2 = _get_data(data2, catalog, dataset, column2, where)
        if len(d1) != len(d2):
            raise StatsError("paired t-test needs equal-length samples")
        res = sp.ttest_rel(d1, d2)
        return {
            "test": "Paired t-test", "statistic": float(res.statistic), "p_value": float(res.pvalue),
            "n": len(d1), "mean_diff": float(np.mean(np.array(d1) - np.array(d2))),
            "interpretation": _interp_p(float(res.pvalue)),
        }

    if test == "wilcoxon":
        d1 = _get_data(data, catalog, dataset, column, where)
        d2 = _get_data(data2, catalog, dataset, column2, where)
        res = sp.wilcoxon(d1, d2)
        return {
            "test": "Wilcoxon signed-rank", "statistic": float(res.statistic), "p_value": float(res.pvalue),
            "n": len(d1), "interpretation": _interp_p(float(res.pvalue)),
        }

    if test == "chi2_contingency":
        if data is None:
            raise StatsError("chi2_contingency needs 'data' as a 2D contingency table, e.g. [[10,20],[15,25]]")
        table = np.asarray(data, dtype=float)
        chi2, p, dof, expected = sp.chi2_contingency(table)
        return {
            "test": "Chi-squared test of independence", "statistic": float(chi2), "p_value": float(p),
            "dof": int(dof), "expected": expected.tolist(), "interpretation": _interp_p(float(p)),
        }

    if test == "fisher_exact":
        if data is None:
            raise StatsError("fisher_exact needs 'data' as a 2x2 table, e.g. [[8,2],[1,9]]")
        table = np.asarray(data, dtype=float)
        odds_ratio, p = sp.fisher_exact(table)
        return {
            "test": "Fisher's exact test", "odds_ratio": float(odds_ratio), "p_value": float(p),
            "interpretation": _interp_p(float(p)),
        }

    if test in ("pearson", "spearman", "linregress"):
        d1 = _get_data(data, catalog, dataset, column, where)
        d2 = _get_data(data2, catalog, dataset, column2, where)
        if len(d1) != len(d2):
            raise StatsError("correlation/regression needs equal-length samples")
        if test == "pearson":
            r, p = sp.pearsonr(d1, d2)
            return {"test": "Pearson correlation", "r": float(r), "p_value": float(p), "n": len(d1),
                    "interpretation": _interp_p(float(p))}
        if test == "spearman":
            rho, p = sp.spearmanr(d1, d2)
            return {"test": "Spearman correlation", "rho": float(rho), "p_value": float(p), "n": len(d1),
                    "interpretation": _interp_p(float(p))}
        res = sp.linregress(d1, d2)
        return {
            "test": "Linear regression", "slope": float(res.slope), "intercept": float(res.intercept),
            "r_squared": float(res.rvalue ** 2), "p_value": float(res.pvalue), "stderr": float(res.stderr),
            "n": len(d1), "interpretation": _interp_p(float(res.pvalue)),
        }

    if test == "proportion_ci":
        if successes is None or trials is None:
            raise StatsError("proportion_ci needs successes and trials")
        lo, hi = _wilson_ci(successes, trials, confidence)
        return {
            "test": "Wilson score confidence interval", "proportion": successes / trials,
            "successes": successes, "trials": trials, "confidence": confidence, "ci_low": lo, "ci_high": hi,
        }

    if test == "normal_ci":
        d = _get_data(data, catalog, dataset, column, where)
        arr = np.asarray(d, dtype=float)
        mean = float(np.mean(arr))
        sem = sp.sem(arr)
        lo, hi = sp.t.interval(confidence, len(arr) - 1, loc=mean, scale=sem)
        return {
            "test": "Mean confidence interval (t-distribution)", "mean": mean, "n": len(arr),
            "confidence": confidence, "ci_low": float(lo), "ci_high": float(hi),
        }

    if test == "binom_test":
        if successes is None or trials is None:
            raise StatsError("binom_test needs successes and trials")
        res = sp.binomtest(successes, trials, p0)
        return {
            "test": "Binomial test", "p_value": float(res.pvalue), "successes": successes,
            "trials": trials, "p0": p0, "proportion": successes / trials,
            "interpretation": _interp_p(float(res.pvalue)),
        }

    raise StatsError(f"unhandled test: {test}")


def _wilson_ci(successes: int, trials: int, confidence: float) -> tuple[float, float]:
    if trials <= 0:
        raise StatsError("trials must be positive")
    z = sp.norm.ppf(1 - (1 - confidence) / 2)
    p = successes / trials
    denom = 1 + z ** 2 / trials
    centre = p + z ** 2 / (2 * trials)
    adj = z * math.sqrt(p * (1 - p) / trials + z ** 2 / (4 * trials ** 2))
    lo = (centre - adj) / denom
    hi = (centre + adj) / denom
    return float(max(0.0, lo)), float(min(1.0, hi))
