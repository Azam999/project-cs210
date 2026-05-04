"""
Build the CS 210 final technical report PDF.
Outputs to reports/Final_Report.pdf
"""
from pathlib import Path
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image,
    Table, TableStyle, KeepTogether, Preformatted,
)

ROOT = Path(__file__).resolve().parent
FIG = ROOT / "reports" / "figures"
OUT = ROOT / "reports" / "Final_Report.pdf"

# ---------- styles ----------
styles = getSampleStyleSheet()
title = ParagraphStyle(
    "title", parent=styles["Title"], fontName="Times-Bold",
    fontSize=18, leading=22, spaceAfter=6, alignment=TA_CENTER,
)
subtitle = ParagraphStyle(
    "subtitle", parent=styles["Normal"], fontName="Times-Italic",
    fontSize=11, leading=14, alignment=TA_CENTER, spaceAfter=4,
)
authorline = ParagraphStyle(
    "authorline", parent=styles["Normal"], fontName="Times-Roman",
    fontSize=11, leading=14, alignment=TA_CENTER, spaceAfter=6,
)
linkline = ParagraphStyle(
    "linkline", parent=styles["Normal"], fontName="Times-Italic",
    fontSize=10, leading=12, alignment=TA_CENTER, spaceAfter=18,
    textColor=colors.HexColor("#1a4f8b"),
)
h1 = ParagraphStyle(
    "h1", parent=styles["Heading1"], fontName="Times-Bold",
    fontSize=13, leading=16, spaceBefore=10, spaceAfter=6, textColor=colors.HexColor("#1a1a1a"),
)
h2 = ParagraphStyle(
    "h2", parent=styles["Heading2"], fontName="Times-Bold",
    fontSize=11, leading=14, spaceBefore=8, spaceAfter=3,
)
body = ParagraphStyle(
    "body", parent=styles["BodyText"], fontName="Times-Roman",
    fontSize=10.5, leading=14, alignment=TA_JUSTIFY, spaceAfter=6,
    firstLineIndent=0,
)
bullet = ParagraphStyle(
    "bullet", parent=body, leftIndent=14, bulletIndent=2,
    spaceAfter=2,
)
caption = ParagraphStyle(
    "caption", parent=styles["Normal"], fontName="Times-Italic",
    fontSize=9.5, leading=12, alignment=TA_CENTER, spaceBefore=2, spaceAfter=10,
)
mono = ParagraphStyle(
    "mono", parent=styles["Code"], fontName="Courier",
    fontSize=8.5, leading=11, leftIndent=10, spaceAfter=6,
)
codestyle = ParagraphStyle(
    "code", parent=styles["Code"], fontName="Courier",
    fontSize=8.2, leading=10.5, leftIndent=8, rightIndent=8,
    spaceBefore=2, spaceAfter=2,
    backColor=colors.HexColor("#f4f4f4"),
    borderColor=colors.HexColor("#cccccc"),
    borderWidth=0.5, borderPadding=5,
)
codecaption = ParagraphStyle(
    "codecaption", parent=styles["Normal"], fontName="Times-Italic",
    fontSize=9, leading=11, alignment=TA_CENTER, spaceAfter=10, spaceBefore=1,
    textColor=colors.HexColor("#333333"),
)

def P(text, style=body):
    return Paragraph(text, style)

def B(items):
    return [Paragraph(f"&bull;&nbsp; {t}", bullet) for t in items]

def fig(name, cap, w=5.6):
    img = Image(str(FIG / name), width=w * inch, height=w * inch * 0.62)
    img.hAlign = "CENTER"
    return KeepTogether([img, P(cap, caption)])

def code(text, cap):
    block = Preformatted(text, codestyle)
    return KeepTogether([block, P(cap, codecaption)])

# ---------- table builder ----------
def make_table(data, col_widths=None, header=True):
    t = Table(data, colWidths=col_widths, hAlign="CENTER")
    style = [
        ("FONT", (0, 0), (-1, -1), "Times-Roman", 9.5),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")))
        style.append(("FONT", (0, 0), (-1, 0), "Times-Bold", 9.5))
    t.setStyle(TableStyle(style))
    return t

# ---------- document ----------
story = []

# Title block
story.append(P("Do Tech Layoffs Help Stock Prices?", title))
story.append(P("An Event-Study Analysis on 4,300+ Layoff Announcements", subtitle))
story.append(P("Azam Ahmed, Xuan Liao &nbsp;&middot;&nbsp; CS 210: Data Management for Data Science &nbsp;&middot;&nbsp; Spring 2026", authorline))
story.append(P("https://github.com/Azam999/project-cs210 &nbsp;|&nbsp; Demo Video Link", linkline))

# ---------- Abstract ----------
story.append(P("Abstract", h1))
story.append(P(
    "We built an end-to-end data pipeline to test a popular financial claim, that public-company stock "
    "prices rise after layoff announcements because Wall Street &ldquo;rewards&rdquo; cost-cutting. Using a normalized "
    "PostgreSQL database, we ingested 4,335 layoff events covering 2,873 companies from layoffs.fyi, "
    "matched 196 publicly-traded companies to their tickers, and pulled 281,418 daily price rows from "
    "Yahoo Finance. We applied a market-adjusted event study, computing Cumulative Abnormal Returns "
    "(CAR) and Standardized CARs (SCAR) for 505 events in our pre-registered (&minus;5, +5) window. The "
    "headline t-test on mean CAR is borderline (mean = &minus;1.12%, t = &minus;1.75, p = 0.080), but the "
    "Patell-Z on SCAR is significant in the negative direction (Z = &minus;2.37, p = 0.018). An OLS "
    "regression and a 5-fold cross-validated Random Forest classifier (ROC-AUC = 0.46) confirm that "
    "layoff-specific features (size, percentage, repeat-vs-first) explain almost none of the variance in "
    "stock reaction. We conclude that the &ldquo;reward&rdquo; narrative is not supported by the data. If "
    "anything, the market tilts mildly negative, but the dominant signal is that announcements carry "
    "little new information.",
    body))

# ---------- 1. Project Definition ----------
story.append(P("1. Project Definition", h1))

story.append(P("1.1 Problem Statement", h2))
story.append(P(
    "Between 2022 and 2026, the tech sector cycled through one of the largest sustained waves of layoffs "
    "in its history. Meta, Amazon, Google, Microsoft, and hundreds of smaller companies cut a combined "
    "hundreds of thousands of jobs. A recurring narrative in financial media is that these announcements "
    "are received well by the market, that share prices climb in the days following a layoff because "
    "investors interpret cost-cutting as a sign of discipline. We wanted to find out whether that claim is "
    "actually supported by data, or whether it is a piece of conventional wisdom that does not survive a "
    "careful test.", body))

story.append(P(
    "<b>Stakeholder framing.</b> Two groups have a direct stake in the answer. <i>Investors and analysts</i> "
    "want to know whether layoff announcements are a reliable buy or sell signal so they can price them "
    "into their models. <i>Employees and policymakers</i> want to know whether the market actually "
    "incentivizes job cuts, since that question shapes how we should interpret corporate behavior. If "
    "Wall Street consistently rewards layoffs, that says one thing about the system. If the effect is "
    "small or non-existent, the &ldquo;reward&rdquo; narrative becomes a myth worth correcting.", body))

story.append(P(
    "Concretely we ask: do tech stocks outperform the S&amp;P 500 in the trading days surrounding a layoff "
    "announcement? Three secondary questions follow. Does the size of the layoff matter? Do first-time "
    "layoffs differ from repeat layoffs at the same company? And does the prevailing market regime "
    "(bull or bear) interact with the effect?", body))

story.append(P("1.2 Connection to Course Material", h2))
story.append(P(
    "The hard part of this project is not the statistics; it is the data management. Every stage uses "
    "material from the course. We had to design a relational schema in 3NF that handles the many-to-many "
    "relationship between companies and price observations, ingest two heterogeneous sources (CSV and "
    "JSON-via-API) with different keys, resolve company names to ticker symbols (a classic entity-resolution "
    "problem), and build a pipeline that is idempotent so we can iterate without duplicating rows or "
    "corrupting state. SQL was used for schema definition, foreign keys, CHECK constraints, index "
    "selection, and ON CONFLICT upserts. Pandas and NumPy were used for cleaning, deduplication, and "
    "feature engineering. Statistical inference uses one-sample t-tests, bootstrap resampling, and the "
    "Patell-Z test. The predictive layer is a Random Forest classifier trained with one-hot encoded "
    "categorical features and evaluated under stratified k-fold cross-validation. All of this lines up "
    "directly with course lectures on ETL, normalization, indexing, and supervised learning.", body))

# ---------- 2. Novelty and Importance ----------
story.append(P("2. Novelty and Importance", h1))

story.append(P("2.1 Importance of the Project", h2))
story.append(P(
    "The post-2020 tech layoff wave is one of the most-discussed and least-quantified labor market events "
    "of the decade. Almost every financial news article on a layoff cites the &ldquo;market reaction&rdquo; "
    "in passing, but very few back the claim with a systematic study. By assembling a single reproducible "
    "pipeline that links 4,000+ layoff records with daily price data, we are turning anecdote into "
    "evidence. The result has direct value for anyone trying to read the market: investors deciding how "
    "to react to a layoff headline, journalists writing about labor and capital, and students looking to "
    "see what an applied data-management project on a real-world question looks like end to end.", body))

story.append(P("2.2 Excitement and Relevance", h2))
story.append(P(
    "Both of us have followed the tech layoff wave personally over the past few years. We have friends "
    "and family at companies that went through multiple rounds, and we kept hearing the same line on the "
    "news: &ldquo;the stock jumped after the announcement.&rdquo; That was the spark. The question is "
    "interesting because it sits exactly at the intersection of what we care about (technology and labor) "
    "and what this course teaches (relational design, ETL, statistical inference). Building it gave us a "
    "chance to leverage the skills from class on a question that actually matters to people we know.", body))

story.append(P("2.3 Review of Related Work", h2))
story.append(P(
    "Event studies on layoffs are an old line of research. Worrell, Davidson, and Sharma (1991) found "
    "negative two-day abnormal returns on layoffs, and follow-ups including Palmon, Sun, and Tang (1997) "
    "and Chen, Mehrotra, Sivakumar, and Yu (2001) reported mixed results conditioned on the stated reason "
    "for the layoff (proactive versus reactive). MacKinlay (1997) is the standard methodological "
    "reference for event-study mechanics. Most of these studies used 100 to 400 hand-collected events, "
    "drawn from pre-2010 data, and spanned multiple industries.", body))
story.append(P(
    "Our contribution is scale and focus. We use a 4,000+ event sample drawn entirely from the post-2020 "
    "tech wave, run through a reproducible pipeline that anyone can re-execute. The existing literature "
    "is largely cross-industry and pre-cloud; our dataset is concentrated in software, hardware, and "
    "tech-adjacent firms during a unique macroeconomic period (the post-ZIRP correction), which gives a "
    "much cleaner read on whether the &ldquo;reward&rdquo; narrative holds in the part of the economy where "
    "the narrative is most often invoked.", body))

# ---------- 3. Data and Methodology ----------
story.append(P("3. Data and Methodology", h1))

story.append(P("3.1 Data Sources", h2))
cell = ParagraphStyle(
    "cell", parent=styles["Normal"], fontName="Times-Roman",
    fontSize=9.5, leading=11.5, alignment=TA_CENTER,
)
data_table = [
    [Paragraph("<b>Source</b>", cell), Paragraph("<b>Format</b>", cell),
     Paragraph("<b>Rows Used</b>", cell), Paragraph("<b>Key Fields</b>", cell)],
    [Paragraph("layoffs.fyi (Kaggle mirror)", cell), Paragraph("CSV", cell),
     Paragraph("4,335 events", cell),
     Paragraph("company, date, # laid off, %, industry, stage, funds raised", cell)],
    [Paragraph("Yahoo Finance (yfinance)", cell), Paragraph("JSON to DataFrame", cell),
     Paragraph("281,418 rows", cell),
     Paragraph("trade_date, adj_close, volume", cell)],
    [Paragraph("S&amp;P 500 (^GSPC)", cell), Paragraph("JSON to DataFrame", cell),
     Paragraph("1,666 days", cell),
     Paragraph("trade_date, adj_close", cell)],
]
_dtbl = make_table(data_table, col_widths=[1.45 * inch, 1.15 * inch, 1.1 * inch, 3.1 * inch], header=False)
_dtbl.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8"))]))
story.append(_dtbl)
story.append(Spacer(1, 6))
story.append(P(
    "We pull layoffs.fyi from a frozen Kaggle snapshot rather than scraping the live site. This is "
    "deliberate. Reproducibility requires that anyone re-running our pipeline processes the identical "
    "input, and the live tracker updates daily. Stock prices come from <i>yfinance</i>, which already "
    "returns split- and dividend-adjusted closes, so we do not have to handle corporate actions ourselves.",
    body))

story.append(P("3.2 Database Design", h2))
story.append(P(
    "We use PostgreSQL with a 3NF schema spanning five tables: <b>companies</b> (master record, one row "
    "per firm), <b>layoff_events</b> (one row per announcement), <b>daily_prices</b> (one row per "
    "company-date), <b>market_index</b> (one row per S&amp;P 500 trading day), and <b>event_windows</b> "
    "(derived results). We chose surrogate SERIAL primary keys instead of using ticker symbols because "
    "tickers change. Meta used to be FB; Block used to be SQ; a rename should not cascade through 280K "
    "price rows. All monetary and price fields are NUMERIC rather than FLOAT to avoid binary rounding "
    "error on chained calculations. CHECK constraints reject negative employee counts and out-of-range "
    "percentages at the database layer (defense in depth). A composite index on (company_id, trade_date) "
    "supports the core analytical query, &ldquo;give me prices for company X across this date range,&rdquo; "
    "in milliseconds.", body))

story.append(code(
    "CREATE TABLE companies (\n"
    "    company_id      SERIAL PRIMARY KEY,\n"
    "    company_name    VARCHAR(255) NOT NULL,\n"
    "    ticker_symbol   VARCHAR(10),\n"
    "    industry        VARCHAR(100),\n"
    "    headquarters    VARCHAR(255),\n"
    "    country         VARCHAR(100),\n"
    "    is_public       BOOLEAN NOT NULL DEFAULT FALSE,\n"
    "    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,\n"
    "    CONSTRAINT uq_company_name UNIQUE (company_name),\n"
    "    CONSTRAINT uq_ticker       UNIQUE (ticker_symbol)\n"
    ");",
    "Code 1. The companies master table with UNIQUE constraints on name and ticker. "
    "Source: <i>sql/schema.sql</i>, lines 27-44."
))

story.append(code(
    "CONSTRAINT chk_percentage_range\n"
    "    CHECK (percentage_laid_off IS NULL\n"
    "           OR (percentage_laid_off >= 0 AND percentage_laid_off <= 100)),\n"
    "CONSTRAINT chk_employees_positive\n"
    "    CHECK (employees_laid_off IS NULL OR employees_laid_off >= 0),\n"
    "CONSTRAINT uq_company_date\n"
    "    UNIQUE (company_id, announcement_date)",
    "Code 2. CHECK and UNIQUE constraints on layoff_events. "
    "These reject bad rows at the database layer rather than relying on application-side validation. "
    "Source: <i>sql/schema.sql</i>, lines 73-85."
))

story.append(P("3.3 ETL Pipeline", h2))
story.append(P(
    "The pipeline runs in five idempotent stages, each as a standalone Python script. Every stage uses "
    "ON CONFLICT clauses so it can be re-executed without producing duplicates, a property we relied on "
    "heavily during iteration.", body))

story.extend(B([
    "<b>Phase 1, Ingest.</b> Parse the raw CSV; normalize company names, dates, and percentage strings; "
    "upsert into <i>companies</i> and <i>layoff_events</i>. Result: 2,873 unique companies, 4,335 events.",
    "<b>Phase 2a, Ticker matching.</b> A layered resolver: a manual override map for the highest-impact "
    "firms (where fuzzy match silently picks the wrong ticker, e.g., &ldquo;Apple&rdquo; matched to "
    "<i>APLE</i> Apple Hospitality REIT), then <i>yf.Search</i> with name-similarity validation. Result: "
    "196 matched public companies covering about 56% of the dataset&rsquo;s total laid-off employees.",
    "<b>Phase 2b, Price fetch.</b> For each matched ticker plus ^GSPC, pull daily prices over a window "
    "wide enough to support a (&minus;250, +30) estimation/event span. Rate-limited and retried.",
    "<b>Phase 3, Event study.</b> Compute log returns, market-adjusted abnormal returns, CARs, and "
    "SCARs across four windows. Run the OLS regression and Random Forest. Persist results to "
    "<i>event_windows</i> and to flat files for the visualizer.",
    "<b>Phase 4, Visualization.</b> Render the six pre-registered plots at 300 dpi.",
]))

story.append(P("Code from Phase 1 shows our deduplication strategy. When the source CSV contains two rows "
    "for the same (company, date), we keep the row with more non-null fields rather than picking arbitrarily.",
    body))

story.append(code(
    "df[\"__non_null_count\"] = df.notna().sum(axis=1)\n"
    "df = df.sort_values(\"__non_null_count\", ascending=False)\n"
    "before = len(df)\n"
    "df = df.drop_duplicates(subset=[\"company\", \"date\"], keep=\"first\")\n"
    "after = len(df)\n"
    "if before != after:\n"
    "    logger.info(f\"  Deduplicated: {before} -> {after} rows\")\n"
    "df = df.drop(columns=[\"__non_null_count\"])",
    "Code 3. Phase 1 deduplication that keeps the most-complete row per (company, date) pair. "
    "Source: <i>src/ingest_layoffs.py</i>, lines 144-151."
))

story.append(P("Phase 2a uses a hand-curated override map for the largest firms before falling back to "
    "the Yahoo Finance search API. This cleanly avoids the most common entity-resolution failures.", body))

story.append(code(
    "MANUAL_TICKER_MAP = {\n"
    "    \"meta\": \"META\", \"facebook\": \"META\",\n"
    "    \"google\": \"GOOGL\", \"alphabet\": \"GOOGL\",\n"
    "    \"amazon\": \"AMZN\", \"microsoft\": \"MSFT\",\n"
    "    \"apple\": \"AAPL\", \"netflix\": \"NFLX\",\n"
    "    \"salesforce\": \"CRM\", \"oracle\": \"ORCL\",\n"
    "    \"nvidia\": \"NVDA\", \"amd\": \"AMD\",\n"
    "    # ... ~50 more entries\n"
    "}",
    "Code 4. Excerpt of the manual ticker override map. "
    "Source: <i>src/match_tickers.py</i>, lines 68-87."
))

story.append(P("3.4 Analytical Methodology", h2))
story.append(P(
    "We follow the standard event-study recipe (MacKinlay, 1997). For each event we define event day "
    "t = 0 as the first trading day on or after the announcement date (using the ^GSPC calendar). "
    "Returns are log returns, R(t) = ln(P_t / P_{t&minus;1}). Abnormal returns are <i>market-adjusted</i>, "
    "AR(t) = R_stock(t) &minus; R_market(t). Cumulative abnormal return over an event window (a, b) is "
    "CAR = sum of AR(t) for t = a to b. To control for cross-sectional variance we also compute "
    "Standardized CARs using the (&minus;250, &minus;31) pre-event estimation window.", body))

story.append(code(
    "market = market.sort_values(\"trade_date\").copy()\n"
    "market[\"r_mkt\"] = np.log(market[\"adj_close\"] / market[\"adj_close\"].shift(1))\n"
    "\n"
    "for cid, grp in prices.groupby(\"company_id\"):\n"
    "    g = grp.sort_values(\"trade_date\").copy()\n"
    "    g[\"r_stock\"] = np.log(g[\"adj_close\"] / g[\"adj_close\"].shift(1))\n"
    "    per_company[int(cid)] = g[[\"adj_close\", \"r_stock\"]]",
    "Code 5. Computing log returns for the market index and each company. "
    "Source: <i>src/analyze_events.py</i>, lines 159-168."
))

story.append(P(
    "All key analysis choices were <b>pre-registered</b> in the proposal to avoid p-hacking:", body))
story.extend(B([
    "<b>Headline window:</b> (&minus;5, +5) trading days.",
    "<b>Hypothesis test:</b> two-sided one-sample t-test on mean CAR vs. zero, plus a Patell-Z on the SCAR "
    "distribution.",
    "<b>Robustness:</b> three additional windows reported as secondary, namely (&minus;30, +30), "
    "(&minus;1, +1), and (0, +3).",
    "<b>Bootstrap CI:</b> 1,000 percentile resamples on mean CAR.",
    "<b>Regression:</b> OLS with HC3 heteroskedasticity-robust standard errors. Predictors include log "
    "employees laid off, percentage laid off, repeat-layoff indicator, days since prior layoff, log funds "
    "raised, 30-day market regime, and industry/stage fixed effects.",
    "<b>Classification:</b> Random Forest (500 trees, class-balanced) predicting the sign of CAR, "
    "evaluated under stratified 5-fold CV with accuracy and ROC-AUC.",
]))

story.append(code(
    "t_stat, p_value = stats.ttest_1samp(cars, 0.0)\n"
    "rng = np.random.default_rng(42)\n"
    "boot = np.array([\n"
    "    rng.choice(cars, size=n, replace=True).mean() for _ in range(1000)\n"
    "])\n"
    "ci_lo, ci_hi = np.percentile(boot, [2.5, 97.5])\n"
    "\n"
    "scars = per_event_df[scar_col].dropna().to_numpy()\n"
    "scar_z = float(np.mean(scars) * np.sqrt(len(scars)))\n"
    "scar_p = float(2 * (1 - stats.norm.cdf(abs(scar_z))))",
    "Code 6. The headline hypothesis test: t-test on CAR, percentile bootstrap CI, "
    "and Patell-style Z on SCAR. Source: <i>src/analyze_events.py</i>, lines 403-414."
))

# ---------- 4. Results ----------
story.append(P("4. Results and Analysis", h1))

story.append(P("4.1 Headline Result", h2))
story.append(P(
    "Across 505 events with complete (&minus;5, +5) data, the mean CAR is <b>&minus;1.12%</b> with median "
    "&minus;0.05%. The one-sample t-statistic of &minus;1.75 yields p = 0.080, just outside the 5% "
    "threshold, and the bootstrap 95% CI [&minus;2.37%, +0.13%] crosses zero. The SCAR-based Patell-Z, "
    "which down-weights events with high pre-event volatility, is more decisive: <b>Z = &minus;2.37, "
    "p = 0.018</b>. Taken together, the evidence runs against the &ldquo;reward&rdquo; hypothesis and "
    "leans (mildly) toward the opposite.", body))

stat_table = [
    ["Statistic", "Value"],
    ["N events with complete CAR", "505"],
    ["Mean CAR (-5, +5)", "-1.12%"],
    ["Median CAR", "-0.05%"],
    ["Std CAR", "14.3%"],
    ["t-statistic", "-1.75"],
    ["p-value (two-sided)", "0.080"],
    ["95% bootstrap CI", "[-2.37%, +0.13%]"],
    ["SCAR Patell Z", "-2.37"],
    ["SCAR p-value", "0.018 (significant)"],
]
story.append(make_table(stat_table, col_widths=[2.6 * inch, 2.0 * inch]))
story.append(P("Table 1. Headline (&minus;5, +5) test statistics.", caption))

story.append(P(
    "All four windows agree in direction. (&minus;30, +30) shows mean CAR = &minus;5.2%, the tightest "
    "window (&minus;1, +1) shows &minus;0.64%, and the post-announcement (0, +3) window shows &minus;0.99%. "
    "The consistency across windows means our headline result is not an artifact of one specific choice.",
    body))

story.append(fig("1_avg_daily_ar_timeline.png",
    "Figure 1. Average daily abnormal return from 30 trading days before to 30 days after layoff "
    "announcements, with 95% confidence band. The series sits slightly below zero throughout the "
    "post-event window with no recovery, consistent with a small persistent negative drift rather than "
    "a sharp one-day reaction."))

story.append(fig("2_car_histogram.png",
    "Figure 2. Distribution of (&minus;5, +5) CAR across 505 events. The distribution is heavy-tailed "
    "(kurtosis 5.9) and approximately symmetric around the median, but the mass is shifted slightly "
    "left of zero, producing the negative mean."))

story.append(P("4.2 Does Layoff Size Matter?", h2))
story.append(P(
    "Both absolute size (employees laid off) and relative size (percent of workforce) are essentially "
    "uncorrelated with CAR. Regressing CAR on log(employees) gives a slope of &minus;0.4% per log unit "
    "with R&sup2; &asymp; 0.000 (p = 0.99). Percentage of workforce shows a slight negative tilt at "
    "extreme values (slope &minus;0.13%/% point, p = 0.06), driven by a handful of large-percentage "
    "outliers in small companies. Either way, this is a much weaker effect than the conventional wisdom "
    "would predict.", body))

story.append(fig("3_layoff_size_vs_car.png",
    "Figure 3. Layoff size versus CAR. Both regressions are visually flat with broad confidence bands, "
    "and the absolute-size relationship is statistically indistinguishable from zero."))

story.append(P("4.3 First-Time vs. Repeat Layoffs", h2))
story.append(P(
    "First-time layoffs show a noticeably larger negative average reaction (mean CAR = &minus;2.99%, "
    "n = 171) than repeat layoffs (&minus;0.16%, n = 334). A Welch t-test gives t = &minus;2.12, "
    "p = 0.035, statistically significant. This is intuitive: a first layoff is genuinely new "
    "information about the company&rsquo;s trajectory, while a third or fourth round at the same "
    "company tells the market less it does not already know.", body))

story.append(fig("4_first_vs_repeat.png",
    "Figure 4. CAR distributions for first-time versus repeat layoff announcements. Both distributions "
    "are wide, but the first-time mean is meaningfully lower."))

story.append(P("4.4 Regression and Random Forest", h2))
story.append(P(
    "The OLS regression on the full feature set achieves R&sup2; = 0.090 (adjusted R&sup2; = 0.032). "
    "Most layoff-specific predictors are not significant after controlling for industry and stage "
    "fixed effects. The strongest individual coefficients are <i>stage = Post-IPO</i> (&minus;0.207, "
    "p &lt; 0.001) and several mid-stage venture buckets, all with negative point estimates. This "
    "pattern lines up with the first-vs-repeat result: companies further along the funding ladder, "
    "which dominate the sample, see slightly more negative reactions.", body))

story.append(P(
    "We trained a Random Forest classifier (500 trees, class-balanced, stratified 5-fold CV) to "
    "predict the sign of CAR. The cross-validated ROC-AUC is <b>0.46 &plusmn; 0.08</b>, below 0.5, "
    "i.e., no better than random guessing. Feature importances are diffuse: the highest-Gini feature "
    "is <i>market_regime_30d</i> (the prevailing 30-day S&amp;P trend) at 0.17, with all "
    "layoff-specific features clustered below it. The takeaway is that layoff-specific features do "
    "not contain reliable ex-ante signal about the sign of the market response. Whatever drives "
    "individual reactions is mostly outside the variables in our dataset.", body))

story.append(code(
    "clf = RandomForestClassifier(\n"
    "    n_estimators=500,\n"
    "    random_state=42,\n"
    "    class_weight=\"balanced\",\n"
    "    n_jobs=-1,\n"
    ")\n"
    "pipe = Pipeline([(\"prep\", preprocessor), (\"rf\", clf)])\n"
    "\n"
    "acc_scores = cross_val_score(pipe, X, y, scoring=\"accuracy\", cv=5, n_jobs=-1)\n"
    "auc_scores = cross_val_score(pipe, X, y, scoring=\"roc_auc\", cv=5, n_jobs=-1)",
    "Code 7. Random Forest configuration and 5-fold cross-validation. "
    "Source: <i>src/analyze_events.py</i>, lines 498-510."
))

story.append(fig("5_rf_feature_importance.png",
    "Figure 5. Random Forest feature importances (Gini, mean across 5 CV folds). Macro context "
    "(market_regime_30d) outranks every layoff-specific feature, but no feature dominates."))

story.append(P("4.5 Temporal Patterns", h2))
story.append(P(
    "The monthly heatmap reveals two things. First, layoff volume is heavily clustered. 42 "
    "matched-company events occurred in January 2023 alone, the peak of the post-ZIRP correction. "
    "Second, mean CARs vary widely across months without an obvious seasonal pattern. The largest "
    "single-month deviations (e.g., November 2021 at &minus;38.8%, February 2022 at +20.6%) come "
    "from sparse cells where one or two outlier events drive the average. The high-volume cells in "
    "2023 are closer to zero, consistent with the headline finding.", body))

story.append(fig("6_monthly_heatmap.png",
    "Figure 6. Monthly event volume (top) and mean (&minus;5, +5) CAR (bottom). Bright-red and "
    "bright-blue extremes coincide with low-N months; the high-volume central cells in 2023 are the "
    "closest to zero."))

# ---------- 5. Experimental Design and Evaluation ----------
story.append(P("5. Experimental Design and Evaluation", h1))

story.append(P("5.1 Hypothesis", h2))
story.append(P(
    "Going in, our prediction was that the &ldquo;Wall Street rewards layoffs&rdquo; narrative would "
    "show up as a small but positive mean CAR, on the order of +0.5% to +1.5%, in the (&minus;5, +5) "
    "window. We expected layoff <i>size</i> (both absolute and percentage) to be the strongest individual "
    "predictor, with larger layoffs producing larger positive reactions. We also expected first-time "
    "layoffs to have a more muted reaction than repeat layoffs, on the theory that the first cut signals "
    "decisive new management action while later cuts signal ongoing weakness.", body))

story.append(P("5.2 Key Findings", h2))
story.append(P(
    "Our hypothesis turned out to be wrong on direction and partially wrong on the secondary questions:",
    body))
story.extend(B([
    "<b>Direction:</b> mean CAR is &minus;1.12%, not positive. The &ldquo;reward&rdquo; framing is not "
    "supported.",
    "<b>Layoff size:</b> essentially uncorrelated with CAR. Slope on log(employees) is statistically "
    "zero (p = 0.99).",
    "<b>First-time vs. repeat:</b> our directional prediction was wrong. First-time layoffs are "
    "<i>more</i> negative (&minus;2.99% vs. &minus;0.16%, Welch p = 0.035), not less. The market "
    "treats the first cut as new information and discounts subsequent cuts.",
    "<b>Predictability:</b> a 5-fold cross-validated Random Forest cannot beat random on the sign of "
    "CAR (AUC = 0.46). The single most important feature is the 30-day market regime, not any "
    "layoff-specific variable.",
]))

story.append(P("5.3 Evaluation", h2))
story.append(P(
    "We evaluate the headline question using a one-sample two-sided t-test (mean CAR vs. zero), a "
    "Patell-style Z-test on standardized CAR, and a 1,000-sample percentile bootstrap CI. The three "
    "tests give a coherent picture, with the Patell-Z and the t-test pointing the same direction and "
    "the bootstrap CI confirming the magnitude. We report effect-direction agreement across four "
    "different windows as an honest robustness check rather than picking the most flattering "
    "post-hoc.", body))
story.append(P(
    "For the predictive layer, we report 5-fold cross-validated accuracy and ROC-AUC with standard "
    "deviations across folds. Because the target is roughly balanced (positive-CAR rate = 0.499), "
    "ROC-AUC is the more honest metric, and an AUC of 0.46 is a clear &ldquo;no signal&rdquo; result. "
    "Feature importances are reported with their standard deviation across the 500 trees, which makes "
    "it visible that no single feature dominates.", body))

story.append(P("5.4 Advantages and Limitations", h2))
story.append(P("<b>Advantages.</b>", body))
story.extend(B([
    "<b>Scale.</b> 4,335 events at 2,873 companies versus the few hundred used by prior literature.",
    "<b>Reproducibility.</b> Every stage is idempotent and re-runnable from a single command sequence. "
    "The pipeline rebuilds the database, fetches data, runs the analysis, and produces all six figures "
    "and all four tables.",
    "<b>Data hygiene.</b> CHECK constraints, UNIQUE constraints, and a manual ticker override map "
    "filter out the most common classes of error before they reach the analysis layer.",
    "<b>Pre-registered choices.</b> Windows, tests, and feature set were declared in the proposal "
    "before results were known, which limits the room for p-hacking.",
]))

story.append(P("<b>Limitations.</b>", body))
story.extend(B([
    "<b>Sample bias.</b> Only 196 of 2,873 companies (about 7%) were public with tradable tickers. The "
    "rest are private and excluded from the stock analysis. The matched companies still capture "
    "approximately 56% of the dataset&rsquo;s total laid-off employees, but the results do not "
    "generalize to private VC-funded startups.",
    "<b>Single-factor market model.</b> We benchmark only against the S&amp;P 500. A Fama-French "
    "three- or five-factor model would absorb sector and size effects more cleanly. For short windows "
    "the two approaches converge (MacKinlay, 1997), so we do not expect this to overturn the "
    "qualitative finding, but it could tighten the confidence interval.",
    "<b>Announcement vs. leak date.</b> Some layoffs leak to the press days before the official "
    "announcement, in which case the &ldquo;true&rdquo; event date is earlier than what the CSV "
    "records. This biases <i>toward</i> a smaller measured effect, since some of the price reaction has "
    "already occurred outside our window.",
    "<b>Multicollinearity in the OLS.</b> The condition number of the regressor matrix is "
    "3.76e+05, flagging multicollinearity (<i>has_pct</i>, <i>has_funds</i>, and the "
    "missingness indicators are partially redundant with the underlying variables). Coefficient point "
    "estimates should be read as exploratory, not causal.",
    "<b>Single benchmark, single country.</b> All companies are benchmarked against ^GSPC even though "
    "a small fraction are non-US. Currency and exchange-calendar mismatches are a small known source "
    "of noise.",
]))

# ---------- 6. Changes After Proposal ----------
story.append(P("6. Changes After Proposal", h1))

story.append(P("6.1 Differences from Proposal", h2))
story.append(P(
    "The methodology and pipeline shape we proposed in February held up well. The schema is the one we "
    "drafted, the analysis windows are the ones we pre-registered, and the final figures map to the six "
    "we promised. A few things changed during execution.", body))
story.extend(B([
    "<b>Ticker matching pivoted away from pure fuzzy matching.</b> The proposal said we would use "
    "fuzzy matching (rapidfuzz) on names that fall outside our manual top-100 list. In practice the "
    "fuzzy approach silently produced wrong tickers (e.g., Apple matching to Apple Hospitality REIT). "
    "We replaced it with the <i>yf.Search</i> API plus name-similarity validation, which is more "
    "conservative and safer for downstream analysis.",
    "<b>Added the SCAR / Patell-Z test.</b> The proposal listed only a one-sample t-test. While "
    "implementing the analysis we realized that the cross-sectional variance is too heterogeneous "
    "for an unweighted t-test to be the only test, so we added the Patell-style Z on standardized "
    "CARs. This turned out to matter: the SCAR test is the one that crosses the 0.05 threshold, while "
    "the plain t-test is borderline.",
    "<b>Sample size came in lower than the upper end of the proposal.</b> We projected 400-600 events "
    "with full price coverage and ended at 505. The match rate was lower than hoped, since "
    "VC-funded private companies dominate the layoffs.fyi dataset.",
    "<b>The Random Forest result was a partial surprise.</b> We expected modest predictive signal. "
    "Getting an AUC below 0.5 was not in the plan, but it is itself a meaningful finding: the absence "
    "of signal is the result.",
]))

story.append(P("6.2 Bottlenecks and Challenges", h2))
story.extend(B([
    "<b>Entity resolution.</b> The single hardest engineering problem was matching free-text company "
    "names to ticker symbols. layoffs.fyi has &ldquo;Meta&rdquo;, &ldquo;Meta Platforms&rdquo;, and "
    "&ldquo;Facebook&rdquo; for the same company, plus typos and minor variations. Building the "
    "manual override map for the top firms, plus a conservative search-API fallback, took more time "
    "than any other piece of the pipeline.",
    "<b>Yahoo Finance rate limits.</b> The yfinance library is unofficial and can throttle or fail "
    "silently. We added retry logic and made Phase 2b idempotent so that interrupted runs could "
    "resume without refetching everything. Total fetch time in a clean run is roughly 5 to 10 "
    "minutes for 196 tickers and the index.",
    "<b>NUMERIC vs. FLOAT.</b> Early on we used FLOAT for prices and noticed that chained log-return "
    "calculations on FLOAT accumulate enough rounding error over 280K rows to shift the third "
    "significant figure of the headline CAR. We migrated to NUMERIC, which is the standard practice "
    "for any system that touches money.",
    "<b>Trading-day alignment.</b> A non-trivial fraction of layoffs are announced after-hours on a "
    "Friday. We had to define event day t = 0 as the first trading day on or after the announcement "
    "(using the ^GSPC calendar) so that weekend and holiday announcements are handled uniformly.",
]))

# ---------- 7. Conclusion and Future Work ----------
story.append(P("7. Conclusion and Future Work", h1))

story.append(P("7.1 Summary of Contributions", h2))
story.append(P(
    "We set out to test whether tech layoff announcements move stock prices in a measurable, predictable "
    "direction. After running an event study on 505 announcements with complete data, the answer is: "
    "not really. The headline (&minus;5, +5) mean CAR is &minus;1.12% with a borderline t-test "
    "(p = 0.080) and a significant SCAR Patell-Z (p = 0.018). The point estimate is consistently "
    "negative across four windows. Layoff size, percentage, and most company-level features explain "
    "almost none of the variance, and a Random Forest classifier cannot beat random guessing on the "
    "sign of the reaction. The popular narrative that Wall Street rewards layoffs is not supported. "
    "The data instead points to a market that mostly shrugs, with a small negative tilt, consistent "
    "with the layoff being confirmatory information rather than news.", body))

story.append(P(
    "Beyond the substantive answer, this project was an exercise in turning a messy, multi-source data "
    "problem into a queryable, reproducible system. The most useful lesson is that the analytical "
    "findings are only as trustworthy as the entity-resolution and idempotency work upstream of them. "
    "Getting the right ticker for each company turned out to matter more than any single statistical "
    "choice.", body))

tightbullet = ParagraphStyle(
    "tightbullet", parent=bullet, leading=12.5, spaceAfter=0,
)
def TB(items):
    return [Paragraph(f"&bull;&nbsp; {t}", tightbullet) for t in items]

story.append(P("Author contributions.", h2))
story.append(P("<b>Azam Ahmed</b> (Phases 2b, 3, 4)", body))
story.extend(TB([
    "Built Phase 2b price fetcher: yfinance puller with retry logic and idempotent re-runs.",
    "Implemented the event-study core: log returns, AR/CAR/SCAR across four windows.",
    "Hypothesis testing: one-sample t-test, 1,000-sample bootstrap CI, Patell-style Z on SCAR.",
    "Wrote the OLS regression module with HC3 robust standard errors.",
    "Built the Random Forest classifier and feature-engineering pipeline (5-fold CV).",
    "Built the visualization module: six 300 dpi figures and four result tables.",
]))
story.append(Spacer(1, 4))
story.append(P("<b>Xuan Liao</b> (Phases 1, 2a, documentation)", body))
story.extend(TB([
    "Designed the PostgreSQL 3NF schema: foreign keys, CHECK constraints, and indexes.",
    "Built Phase 1 ingest: CSV cleaning, deduplication, two-pass company/event upsert.",
    "Curated the manual ticker override map for the ~50 highest-impact firms.",
    "Built Phase 2a ticker matching: <i>yf.Search</i> integration with name-similarity validation.",
    "Project documentation: Phase 2a write-up, README, and SQL migration files.",
    "Proposal literature review (Worrell, Palmon, Chen, MacKinlay, Patell).",
]))
story.append(Spacer(1, 4))
story.append(P(
    "Both authors reviewed all code, shared the writing, and prepared the oral exam deck together.",
    body))

story.append(P("7.2 Future Directions", h2))
story.extend(B([
    "Replace the single-factor model with a Fama-French five-factor regression to cleanly separate "
    "sector exposure from the layoff-specific abnormal return.",
    "Sentiment-tag each press release (NLP on the source URL) and condition CAR on whether the "
    "layoff is framed as &ldquo;restructuring,&rdquo; &ldquo;efficiency,&rdquo; or &ldquo;weak "
    "demand.&rdquo; Chen et al. (2001) found large differences along this axis on a much smaller "
    "sample.",
    "Extend the matching layer to use Wikidata and SEC EDGAR APIs so the resolver can be pushed past "
    "the current ~7% match rate without manual overrides.",
    "Run a placebo test: pick random non-event dates for the same companies, recompute CARs, and "
    "verify that the layoff-event distribution is statistically distinguishable from the placebo.",
]))

story.append(P(
    "<b>Reproducibility.</b> The full pipeline (schema migration, ingest, ticker matching, price "
    "fetch, event study, visualization) runs from a single command sequence documented in the "
    "<i>README.md</i>. Every stage is idempotent.", body))

# ---------- References ----------
story.append(P("References", h1))
refs = [
    "Worrell, D. L., Davidson, W. N., &amp; Sharma, V. M. (1991). Layoff announcements and stockholder "
    "wealth. <i>Academy of Management Journal</i>, 34(3), 662-678.",
    "Palmon, O., Sun, H. L., &amp; Tang, A. P. (1997). Layoff announcements: Stock price impact and "
    "financial performance. <i>Financial Management</i>, 26(3), 54-68.",
    "Chen, P., Mehrotra, V., Sivakumar, R., &amp; Yu, W. W. (2001). Layoffs, shareholders&rsquo; "
    "wealth, and corporate performance. <i>Journal of Empirical Finance</i>, 8(2), 171-199.",
    "MacKinlay, A. C. (1997). Event studies in economics and finance. <i>Journal of Economic "
    "Literature</i>, 35(1), 13-39.",
    "Patell, J. M. (1976). Corporate forecasts of earnings per share and stock price behavior. "
    "<i>Journal of Accounting Research</i>, 14(2), 246-276.",
    "Fama, E. F., Fisher, L., Jensen, M. C., &amp; Roll, R. (1969). The adjustment of stock prices to "
    "new information. <i>International Economic Review</i>, 10(1), 1-21.",
    "layoffs.fyi tracker, Kaggle mirror: <i>kaggle.com/datasets/swaptr/layoffs-2022</i>.",
    "Yahoo Finance via the <i>yfinance</i> Python package.",
]
refstyle = ParagraphStyle(
    "ref", parent=bullet, fontSize=10, leading=12.5, spaceAfter=2,
)
for r in refs:
    story.append(Paragraph(f"&bull;&nbsp; {r}", refstyle))

# ---------- build ----------
doc = SimpleDocTemplate(
    str(OUT), pagesize=LETTER,
    leftMargin=0.85 * inch, rightMargin=0.85 * inch,
    topMargin=0.7 * inch, bottomMargin=0.7 * inch,
    title="Do Tech Layoffs Help Stock Prices?",
    author="Azam Ahmed, Xuan Liao",
)

def _footer(canvas, d):
    canvas.saveState()
    canvas.setFont("Times-Italic", 8.5)
    canvas.setFillColor(colors.grey)
    canvas.drawString(0.85 * inch, 0.4 * inch,
        "Ahmed and Liao, Do Tech Layoffs Help Stock Prices?, CS 210, Spring 2026")
    canvas.drawRightString(LETTER[0] - 0.85 * inch, 0.4 * inch, f"Page {d.page}")
    canvas.restoreState()

doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
print(f"Wrote {OUT}")
