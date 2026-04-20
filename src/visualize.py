"""
visualize.py
------------
Phase 4: Six final plots for the write-up.

All figures go to reports/figures/*.png at 300 dpi. This script reads from:
  - event_windows, layoff_events, companies (SQL)
  - info/analysis_summary.json (headline hypothesis test)
  - info/timeline_ars.csv (daily ARs for plot 1)
  - info/rf_model.pkl + reports/tables/rf_feature_importance.csv (plot 5)

Run `python src/visualize.py` to regenerate all six, or `--only N` for one.
"""

import argparse
import json
import logging
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import text

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

load_dotenv()
from ingest_layoffs import get_engine  # noqa: E402

sns.set_theme(style="whitegrid", context="talk")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,  # Override handlers set by ingest_layoffs import
)
logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"
TABLES_DIR = REPORTS_DIR / "tables"
INFO_DIR = PROJECT_ROOT / "info"

HEADLINE_WS, HEADLINE_WE = -5, 5


def _save(fig, name):
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    path = FIGURES_DIR / name
    fig.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"  Saved: {path}")


# ----------------------------------------------------------------------------
# Plot 1: Average daily AR timeline, t-30 to t+30
# ----------------------------------------------------------------------------
def plot_avg_daily_ar(engine):
    path = INFO_DIR / "timeline_ars.csv"
    if not path.exists():
        logger.warning("Skipping plot 1: info/timeline_ars.csv not found")
        return
    df = pd.read_csv(path)
    grouped = df.groupby("offset")["ar"].agg(["mean", "std", "count"]).reset_index()
    grouped["se"] = grouped["std"] / np.sqrt(grouped["count"])
    grouped["ci_lo"] = grouped["mean"] - 1.96 * grouped["se"]
    grouped["ci_hi"] = grouped["mean"] + 1.96 * grouped["se"]

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(grouped["offset"], grouped["mean"] * 100, color="#2b6cb0", linewidth=2,
            label="Mean AR (%)")
    ax.fill_between(grouped["offset"], grouped["ci_lo"] * 100,
                    grouped["ci_hi"] * 100, color="#2b6cb0", alpha=0.2,
                    label="95% CI")
    ax.axvline(0, color="red", linestyle="--", alpha=0.7, label="Announcement (t=0)")
    ax.axhline(0, color="black", linestyle="-", linewidth=0.5)
    ax.set_xlabel("Trading days relative to announcement")
    ax.set_ylabel("Average abnormal return (%)")
    ax.set_title("Average daily abnormal return around layoff announcements")
    ax.legend(loc="best")
    _save(fig, "1_avg_daily_ar_timeline.png")


# ----------------------------------------------------------------------------
# Plot 2: CAR histogram for (-5, +5) window
# ----------------------------------------------------------------------------
def plot_car_histogram(engine):
    df = pd.read_sql(text("""
        SELECT cumulative_abnormal_return AS car
        FROM event_windows
        WHERE window_start_offset = :ws AND window_end_offset = :we
          AND cumulative_abnormal_return IS NOT NULL
    """), engine, params={"ws": HEADLINE_WS, "we": HEADLINE_WE})

    if df.empty:
        logger.warning("Skipping plot 2: no CARs found")
        return

    cars_pct = df["car"].astype(float) * 100

    # Annotate with headline test from summary
    summary_path = INFO_DIR / "analysis_summary.json"
    annotation = ""
    if summary_path.exists():
        s = json.loads(summary_path.read_text())
        annotation = (
            f"N = {s['n']}\n"
            f"mean CAR = {s['mean_car']*100:+.2f}%\n"
            f"t = {s['t_statistic']:+.2f}, p = {s['p_value']:.4f}"
        )

    fig, ax = plt.subplots(figsize=(12, 6))
    sns.histplot(cars_pct, kde=True, color="#4c78a8", bins=40, ax=ax)
    ax.axvline(0, color="red", linestyle="--", alpha=0.7, label="CAR = 0")
    ax.axvline(cars_pct.mean(), color="#2b6cb0", linewidth=2,
               label=f"Mean = {cars_pct.mean():+.2f}%")
    # Clip extreme outliers for readability
    lo, hi = np.percentile(cars_pct, [1, 99])
    ax.set_xlim(lo * 1.1, hi * 1.1)
    ax.set_xlabel("Cumulative Abnormal Return (%) in ±5 day window")
    ax.set_ylabel("Number of events")
    ax.set_title(f"Distribution of CAR around layoff announcements ({HEADLINE_WS:+d}, {HEADLINE_WE:+d})")
    if annotation:
        ax.text(0.02, 0.98, annotation, transform=ax.transAxes, fontsize=12,
                verticalalignment="top",
                bbox=dict(boxstyle="round", facecolor="white", alpha=0.9))
    ax.legend(loc="upper right")
    _save(fig, "2_car_histogram.png")


# ----------------------------------------------------------------------------
# Plot 3: Layoff size vs CAR
# ----------------------------------------------------------------------------
def plot_size_vs_car(engine):
    df = pd.read_sql(text("""
        SELECT le.employees_laid_off, le.percentage_laid_off,
               ew.cumulative_abnormal_return AS car
        FROM layoff_events le
        JOIN event_windows ew ON ew.event_id = le.event_id
        WHERE ew.window_start_offset = :ws AND ew.window_end_offset = :we
          AND ew.cumulative_abnormal_return IS NOT NULL
    """), engine, params={"ws": HEADLINE_WS, "we": HEADLINE_WE})

    if df.empty:
        logger.warning("Skipping plot 3: no joined events/CARs")
        return

    df["car_pct"] = df["car"].astype(float) * 100

    fig, axes = plt.subplots(1, 2, figsize=(16, 6))

    # Left: log(employees)
    left = df.dropna(subset=["employees_laid_off"])
    left = left[left["employees_laid_off"] > 0]
    if len(left) > 5:
        sns.regplot(x=np.log1p(left["employees_laid_off"]), y=left["car_pct"],
                    ax=axes[0], scatter_kws={"alpha": 0.5}, line_kws={"color": "red"})
        slope, intercept, r, p, _ = _linregress(
            np.log1p(left["employees_laid_off"]).values, left["car_pct"].values
        )
        axes[0].set_title(
            f"log(1 + employees laid off) vs CAR\n"
            f"slope={slope:+.3f}, R²={r**2:.3f}, p={p:.3f}, N={len(left)}"
        )
        axes[0].set_xlabel("log(1 + employees laid off)")
        axes[0].set_ylabel("CAR (%)")
        axes[0].axhline(0, color="black", linewidth=0.5)

    # Right: percentage (CSV stores fraction 0-1; convert to percent for display)
    right = df.dropna(subset=["percentage_laid_off"])
    if len(right) > 5:
        pct_pct = right["percentage_laid_off"].astype(float) * 100
        sns.regplot(x=pct_pct, y=right["car_pct"],
                    ax=axes[1], scatter_kws={"alpha": 0.5}, line_kws={"color": "red"})
        slope, intercept, r, p, _ = _linregress(
            pct_pct.values, right["car_pct"].values
        )
        axes[1].set_title(
            f"% of workforce laid off vs CAR\n"
            f"slope={slope:+.3f} %/%, R²={r**2:.3f}, p={p:.3f}, N={len(right)}"
        )
        axes[1].set_xlabel("Percentage of workforce laid off (%)")
        axes[1].set_ylabel("CAR (%)")
        axes[1].axhline(0, color="black", linewidth=0.5)

    fig.suptitle("Layoff size vs. stock-price reaction", fontsize=16, y=1.02)
    plt.tight_layout()
    _save(fig, "3_layoff_size_vs_car.png")


def _linregress(x, y):
    from scipy.stats import linregress
    return linregress(x, y)


# ----------------------------------------------------------------------------
# Plot 4: First-time vs repeat
# ----------------------------------------------------------------------------
def plot_first_vs_repeat(engine):
    df = pd.read_sql(text("""
        WITH ranked AS (
            SELECT le.event_id, le.company_id, le.announcement_date,
                   ROW_NUMBER() OVER (PARTITION BY le.company_id
                                      ORDER BY le.announcement_date) AS rn
            FROM layoff_events le
            JOIN companies c USING (company_id)
            WHERE c.ticker_symbol IS NOT NULL
        )
        SELECT r.rn, ew.cumulative_abnormal_return AS car
        FROM ranked r
        JOIN event_windows ew ON ew.event_id = r.event_id
        WHERE ew.window_start_offset = :ws AND ew.window_end_offset = :we
          AND ew.cumulative_abnormal_return IS NOT NULL
    """), engine, params={"ws": HEADLINE_WS, "we": HEADLINE_WE})

    if df.empty:
        logger.warning("Skipping plot 4: no data")
        return

    df["car_pct"] = df["car"].astype(float) * 100
    df["group"] = np.where(df["rn"] == 1, "First-time", "Repeat")

    first = df.loc[df["group"] == "First-time", "car_pct"].to_numpy()
    repeat = df.loc[df["group"] == "Repeat", "car_pct"].to_numpy()
    from scipy.stats import ttest_ind
    if len(first) > 2 and len(repeat) > 2:
        t_stat, p_val = ttest_ind(first, repeat, equal_var=False)
        annotation = (
            f"First-time: N={len(first)}, mean={first.mean():+.2f}%\n"
            f"Repeat:     N={len(repeat)}, mean={repeat.mean():+.2f}%\n"
            f"Welch's t={t_stat:+.2f}, p={p_val:.3f}"
        )
    else:
        annotation = "Insufficient data for t-test"

    fig, ax = plt.subplots(figsize=(10, 7))
    sns.boxplot(x="group", y="car_pct", data=df, ax=ax,
                order=["First-time", "Repeat"], width=0.5)
    sns.stripplot(x="group", y="car_pct", data=df, ax=ax,
                  order=["First-time", "Repeat"], alpha=0.35, color="black", size=3)
    ax.axhline(0, color="red", linestyle="--", alpha=0.7)
    ax.set_xlabel("")
    ax.set_ylabel("CAR (%) in ±5 day window")
    ax.set_title("First-time vs. repeat layoff announcements")
    ax.text(0.02, 0.98, annotation, transform=ax.transAxes, fontsize=11,
            verticalalignment="top",
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.9))
    # Clip to 1-99 percentile for readability
    lo, hi = np.percentile(df["car_pct"], [1, 99])
    ax.set_ylim(lo * 1.15, hi * 1.15)
    _save(fig, "4_first_vs_repeat.png")


# ----------------------------------------------------------------------------
# Plot 5: Random Forest feature importance
# ----------------------------------------------------------------------------
def plot_rf_importance(engine):
    csv_path = TABLES_DIR / "rf_feature_importance.csv"
    if not csv_path.exists():
        logger.warning("Skipping plot 5: rf_feature_importance.csv not found")
        return
    df = pd.read_csv(csv_path)
    top = df.head(15).iloc[::-1]  # top 15, reversed for horizontal bar

    fig, ax = plt.subplots(figsize=(12, 8))
    ax.barh(top["feature"], top["importance_mean"],
            xerr=top["importance_std"],
            color="#2b6cb0", alpha=0.85, capsize=4)
    ax.set_xlabel("Feature importance (Gini)")
    ax.set_title("Top 15 features — Random Forest (predicting positive CAR)")
    _save(fig, "5_rf_feature_importance.png")


# ----------------------------------------------------------------------------
# Plot 6: Monthly heatmap — event counts + mean CAR
# ----------------------------------------------------------------------------
def plot_monthly_heatmap(engine):
    df = pd.read_sql(text("""
        SELECT DATE_TRUNC('month', le.announcement_date)::date AS month,
               COUNT(*) AS n_events,
               AVG(ew.cumulative_abnormal_return) AS mean_car
        FROM layoff_events le
        JOIN companies c USING (company_id)
        LEFT JOIN event_windows ew
          ON ew.event_id = le.event_id
         AND ew.window_start_offset = :ws
         AND ew.window_end_offset = :we
        WHERE c.ticker_symbol IS NOT NULL
        GROUP BY 1
        ORDER BY 1
    """), engine, params={"ws": HEADLINE_WS, "we": HEADLINE_WE})

    if df.empty:
        logger.warning("Skipping plot 6: no monthly data")
        return

    df["month"] = pd.to_datetime(df["month"])
    df["year"] = df["month"].dt.year
    df["m"] = df["month"].dt.month
    df["mean_car_pct"] = df["mean_car"].astype(float) * 100

    pivot_n = df.pivot(index="year", columns="m", values="n_events").fillna(0).astype(int)
    pivot_car = df.pivot(index="year", columns="m", values="mean_car_pct")

    fig, axes = plt.subplots(2, 1, figsize=(14, 10))
    sns.heatmap(pivot_n, annot=True, fmt="d", cmap="Blues", ax=axes[0],
                cbar_kws={"label": "Events"})
    axes[0].set_title("Event volume: layoff announcements per month (matched companies only)")
    axes[0].set_xlabel("Month")
    axes[0].set_ylabel("Year")

    # Center diverging colormap at 0
    vmax = max(abs(np.nanmin(pivot_car.values)), abs(np.nanmax(pivot_car.values)))
    sns.heatmap(pivot_car, annot=True, fmt=".1f", cmap="RdBu_r", ax=axes[1],
                center=0, vmin=-vmax, vmax=vmax,
                cbar_kws={"label": "Mean CAR (%) in ±5 day window"})
    axes[1].set_title("Market reaction: mean CAR in ±5 day window")
    axes[1].set_xlabel("Month")
    axes[1].set_ylabel("Year")
    plt.tight_layout()
    _save(fig, "6_monthly_heatmap.png")


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
PLOTS = [
    ("1", plot_avg_daily_ar),
    ("2", plot_car_histogram),
    ("3", plot_size_vs_car),
    ("4", plot_first_vs_repeat),
    ("5", plot_rf_importance),
    ("6", plot_monthly_heatmap),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="Comma-separated plot numbers, e.g. '1,2'",
                    default=None)
    args = ap.parse_args()

    engine = get_engine()
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    selected = set(args.only.split(",")) if args.only else {n for n, _ in PLOTS}
    for n, fn in PLOTS:
        if n in selected:
            logger.info(f"Plot {n}: {fn.__name__}")
            try:
                fn(engine)
            except Exception as e:
                logger.error(f"  Plot {n} failed: {e}", exc_info=True)


if __name__ == "__main__":
    main()
