"""
analyze_events.py
-----------------
Phase 3: Event study, hypothesis test, OLS regression, Random Forest.

For every layoff event for which we have a matched ticker and sufficient
price history, we compute abnormal returns, cumulative abnormal returns
(CAR), and standardized CARs (SCAR) across four analysis windows. Results
are written back to the event_windows table.

Aggregate outputs (hypothesis test, regression, Random Forest) are written
to reports/ and info/ for the visualizer and final write-up.

Methodology:
  - Returns: log returns. R(t) = ln(P_t / P_{t-1}).
  - Abnormal return: market-adjusted. AR(t) = R_stock(t) - R_mkt(t).
  - Event day t=0: first trading day >= announcement_date (^GSPC calendar).
  - Estimation window for SCAR sigma: (-250, -31) before event.
  - Headline window (pre-registered): (-5, +5).
"""

import argparse
import json
import logging
import os
import pickle
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from scipy import stats
from sqlalchemy import text

load_dotenv()
from ingest_layoffs import get_engine  # noqa: E402

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)


# ----------------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("analyze_events.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
    force=True,  # Override handlers set by ingest_layoffs import
)
logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"
TABLES_DIR = REPORTS_DIR / "tables"
FIGURES_DIR = REPORTS_DIR / "figures"
INFO_DIR = PROJECT_ROOT / "info"


# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------
DEFAULT_WINDOWS = [(-30, 30), (-5, 5), (-1, 1), (0, 3)]
HEADLINE_WINDOW = (-5, 5)


def _window_key(ws: int, we: int) -> str:
    """Safe column-name key: 'm' for minus, 'p' for plus. Avoids dashes that
    would break patsy/statsmodels formulas."""
    def _part(n):
        return f"m{abs(n)}" if n < 0 else f"p{n}"
    return f"{_part(ws)}_{_part(we)}"
ESTIMATION_START = -250
ESTIMATION_END = -31
MIN_ESTIMATION_DAYS = 150
MIN_WINDOW_COVERAGE = 0.90


# ----------------------------------------------------------------------------
# Migration guard
# ----------------------------------------------------------------------------
def check_migrations(engine):
    """Abort early if the event_windows uniqueness migration hasn't been applied."""
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'uq_event_window'
        """)).first()
    if row is None:
        logger.error(
            "Migration missing: sql/add_event_window_uniqueness.sql has not "
            "been applied. Run it first:\n"
            "  psql layoffs_analysis -f sql/add_event_window_uniqueness.sql"
        )
        sys.exit(2)


# ----------------------------------------------------------------------------
# Data loading
# ----------------------------------------------------------------------------
def load_all_data(engine):
    """Pull everything we need into pandas. Dataset is small (<100 MB)."""
    with engine.connect() as conn:
        events = pd.read_sql(text("""
            SELECT le.event_id, le.company_id, le.announcement_date,
                   le.employees_laid_off, le.percentage_laid_off,
                   le.funds_raised_usd, le.stage,
                   c.company_name, c.ticker_symbol, c.industry
            FROM layoff_events le
            JOIN companies c USING (company_id)
            WHERE c.ticker_symbol IS NOT NULL
            ORDER BY le.announcement_date
        """), conn)
        prices = pd.read_sql(text("""
            SELECT company_id, trade_date, adj_close
            FROM daily_prices
            ORDER BY company_id, trade_date
        """), conn)
        market = pd.read_sql(text("""
            SELECT trade_date, adj_close
            FROM market_index
            ORDER BY trade_date
        """), conn)

    events["announcement_date"] = pd.to_datetime(events["announcement_date"])
    prices["trade_date"] = pd.to_datetime(prices["trade_date"])
    market["trade_date"] = pd.to_datetime(market["trade_date"])
    prices["adj_close"] = prices["adj_close"].astype(float)
    market["adj_close"] = market["adj_close"].astype(float)

    logger.info(
        f"Loaded: {len(events)} events, {len(prices)} price rows, "
        f"{len(market)} market-index rows"
    )
    return events, prices, market


# ----------------------------------------------------------------------------
# Compute log returns
# ----------------------------------------------------------------------------
def compute_returns(prices: pd.DataFrame, market: pd.DataFrame):
    """
    Build:
      - per-company returns dict: company_id -> DataFrame indexed by trade_date
        with columns [adj_close, r_stock]
      - market returns: DataFrame indexed by trade_date with [adj_close, r_mkt]
    """
    market = market.sort_values("trade_date").copy()
    market["r_mkt"] = np.log(market["adj_close"] / market["adj_close"].shift(1))
    market = market.set_index("trade_date")

    per_company = {}
    for cid, grp in prices.groupby("company_id"):
        g = grp.sort_values("trade_date").copy()
        g["r_stock"] = np.log(g["adj_close"] / g["adj_close"].shift(1))
        g = g.set_index("trade_date")
        per_company[int(cid)] = g[["adj_close", "r_stock"]]
    return per_company, market


# ----------------------------------------------------------------------------
# Core event-study math
# ----------------------------------------------------------------------------
def align_to_trading_days(announcement_date, trading_days: pd.DatetimeIndex):
    """Return the integer index t0 of the first trading day >= announcement."""
    t0 = trading_days.searchsorted(announcement_date, side="left")
    if t0 >= len(trading_days):
        return None
    return int(t0)


def compute_window_stats(
    company_returns: pd.DataFrame,
    market_returns: pd.DataFrame,
    trading_days: pd.DatetimeIndex,
    t0: int,
    win_start: int,
    win_end: int,
):
    """Return (car, avg_ar, ar_series) or None if coverage insufficient."""
    # Window runs from t0+win_start through t0+win_end inclusive
    lo = t0 + win_start
    hi = t0 + win_end
    if lo < 1 or hi >= len(trading_days):
        return None

    dates = trading_days[lo : hi + 1]
    expected = len(dates)

    # Pull stock + market returns; both indexed by trade_date
    merged = market_returns.reindex(dates)[["r_mkt"]].join(
        company_returns.reindex(dates)[["r_stock"]]
    )
    valid = merged.dropna().copy()
    if len(valid) < expected * MIN_WINDOW_COVERAGE:
        return None

    valid["ar"] = valid["r_stock"] - valid["r_mkt"]
    car = float(valid["ar"].sum())
    avg_ar = float(valid["ar"].mean())
    return car, avg_ar, valid["ar"]


def compute_scar(
    company_returns: pd.DataFrame,
    market_returns: pd.DataFrame,
    trading_days: pd.DatetimeIndex,
    t0: int,
    win_start: int,
    win_end: int,
    car: float,
):
    """
    SCAR = CAR / (sigma_ar * sqrt(L)) where sigma_ar is estimated on the
    (-250, -31) pre-event window. Returns None if estimation window has
    insufficient observations.
    """
    est_lo = t0 + ESTIMATION_START
    est_hi = t0 + ESTIMATION_END
    if est_lo < 1 or est_hi >= len(trading_days):
        return None

    est_dates = trading_days[est_lo : est_hi + 1]
    merged = market_returns.reindex(est_dates)[["r_mkt"]].join(
        company_returns.reindex(est_dates)[["r_stock"]]
    )
    valid = merged.dropna()
    if len(valid) < MIN_ESTIMATION_DAYS:
        return None

    valid_ar = valid["r_stock"] - valid["r_mkt"]
    sigma = float(valid_ar.std(ddof=1))
    if sigma <= 0:
        return None

    length = win_end - win_start + 1
    return float(car / (sigma * np.sqrt(length)))


# ----------------------------------------------------------------------------
# DB write
# ----------------------------------------------------------------------------
_INSERT_WINDOW_SQL = text("""
    INSERT INTO event_windows
        (event_id, window_start_offset, window_end_offset,
         cumulative_abnormal_return, avg_abnormal_return, t_statistic)
    VALUES
        (:event_id, :win_start, :win_end, :car, :avg_ar, :scar)
    ON CONFLICT (event_id, window_start_offset, window_end_offset) DO NOTHING
""")


# ----------------------------------------------------------------------------
# Compute & store per-event windows; also collect timeline ARs for viz
# ----------------------------------------------------------------------------
def compute_and_store_events(engine, events, per_company, market_returns, windows):
    trading_days = pd.DatetimeIndex(market_returns.index)
    timeline_rows = []   # (event_id, offset, ar) for the (-30, +30) plot
    per_event_results = []  # list of dicts keyed by window string
    stats_counts = {"processed": 0, "skipped_no_prices": 0, "skipped_bounds": 0}

    for _, ev in events.iterrows():
        event_id = int(ev["event_id"])
        cid = int(ev["company_id"])
        if cid not in per_company:
            stats_counts["skipped_no_prices"] += 1
            continue

        t0 = align_to_trading_days(ev["announcement_date"], trading_days)
        if t0 is None:
            stats_counts["skipped_bounds"] += 1
            continue

        cret = per_company[cid]
        stats_counts["processed"] += 1

        row_result = {"event_id": event_id}
        with engine.begin() as conn:
            for (ws, we) in windows:
                res = compute_window_stats(cret, market_returns, trading_days, t0, ws, we)
                if res is None:
                    car, avg_ar, ar_series = None, None, None
                else:
                    car, avg_ar, ar_series = res
                scar = None
                if car is not None:
                    scar = compute_scar(
                        cret, market_returns, trading_days, t0, ws, we, car
                    )

                conn.execute(_INSERT_WINDOW_SQL, {
                    "event_id": event_id,
                    "win_start": ws, "win_end": we,
                    "car": car, "avg_ar": avg_ar, "scar": scar,
                })

                key = _window_key(ws, we)
                row_result[f"car_{key}"] = car
                row_result[f"scar_{key}"] = scar

                # Collect per-day ARs for the big (-30, +30) window so we
                # can draw the average-AR timeline plot in Phase 4.
                if (ws, we) == (-30, 30) and ar_series is not None:
                    for d, ar in ar_series.items():
                        offset = int(trading_days.get_loc(d)) - t0
                        timeline_rows.append({
                            "event_id": event_id,
                            "offset": offset,
                            "ar": float(ar),
                        })

        per_event_results.append(row_result)

    logger.info(
        f"Events processed: {stats_counts['processed']}, "
        f"skipped (no prices): {stats_counts['skipped_no_prices']}, "
        f"skipped (bounds): {stats_counts['skipped_bounds']}"
    )

    per_event_df = pd.DataFrame(per_event_results)
    timeline_df = pd.DataFrame(timeline_rows)
    return per_event_df, timeline_df


# ----------------------------------------------------------------------------
# Feature engineering for regression + RF
# ----------------------------------------------------------------------------
def engineer_features(events: pd.DataFrame, per_event_df: pd.DataFrame,
                      market_returns: pd.DataFrame):
    df = events.merge(per_event_df, on="event_id", how="left")

    # Repeat-layoff features
    df = df.sort_values(["company_id", "announcement_date"]).copy()
    df["event_rank"] = df.groupby("company_id").cumcount() + 1
    df["is_repeat"] = (df["event_rank"] > 1).astype(int)
    df["prior_date"] = df.groupby("company_id")["announcement_date"].shift(1)
    df["days_since_prior_layoff"] = (
        (df["announcement_date"] - df["prior_date"]).dt.days
    ).fillna(9999).astype(int)
    df["is_first"] = (df["event_rank"] == 1).astype(int)

    # Size features
    df["log_employees_laid_off"] = np.log1p(df["employees_laid_off"].fillna(
        df["employees_laid_off"].median()
    ))
    df["pct_laid_off"] = df["percentage_laid_off"].astype(float)
    df["has_pct"] = df["percentage_laid_off"].notna().astype(int)
    df["pct_laid_off_filled"] = df["pct_laid_off"].fillna(df["pct_laid_off"].median())

    df["log_funds_raised"] = np.log1p(df["funds_raised_usd"].fillna(0.0).astype(float))
    df["has_funds"] = df["funds_raised_usd"].notna().astype(int)

    # Market regime: 30-day log return on ^GSPC ending the day before event
    mkt = market_returns.sort_index().copy()
    mkt["r_mkt_30d"] = mkt["r_mkt"].rolling(30, min_periods=20).sum()
    trading_days = pd.DatetimeIndex(mkt.index)
    def _regime(date):
        idx = trading_days.searchsorted(pd.Timestamp(date), side="left") - 1
        if idx < 0 or idx >= len(trading_days):
            return np.nan
        return mkt["r_mkt_30d"].iloc[idx]
    df["market_regime_30d"] = df["announcement_date"].apply(_regime).fillna(0.0)

    # Industry collapsing: top 15, rest -> Other
    top_industries = df["industry"].value_counts().head(15).index.tolist()
    df["industry_top15"] = np.where(
        df["industry"].isin(top_industries), df["industry"], "Other"
    )
    df["industry_top15"] = df["industry_top15"].fillna("Other")

    # Stage: keep raw; null -> "Unknown"
    df["stage_clean"] = df["stage"].fillna("Unknown")

    # Year control
    df["event_year"] = df["announcement_date"].dt.year.astype(int)

    return df


# ----------------------------------------------------------------------------
# Aggregate hypothesis test
# ----------------------------------------------------------------------------
def run_hypothesis_test(per_event_df: pd.DataFrame) -> dict:
    ws, we = HEADLINE_WINDOW
    key = _window_key(ws, we)
    col = f"car_{key}"
    cars = per_event_df[col].dropna().to_numpy()
    n = len(cars)
    if n < 2:
        return {"n": n, "note": "insufficient observations"}

    t_stat, p_value = stats.ttest_1samp(cars, 0.0)
    rng = np.random.default_rng(42)
    boot = np.array([
        rng.choice(cars, size=n, replace=True).mean() for _ in range(1000)
    ])
    ci_lo, ci_hi = np.percentile(boot, [2.5, 97.5])

    # SCAR-based test (Patell Z proxy): mean(SCAR) * sqrt(N) ~ N(0,1)
    scar_col = f"scar_{key}"
    scars = per_event_df[scar_col].dropna().to_numpy()
    scar_z = float(np.mean(scars) * np.sqrt(len(scars))) if len(scars) > 0 else None
    scar_p = float(2 * (1 - stats.norm.cdf(abs(scar_z)))) if scar_z is not None else None

    return {
        "window": f"({ws},{we})",
        "n": int(n),
        "mean_car": float(cars.mean()),
        "median_car": float(np.median(cars)),
        "std_car": float(cars.std(ddof=1)),
        "t_statistic": float(t_stat),
        "p_value": float(p_value),
        "bootstrap_ci_95": [float(ci_lo), float(ci_hi)],
        "scar_n": int(len(scars)),
        "scar_mean": float(scars.mean()) if len(scars) > 0 else None,
        "scar_z": scar_z,
        "scar_p_value": scar_p,
    }


# ----------------------------------------------------------------------------
# OLS regression
# ----------------------------------------------------------------------------
def run_regression(df: pd.DataFrame):
    import statsmodels.api as sm
    import statsmodels.formula.api as smf

    ws, we = HEADLINE_WINDOW
    y_col = f"car_{_window_key(ws, we)}"
    sub = df.dropna(subset=[y_col]).copy()
    if len(sub) < 30:
        logger.warning(f"Regression skipped: only {len(sub)} obs with {y_col}")
        return None, None

    formula = (
        f"{y_col} ~ log_employees_laid_off + pct_laid_off_filled + has_pct "
        "+ is_repeat + days_since_prior_layoff + market_regime_30d "
        "+ log_funds_raised + has_funds "
        "+ C(industry_top15) + C(stage_clean)"
    )
    model = smf.ols(formula=formula, data=sub).fit(cov_type="HC3")

    # Coefficients table
    coef_df = pd.DataFrame({
        "coef": model.params,
        "std_err_hc3": model.bse,
        "t": model.tvalues,
        "p_value": model.pvalues,
        "ci_lo": model.conf_int()[0],
        "ci_hi": model.conf_int()[1],
    })
    return model, coef_df


# ----------------------------------------------------------------------------
# Random Forest
# ----------------------------------------------------------------------------
def run_random_forest(df: pd.DataFrame):
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import cross_val_score
    from sklearn.preprocessing import OneHotEncoder
    from sklearn.compose import ColumnTransformer
    from sklearn.pipeline import Pipeline

    ws, we = HEADLINE_WINDOW
    y_col = f"car_{_window_key(ws, we)}"
    sub = df.dropna(subset=[y_col]).copy()
    sub["target"] = (sub[y_col] > 0).astype(int)
    if len(sub) < 30 or sub["target"].nunique() < 2:
        logger.warning(f"RF skipped: {len(sub)} obs, {sub['target'].nunique()} classes")
        return None, None, None

    numeric_features = [
        "log_employees_laid_off", "pct_laid_off_filled", "has_pct",
        "is_repeat", "days_since_prior_layoff", "market_regime_30d",
        "log_funds_raised", "has_funds", "event_year",
    ]
    categorical_features = ["industry_top15", "stage_clean"]

    preprocessor = ColumnTransformer(
        transformers=[
            ("num", "passthrough", numeric_features),
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False),
             categorical_features),
        ]
    )
    clf = RandomForestClassifier(
        n_estimators=500,
        random_state=42,
        class_weight="balanced",
        n_jobs=-1,
    )
    pipe = Pipeline([("prep", preprocessor), ("rf", clf)])

    X = sub[numeric_features + categorical_features]
    y = sub["target"]

    acc_scores = cross_val_score(pipe, X, y, scoring="accuracy", cv=5, n_jobs=-1)
    auc_scores = cross_val_score(pipe, X, y, scoring="roc_auc", cv=5, n_jobs=-1)

    # Fit on full data for feature importances
    pipe.fit(X, y)
    rf = pipe.named_steps["rf"]
    ohe = pipe.named_steps["prep"].named_transformers_["cat"]
    feature_names = (
        numeric_features
        + list(ohe.get_feature_names_out(categorical_features))
    )
    importances = pd.DataFrame({
        "feature": feature_names,
        "importance_mean": rf.feature_importances_,
        "importance_std": np.std(
            [tree.feature_importances_ for tree in rf.estimators_], axis=0
        ),
    }).sort_values("importance_mean", ascending=False).reset_index(drop=True)

    metrics = {
        "n_obs": int(len(sub)),
        "pos_rate": float(y.mean()),
        "cv_accuracy_mean": float(acc_scores.mean()),
        "cv_accuracy_std": float(acc_scores.std()),
        "cv_roc_auc_mean": float(auc_scores.mean()),
        "cv_roc_auc_std": float(auc_scores.std()),
    }
    return pipe, importances, metrics


# ----------------------------------------------------------------------------
# Output writers
# ----------------------------------------------------------------------------
def ensure_dirs():
    for p in (REPORTS_DIR, TABLES_DIR, FIGURES_DIR, INFO_DIR):
        p.mkdir(parents=True, exist_ok=True)


def write_outputs(summary, coef_df, ols_model, rf_pipe, rf_imp, rf_metrics,
                  per_event_df, timeline_df):
    ensure_dirs()

    # Summary JSON
    with open(INFO_DIR / "analysis_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)

    # Regression outputs
    if coef_df is not None and ols_model is not None:
        coef_df.to_csv(TABLES_DIR / "regression_coefficients.csv", index=True)
        with open(TABLES_DIR / "regression_full.txt", "w") as f:
            f.write(str(ols_model.summary()))

    # RF outputs
    if rf_pipe is not None:
        with open(INFO_DIR / "rf_model.pkl", "wb") as f:
            pickle.dump(rf_pipe, f)
    if rf_imp is not None:
        rf_imp.to_csv(TABLES_DIR / "rf_feature_importance.csv", index=False)
    if rf_metrics is not None:
        with open(TABLES_DIR / "rf_metrics.txt", "w") as f:
            for k, v in rf_metrics.items():
                f.write(f"{k}: {v}\n")

    # Per-event CAR table (useful for the viz layer without a DB roundtrip)
    per_event_df.to_csv(INFO_DIR / "per_event_cars.csv", index=False)
    # Daily-AR timeline (for plot 1)
    timeline_df.to_csv(INFO_DIR / "timeline_ars.csv", index=False)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recompute", action="store_true",
                    help="Delete existing event_windows rows before recomputing")
    ap.add_argument("--skip-rf", action="store_true",
                    help="Skip Random Forest classifier")
    ap.add_argument("--windows", default=None,
                    help='Windows like "-30,+30;-5,+5;-1,+1;0,+3"')
    args = ap.parse_args()

    windows = DEFAULT_WINDOWS
    if args.windows:
        windows = []
        for piece in args.windows.split(";"):
            s, e = piece.split(",")
            windows.append((int(s), int(e)))
    if HEADLINE_WINDOW not in windows:
        windows.append(HEADLINE_WINDOW)

    logger.info("=" * 60)
    logger.info(f"Event study started at {datetime.now().isoformat()}")
    logger.info(f"Windows: {windows}")
    logger.info("=" * 60)

    engine = get_engine()
    check_migrations(engine)

    if args.recompute:
        with engine.begin() as conn:
            n = conn.execute(text("DELETE FROM event_windows")).rowcount
        logger.info(f"--recompute: deleted {n} existing event_windows rows")

    events, prices, market = load_all_data(engine)
    per_company, market_returns = compute_returns(prices, market)

    per_event_df, timeline_df = compute_and_store_events(
        engine, events, per_company, market_returns, windows
    )

    # Aggregate test on headline window
    summary = run_hypothesis_test(per_event_df)
    logger.info("-" * 60)
    logger.info(f"Hypothesis test on window {HEADLINE_WINDOW}:")
    for k, v in summary.items():
        logger.info(f"  {k}: {v}")

    # Feature engineering for regression + RF
    features_df = engineer_features(events, per_event_df, market_returns)

    ols_model, coef_df = run_regression(features_df)
    if ols_model is not None:
        logger.info("-" * 60)
        logger.info(f"OLS regression: N={ols_model.nobs}, R²={ols_model.rsquared:.4f}")

    rf_pipe, rf_imp, rf_metrics = (None, None, None)
    if not args.skip_rf:
        rf_pipe, rf_imp, rf_metrics = run_random_forest(features_df)
        if rf_metrics is not None:
            logger.info("-" * 60)
            logger.info(
                f"Random Forest: 5-fold accuracy={rf_metrics['cv_accuracy_mean']:.3f}, "
                f"ROC-AUC={rf_metrics['cv_roc_auc_mean']:.3f}"
            )

    write_outputs(summary, coef_df, ols_model, rf_pipe, rf_imp, rf_metrics,
                  per_event_df, timeline_df)

    # Row-count check
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT window_start_offset, window_end_offset, COUNT(*)
            FROM event_windows
            GROUP BY 1, 2 ORDER BY 1, 2
        """)).fetchall()
    logger.info("-" * 60)
    logger.info("event_windows row counts:")
    for r in rows:
        logger.info(f"  ({r[0]}, {r[1]}): {r[2]}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
