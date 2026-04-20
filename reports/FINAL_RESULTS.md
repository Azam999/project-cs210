# Final Results — Do Tech Layoffs Help Stock Prices?

**CS 210 · Rutgers · Spring 2026**
**Authors:** Azam Ahmed, Xuan Liao
**Run date:** 2026-04-20

---

## Verdict

**No. The data does not support the "Wall Street rewards layoffs" narrative — and mild evidence points the other direction.**

---

## The numbers

Pre-registered event window: **(−5, +5) trading days** around the announcement.
Methodology: market-adjusted abnormal returns, log returns, S&P 500 benchmark.

| Metric | Value |
|---|---|
| N (events with complete CAR) | **505** |
| Mean CAR | **−1.12%** |
| Median CAR | −0.05% |
| Std CAR | 14.3% |
| t-statistic (one-sample) | −1.75 |
| p-value (two-sided t-test) | 0.080 |
| 95% bootstrap CI | [−2.37%, +0.13%] |
| Standardized CAR Patell Z | **−2.37** |
| SCAR p-value | **0.018 — significant at α=0.05** |

All four windows are consistent in direction:

| Window | Mean CAR |
|---|---|
| (−30, +30) | −5.2% |
| **(−5, +5)** | **−1.12%** |
| (−1, +1) | −0.64% |
| (0, +3) | −0.99% |

---

## Answering the proposal's secondary questions

- **Does layoff size matter?** No. `log(employees)` slope ≈ −0.05% per log unit, R² ≈ 0.000, p = 0.91. Percentage-of-workforce slope likewise flat (p = 0.69).
- **First-time vs. repeat layoffs?** No significant difference (Welch t = −1.10, p = 0.27). Point estimates: first-time −1.90%, repeat −0.41%.
- **Market regime?** `market_regime_30d` is the top Random Forest feature by Gini importance — the prevailing 30-day S&P trend matters more than any layoff-specific variable.
- **Predictability?** Random Forest 5-fold ROC-AUC = **0.46** — features can't reliably predict the sign of the reaction.

---

## Interpretation

Two competing narratives, tested:

1. **"Wall Street rewards layoffs"** — would predict mean CAR > 0 with p < 0.05.
   **Rejected.** Point estimate is negative with borderline-to-significant evidence against zero.
2. **"Wall Street punishes layoffs"** — would predict a large negative effect.
   **Weakly supported.** The SCAR Z-test is significant (p = 0.018), but the effect is small (≈ −1%) and layoff-specific features don't explain it.

The defensible reading: **layoff announcements carry little new information. The market mostly shrugs, with a slight negative tilt.** By the time a layoff hits the news, the underlying business weakness is often already priced in; the layoff itself is confirmatory, not informative.

---

## What we built

- **Normalized 3NF PostgreSQL** schema: `companies`, `layoff_events`, `daily_prices`, `market_index`, `event_windows`
- **Fully idempotent ETL pipeline**: every stage re-runnable via `ON CONFLICT DO NOTHING` / `ON CONFLICT DO UPDATE`
- **Two data sources**: layoffs.fyi CSV + Yahoo Finance via `yfinance`
- **Layered entity resolution**: manual override map → `yf.Search` API → heuristic validation → unresolved
- **Event-study analysis**: market-adjusted abnormal returns, Cumulative Abnormal Return (CAR), Standardized CAR (SCAR) via `(−250, −31)` estimation window
- **Statistical tests**: one-sample t-test on CAR, Patell-style Z on SCAR, 1000-sample bootstrap CI
- **OLS regression** with HC3 robust standard errors
- **Random Forest classifier** (500 trees, 5-fold CV, class-balanced)

### Pipeline volume

| Stage | Output |
|---|---|
| Phase 1: Ingest | 2,873 companies · 4,335 events |
| Phase 2a: Ticker matching | 196 matched public companies |
| Phase 2b: Price fetch | 281,418 daily price rows · 1,666 S&P days |
| Phase 3: Event study | 530 events × 4 windows = 2,120 event_windows rows |
| Phase 4: Visualizations | 6 figures + 4 tables |

---

## Caveats (from the proposal, still apply)

- **Selection bias.** Only 196 of 2,873 companies (≈7%) are public with tradable tickers. The sample skews toward larger, more-established tech firms. The 2,677 unresolved are overwhelmingly VC-funded startups that would've been excluded regardless. However, the matched companies still capture ~56% of the total layoff-employee impact.
- **Single-factor market model.** We subtract S&P 500 returns rather than fitting a full Fama-French multi-factor model. For short windows the two approaches converge (MacKinlay 1997), but a multi-factor model could isolate sector effects more cleanly.
- **Announcement vs. leak date.** Some layoffs leak to the press days before the official announcement, which could push the "true" event earlier than what the CSV records — biasing toward weaker measured effects. The (−5, 0) pre-event window in our results is flat, which is consistent with either "no leak" or "leaks happened but >5 trading days prior."

---

## One-sentence summary for the oral exam

> We built an idempotent 3NF PostgreSQL pipeline — **2,873 companies, 4,335 events, 281K prices, 1,666 S&P days** — and ran a market-adjusted event study on 505 public-company layoff announcements; in the pre-registered (−5, +5) window, mean CAR = **−1.12%** (t-test p = 0.080; SCAR-based Patell Z p = **0.018**). The "Wall Street rewards layoffs" narrative is **not supported**; if anything, tech stocks slightly underperform the market after layoff announcements, though the effect is small and layoff-specific features don't explain it. **The market mostly shrugs.**

---

## Outputs

- **Figures**: `reports/figures/` — six 300 dpi PNGs
- **Tables**: `reports/tables/` — regression coefficients, RF feature importance, RF metrics
- **Analysis summary JSON**: `info/analysis_summary.json` (regenerable)
- **Per-event CARs**: `info/per_event_cars.csv` (regenerable)
- **Fitted Random Forest**: `info/rf_model.pkl` (regenerable)

## Reproducing

```bash
# From project root, with venv active
psql layoffs_analysis -f sql/schema.sql
psql layoffs_analysis -f sql/add_ticker_metadata.sql
psql layoffs_analysis -f sql/add_event_window_uniqueness.sql
python src/ingest_layoffs.py
python src/match_tickers.py
python src/fetch_prices.py       # ~5-10 min (subject to Yahoo rate limits)
python src/analyze_events.py
python src/visualize.py
```

Every stage is idempotent.
