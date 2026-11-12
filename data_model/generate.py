"""Fill the Hoshi Stream tables with seeded, internally consistent synthetic data.

Runs as a serverless spark_python_task. Generation is numpy with one RNG stream per
stage (SEED + stage id), so the same seed and as-of date give identical data. Rows are
written with insertInto into the tables created by build_ddl.py, so the DDL (types,
comments, constraints) stays the source of truth. After the last table, one row goes to
<catalog>.<prefix>lab.data_manifest with the as-of date, seed, model pin and row counts.

Usage: generate.py --root <lab dir> [--as-of YYYY-MM-DD]
"""

import argparse
import calendar
import tempfile
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

SEED = 2026
WINDOW_MONTHS = 34
STAGES = [
    "genre",
    "series",
    "titles",
    "episodes",
    "subs",
    "sessions",
    "impressions",
    "campaigns",
    "deals",
    "mgs",
    "holders",
    "licenses",
    "statements",
    "windows",
    "talent",
    "offers",
    "redemptions",
    "invoices",
    "refunds",
    "churn",
    "partners",
    "advertisers",
    "misc",
]
STAGE = {n: i for i, n in enumerate(STAGES)}


def rng(stage):
    return np.random.default_rng([SEED, STAGE[stage]])


def add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    y, m = y + d.year, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


GENRES = [
    "Action",
    "Adventure",
    "Comedy",
    "Drama",
    "Fantasy",
    "Horror",
    "Mystery",
    "Romance",
    "Sci-Fi",
    "Slice of Life",
    "Sports",
    "Thriller",
    "Mecha",
    "Isekai",
    "Shonen",
    "Shojo",
    "Seinen",
    "Music",
    "Idol",
    "Historical",
    "Supernatural",
    "School Life",
    "Military",
    "Psychological",
    "Kids",
]
ADJ = [
    "Crimson",
    "Silver",
    "Hollow",
    "Azure",
    "Ember",
    "Gale",
    "Iron",
    "Lunar",
    "Storm",
    "Velvet",
    "Paper",
    "Glass",
    "Thorn",
    "Tidal",
    "Neon",
    "Frost",
    "Ashen",
    "Verdant",
    "Scarlet",
    "Quiet",
]
NOUN = [
    "Harbor",
    "Shrine",
    "Circuit",
    "Orchard",
    "Vanguard",
    "Lantern",
    "Meadow",
    "Requiem",
    "Bloom",
    "Sentinel",
    "Tempest",
    "Archive",
    "Carnival",
    "Relic",
    "Voyage",
    "Garden",
    "Chronicle",
    "Ferry",
    "Summit",
    "Rampart",
]

# iso2, iso3, name, group, currency, language, time zone, population. Indexes 0..21 are served.
TERRITORIES = [
    (
        "US",
        "USA",
        "United States",
        "NA",
        "USD",
        "English",
        "America/New_York",
        335000000,
    ),
    ("CA", "CAN", "Canada", "NA", "CAD", "English", "America/Toronto", 39000000),
    (
        "PR",
        "PRI",
        "Puerto Rico",
        "NA",
        "USD",
        "Spanish",
        "America/Puerto_Rico",
        3200000,
    ),
    ("BS", "BHS", "Bahamas", "NA", "USD", "English", "America/Nassau", 400000),
    (
        "BR",
        "BRA",
        "Brazil",
        "LATAM",
        "BRL",
        "Portuguese",
        "America/Sao_Paulo",
        216000000,
    ),
    (
        "MX",
        "MEX",
        "Mexico",
        "LATAM",
        "MXN",
        "Spanish",
        "America/Mexico_City",
        128000000,
    ),
    (
        "AR",
        "ARG",
        "Argentina",
        "LATAM",
        "ARS",
        "Spanish",
        "America/Argentina/Buenos_Aires",
        46000000,
    ),
    ("CO", "COL", "Colombia", "LATAM", "COP", "Spanish", "America/Bogota", 52000000),
    ("CL", "CHL", "Chile", "LATAM", "CLP", "Spanish", "America/Santiago", 20000000),
    ("PE", "PER", "Peru", "LATAM", "PEN", "Spanish", "America/Lima", 34000000),
    (
        "GB",
        "GBR",
        "United Kingdom",
        "EMEA",
        "GBP",
        "English",
        "Europe/London",
        68000000,
    ),
    ("DE", "DEU", "Germany", "EMEA", "EUR", "German", "Europe/Berlin", 84000000),
    ("FR", "FRA", "France", "EMEA", "EUR", "French", "Europe/Paris", 68000000),
    ("ES", "ESP", "Spain", "EMEA", "EUR", "Spanish", "Europe/Madrid", 48000000),
    ("IT", "ITA", "Italy", "EMEA", "EUR", "Italian", "Europe/Rome", 59000000),
    (
        "AE",
        "ARE",
        "United Arab Emirates",
        "EMEA",
        "AED",
        "Arabic",
        "Asia/Dubai",
        10000000,
    ),
    ("JP", "JPN", "Japan", "APAC", "JPY", "Japanese", "Asia/Tokyo", 124000000),
    ("KR", "KOR", "South Korea", "APAC", "KRW", "Korean", "Asia/Seoul", 52000000),
    ("AU", "AUS", "Australia", "APAC", "AUD", "English", "Australia/Sydney", 26000000),
    ("PH", "PHL", "Philippines", "APAC", "PHP", "English", "Asia/Manila", 115000000),
    ("SG", "SGP", "Singapore", "APAC", "SGD", "English", "Asia/Singapore", 6000000),
    ("IN", "IND", "India", "APAC", "INR", "English", "Asia/Kolkata", 1400000000),
    (
        "NL",
        "NLD",
        "Netherlands",
        "Rights-only",
        "EUR",
        "Dutch",
        "Europe/Amsterdam",
        18000000,
    ),
    (
        "SE",
        "SWE",
        "Sweden",
        "Rights-only",
        "SEK",
        "Swedish",
        "Europe/Stockholm",
        10500000,
    ),
    (
        "ZA",
        "ZAF",
        "South Africa",
        "Rights-only",
        "ZAR",
        "English",
        "Africa/Johannesburg",
        60000000,
    ),
    ("TW", "TWN", "Taiwan", "Rights-only", "TWD", "Chinese", "Asia/Taipei", 23000000),
    ("TH", "THA", "Thailand", "Rights-only", "THB", "Thai", "Asia/Bangkok", 72000000),
    (
        "NZ",
        "NZL",
        "New Zealand",
        "Rights-only",
        "NZD",
        "English",
        "Pacific/Auckland",
        5300000,
    ),
    ("IE", "IRL", "Ireland", "Rights-only", "EUR", "English", "Europe/Dublin", 5300000),
    ("PL", "POL", "Poland", "Rights-only", "PLN", "Polish", "Europe/Warsaw", 37500000),
]
TER_US, TER_BR, TER_MX, TER_PH, TER_JP, TER_KR = 0, 4, 5, 19, 16, 17
REGION_RANGE = {
    "NA": [0, 1, 2, 3],
    "LATAM": [4, 5, 6, 7, 8, 9],
    "EMEA": [10, 11, 12, 13, 14, 15],
    "APAC": [16, 17, 18, 19, 20, 21],
}
COUNTRY_WEIGHTS = {
    "NA": [0.75, 0.15, 0.07, 0.03],
    "LATAM": [0.32, 0.24, 0.14, 0.12, 0.09, 0.09],
    "EMEA": [0.22, 0.20, 0.18, 0.16, 0.14, 0.10],
    "APAC": [0.30, 0.16, 0.14, 0.14, 0.10, 0.16],
}
REGION_SHARE = {"NA": 0.28, "LATAM": 0.22, "EMEA": 0.25, "APAC": 0.25}
PLATFORM = {
    "NA": (1, 2),
    "LATAM": (3, 4),
    "EMEA": (5, 6),
    "APAC": (7, 8),
}  # (web and mobile, tv and console)
TAX = {"NA": 0.07, "LATAM": 0.10, "EMEA": 0.15, "APAC": 0.08}

# id: (code, name, type, tier, monthly or annual list price, term months, trial days, ad supported)
PLANS = {
    1: ("FREE", "Free", "Free", "Free", 0.0, 1, 0, True),
    2: ("FAN-M", "Fan", "Paid", "Fan", 7.99, 1, 14, False),
    3: ("MEGA-M", "Mega Fan", "Paid", "Mega Fan", 11.99, 1, 14, False),
    4: ("ULT-M", "Ultimate Fan", "Paid", "Ultimate Fan", 15.99, 1, 14, False),
    5: ("FAN-A", "Fan Annual", "Paid", "Fan", 79.99, 12, 14, False),
    6: ("MEGA-A", "Mega Fan Annual", "Paid", "Mega Fan", 119.99, 12, 14, False),
    7: ("ULT-A", "Ultimate Fan Annual", "Paid", "Ultimate Fan", 159.99, 12, 14, False),
}
PLAN_MIX = np.array([0.25, 0.30, 0.15, 0.08, 0.09, 0.07, 0.06])
SWITCH_MIX = PLAN_MIX[1:] / PLAN_MIX[1:].sum()  # plan changes only move between paid plans
LATAM_NEW_PRICE = {2: 9.99, 3: 14.99, 4: 19.99, 5: 99.99, 6: 149.99, 7: 199.99}
PRICE_UPLIFT_MONTHS = 6
SPIKE_MONTHS = 2
BASE_HAZARD = {"free": 0.02, "monthly": 0.024, "annual": 0.006}
SPIKE_MULT = 3.5
SWITCH_P = 0.02
REASONS = ["price", "content", "competitor", "technical", "not_using", "other"]
REASON_P = np.array([0.03, 0.27, 0.22, 0.12, 0.23, 0.13])
REASON_TEXT = {
    "price": "Price increase was too high for the value",
    "content": "Not enough new shows to keep watching",
    "competitor": "Moved to another streaming service",
    "technical": "Playback or app problems",
    "not_using": "Stopped watching",
    "other": "Other reason",
}
CHANNELS = [
    "Organic search",
    "Paid social",
    "App store",
    "Partner bundle",
    "Referral",
    "Free trial",
]
CHANNEL_P = [0.3, 0.2, 0.15, 0.1, 0.1, 0.15]
PAY_METHODS = ["Credit Card", "PayPal", "Debit Card", "Direct Debit", "Gift Card"]
PAY_P = [0.50, 0.18, 0.14, 0.12, 0.06]
PAY_FAIL = {
    "Credit Card": 0.025,
    "PayPal": 0.025,
    "Debit Card": 0.025,
    "Direct Debit": 0.075,
    "Gift Card": 0.025,
}
FAIL_REASON = {
    "Credit Card": "Card declined",
    "PayPal": "Payment method not funded",
    "Debit Card": "Insufficient funds",
    "Direct Debit": "Mandate rejected",
    "Gift Card": "Gift card balance exhausted",
}
OBJECTIVES = ["Awareness", "Consideration", "Conversion", "Brand Launch"]
CPM_BASE = {
    "Awareness": 12.0,
    "Consideration": 18.0,
    "Conversion": 26.0,
    "Brand Launch": 34.0,
}
REFUND_REASON_TEXT = {
    "CHANGED_MIND": "Customer changed mind",
    "DUPLICATE_CHARGE": "Duplicate charge",
    "SERVICE_ISSUE": "Service issue",
    "ANNUAL_CANCEL_WINDOW": "Annual plan cancelled inside refund window",
}


def unique_names(names):
    """Suffix repeated names so each entity has a distinct display name; RNG draws are unchanged."""
    seen = Counter()
    out = []
    for n in names:
        seen[n] += 1
        out.append(n if seen[n] == 1 else f"{n} {seen[n]}")
    return out


def nullable(df):
    return df.astype(object).where(pd.notna(df), None)


def write_table(spark, cat, prefix, schema, table, pdf):
    from pyspark.sql import functions as F

    fqn = f"{cat}.{prefix}{schema}.{table}"
    target = spark.table(fqn).schema
    names = [f.name for f in target]
    missing = set(names) - set(pdf.columns)
    if missing:
        raise RuntimeError(f"{fqn}: missing {missing}")
    sdf = spark.createDataFrame(nullable(pdf[names]))
    sdf = sdf.select([F.col(f.name).cast(f.dataType).alias(f.name) for f in target])
    sdf.write.mode("overwrite").insertInto(fqn)
    print(f"wrote {fqn}: {len(pdf)} rows", flush=True)


def write_manifest(spark, cat, prefix, as_of, seed, sha, table_count, total_rows):
    from pyspark.sql import types as T

    fqn = f"{cat}.{prefix}lab.data_manifest"
    fields = [
        T.StructField("as_of", T.DateType()),
        T.StructField("seed", T.IntegerType()),
        T.StructField("generated_at", T.TimestampType()),
        T.StructField("model_sha", T.StringType()),
        T.StructField("table_count", T.IntegerType()),
        T.StructField("total_rows", T.LongType()),
    ]
    row = (as_of, seed, datetime.now(UTC), sha, table_count, total_rows)
    spark.createDataFrame([row], T.StructType(fields)).write.mode("overwrite").saveAsTable(fqn)
    print(f"wrote {fqn}: {total_rows} rows in {table_count} tables", flush=True)


def pick_covering(r, day, act, term):
    """For each day, pick a subscription row active that day, uniformly over active rows."""
    out = np.full(len(day), -1, dtype=np.int64)
    todo = np.arange(len(day))
    n = len(act)
    for _ in range(400000):
        if todo.size == 0:
            break
        cand = r.integers(0, n, size=todo.size)
        d = day[todo]
        ok = (act[cand] <= d) & ((term[cand] < 0) | (d < term[cand]))
        out[todo[ok]] = cand[ok]
        todo = todo[~ok]
    if todo.size:
        raise RuntimeError(f"{todo.size} days have no active subscription")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--as-of", default=None)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="generate and report only, no Spark writes",
    )
    args = ap.parse_args()
    root = Path(args.root)
    lab = yaml.safe_load((root / "lab.yaml").read_text())["workspace"]
    subset = yaml.safe_load((root / "data_model" / "model_subset.yaml").read_text())
    cat, prefix = lab["catalog"], lab["schema_prefix"]
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today() - timedelta(days=1)
    start = add_months(as_of, -WINDOW_MONTHS)
    A = (as_of - start).days
    print(f"as_of={as_of} window_start={start} window_days={A} seed={SEED}", flush=True)

    out = {}
    base_date = np.datetime64(start, "D")
    base_ts = np.datetime64(start, "s")

    def D(off):
        return base_date + np.asarray(off, dtype=np.int64).astype("timedelta64[D]")

    def TS(sec):
        return base_ts + np.asarray(sec, dtype=np.int64).astype("timedelta64[s]")

    def dser(arr, mask=None):
        s = pd.Series(pd.to_datetime(D(arr)))
        return s.where(mask) if mask is not None else s

    t_inc = (add_months(as_of, -PRICE_UPLIFT_MONTHS) - start).days
    spike_end = (add_months(add_months(as_of, -PRICE_UPLIFT_MONTHS), SPIKE_MONTHS) - start).days

    month_starts = []
    m = 0
    while True:
        d = (add_months(start, m) - start).days
        if d >= A:
            break
        month_starts.append(d)
        m += 1
    bounds = month_starts + [A]
    n_months = len(month_starts)

    # ---------- genre ----------
    r = rng("misc")
    G = len(GENRES)
    out[("content", "genre")] = pd.DataFrame(
        {
            "genre_id": np.arange(1, G + 1),
            "code": [f"GEN-{i:02d}" for i in range(1, G + 1)],
            "name": GENRES,
            "description": [f"{g} anime titles" for g in GENRES],
            "target_demographic": r.choice(["Kids", "Teen", "Adult", "All ages"], G),
            "tier": r.choice(["Core", "Growth", "Niche"], G, p=[0.5, 0.3, 0.2]),
            "is_active": True,
            "parental_guidance_flag": r.random(G) < 0.3,
            "daypart_affinity": r.choice(["Prime", "Late night", "Daytime"], G),
            "syndication_eligibility": r.random(G) < 0.5,
            "effective_start_date": dser(np.zeros(G, dtype=np.int64)),
            "usage_notes": "Anime genre taxonomy used for catalog and ad targeting",
        }
    )

    # ---------- series, seasons, titles, episodes ----------
    r = rng("series")
    NS = 400
    combos = [f"{a} {b}" for a in ADJ for b in NOUN]
    r.shuffle(combos)
    series_title = ["Moonlit Blade", "Moonlit Blade: Second Dawn"] + combos[: NS - 2]
    series_franchise = ["Moonlit Blade", "Moonlit Blade"] + combos[: NS - 2]
    series_genre = r.integers(1, G + 1, NS)
    series_genre[:2] = 1
    series_pre = np.array([add_months(start, -int(x)) for x in r.integers(12, 150, NS)])
    series_status = r.choice(["Ongoing", "Completed"], NS, p=[0.4, 0.6])
    series_type = r.choice(["Television", "OVA", "Web series"], NS, p=[0.85, 0.08, 0.07])
    out[("content", "series")] = pd.DataFrame(
        {
            "series_id": np.arange(1, NS + 1),
            "genre_id": series_genre,
            "franchise_name": series_franchise,
            "title": series_title,
            "series_type": series_type,
            "series_status": series_status,
            "premiere_date": pd.to_datetime(series_pre),
            "finale_date": pd.NaT,
            "total_season_count": 0,
            "total_episode_count": 0,
            "original_network": "TV Tokyo Partner Network",
            "production_company": r.choice(["Kaze Animation", "Nishi Works", "Tsuki Studio", "Akari Pictures"], NS),
            "language_original": "Japanese",
            "country_of_origin": "JP",
        }
    )

    # seasons: every series has season 1; series 1 and 2 (the flagship) have exactly two seasons
    seasons = [(s, 1) for s in range(1, NS + 1)] + [(1, 2), (2, 2)]
    nxt = {s: 1 for s in range(1, NS + 1)}
    nxt[1], nxt[2] = 2, 2
    while len(seasons) < 900:
        s = int(r.integers(3, NS + 1))
        nxt[s] += 1
        seasons.append((s, nxt[s]))
    NSEAS = len(seasons)
    season_series = np.array([s for s, _ in seasons])
    season_num = np.array([k for _, k in seasons])

    # titles 1..900 are episodic (one per season); 901..1200 are films and specials
    NT = 1200
    flag_seasons = [
        seasons.index((1, 1)),
        seasons.index((1, 2)),
        seasons.index((2, 1)),
        seasons.index((2, 2)),
    ]
    title_season = np.full(NT + 1, -1, dtype=np.int64)
    for t, k in zip([5, 8, 9, 10], flag_seasons):  # the four franchise titles sit at ranks 5, 8, 9, 10
        title_season[t] = k
    rest = [i for i in range(NSEAS) if i not in flag_seasons]
    r.shuffle(rest)
    free_titles = [t for t in range(1, 901) if title_season[t] < 0]
    for t, k in zip(free_titles, rest):
        title_season[t] = k

    rs = rng("titles")
    simulcast = np.zeros(NT + 1, dtype=bool)
    simulcast[1:11] = True
    simulcast[rs.choice(np.arange(11, 901), 170, replace=False)] = True

    last_premiere = A - 21 * 7
    season_starts = [
        d
        for d in range(last_premiere + 1)
        if date.fromordinal(start.toordinal() + d).month in (1, 4, 7, 10)
        and date.fromordinal(start.toordinal() + d).day <= 14
    ]
    back_lo = (add_months(start, -150) - start).days
    premiere = np.zeros(NSEAS, dtype=np.int64)
    for t in range(1, 901):
        k = title_season[t]
        if simulcast[t]:
            premiere[k] = season_starts[int(rs.integers(0, len(season_starts)))]
        else:
            premiere[k] = int(rs.integers(back_lo, 0))

    film_series = rs.integers(3, NS + 1, NT - 900)
    t_series = np.zeros(NT, dtype=np.int64)
    t_season_num = np.empty(NT, dtype=object)
    t_name = [""] * NT
    t_type = np.empty(NT, dtype=object)
    t_release = np.zeros(NT, dtype=np.int64)
    t_runtime = np.zeros(NT, dtype=np.int64)
    for t in range(1, NT + 1):
        i = t - 1
        if t <= 900:
            k = title_season[t]
            s = int(season_series[k])
            t_series[i] = s
            t_season_num[i] = int(season_num[k])
            t_type[i] = "Series"
            t_release[i] = premiere[k]
            t_runtime[i] = 1440
            base = series_title[s - 1]
            t_name[i] = f"{base} Season {int(season_num[k])}" if season_num[k] > 1 else base
        else:
            t_series[i] = int(film_series[t - 901])
            t_season_num[i] = None
            t_type[i] = "Film" if t <= 1050 else "Special"
            t_release[i] = int(rs.integers(back_lo, 0))
            t_runtime[i] = int(rs.integers(5400, 7200)) if t_type[i] == "Film" else 1440
            t_name[i] = f"{ADJ[t % len(ADJ)]} {NOUN[t % len(NOUN)]}: The {t_type[i]}"
    t_name[7] = "Moonlit Blade II"
    t_name[8] = "Moonlit Blade: Second Dawn"
    t_name[9] = "Moonlit Blade: Second Dawn II"
    t_name[4] = "Moonlit Blade"
    t_genre = series_genre[t_series - 1]
    out[("content", "title")] = pd.DataFrame(
        {
            "title_id": np.arange(1, NT + 1),
            "series_id": t_series,
            "genre_id": t_genre,
            "name": t_name,
            "content_type": t_type,
            "production_year": D(t_release).astype("datetime64[Y]").astype(np.int64) + 1970,
            "release_date": pd.to_datetime(D(t_release)),
            "runtime_seconds": t_runtime,
            "original_language": "Japanese",
            "content_status": "Active",
            "parental_advisory_flag": rs.random(NT) < 0.15,
            "premiere_flag": rs.random(NT) < 0.08,
            "season_number": t_season_num,
            "country_of_origin": "JP",
            "is_simulcast": simulcast[1:],
        }
    )

    # episodes: contiguous per title, ids start at 1
    re_ = rng("episodes")
    ep = {
        k: []
        for k in [
            "content_episode_id",
            "title_id",
            "content_season_id",
            "content_series_id",
            "episode_number",
            "title",
            "runtime_seconds",
            "air",
            "until",
            "episode_type",
            "episode_status",
            "subtitles_available",
            "video_resolution",
        ]
    }
    ep_idx_start = np.zeros(NT + 1, dtype=np.int64)
    ep_count = np.zeros(NT + 1, dtype=np.int64)
    nid = 1
    for t in range(1, NT + 1):
        i = t - 1
        ep_idx_start[t] = nid
        if t <= 900:
            k = int(title_season[t])
            n_ep = int(re_.integers(12, 20))
            airs = premiere[k] + 7 * np.arange(n_ep)
            season_id, etype = k + 1, "Episode"
        else:
            n_ep = 1
            airs = np.array([t_release[i]])
            season_id, etype = None, "Feature"
        for e in range(n_ep):
            ep["content_episode_id"].append(nid)
            ep["title_id"].append(t)
            ep["content_season_id"].append(season_id)
            ep["content_series_id"].append(int(t_series[i]))
            ep["episode_number"].append(e + 1)
            ep["title"].append(t_name[i])
            ep["runtime_seconds"].append(int(t_runtime[i] + re_.integers(-120, 121)) if t <= 900 else int(t_runtime[i]))
            ep["air"].append(int(airs[e]))
            ep["until"].append(int(airs[e]) + 365 * 3)
            ep["episode_type"].append(etype)
            ep["episode_status"].append("Published")
            ep["subtitles_available"].append(True)
            ep["video_resolution"].append(str(re_.choice(["1080p", "4K", "720p"], p=[0.7, 0.2, 0.1])))
            nid += 1
        ep_count[t] = n_ep
    n_eps = nid - 1
    ep_df = pd.DataFrame(
        {
            "content_episode_id": ep["content_episode_id"],
            "title_id": ep["title_id"],
            "content_season_id": pd.array(ep["content_season_id"], dtype="Int64"),
            "content_series_id": ep["content_series_id"],
            "episode_number": ep["episode_number"],
            "title": ep["title"],
            "runtime_seconds": ep["runtime_seconds"],
            "original_air_date": pd.to_datetime(D(ep["air"])),
            "vod_available_from_date": pd.to_datetime(D(ep["air"])),
            "vod_available_until_date": pd.to_datetime(D(ep["until"])),
            "episode_type": ep["episode_type"],
            "episode_status": ep["episode_status"],
            "subtitles_available": ep["subtitles_available"],
            "video_resolution": ep["video_resolution"],
        }
    )
    out[("content", "content_episode")] = ep_df
    ep_vod = np.array(ep["air"], dtype=np.int64)
    ep_run = np.array(ep["runtime_seconds"], dtype=np.int64)
    ep_series = np.array(ep["content_series_id"], dtype=np.int64)
    ep_season_arr = np.array([-1 if x is None else x for x in ep["content_season_id"]], dtype=np.int64)
    season_ep_count = Counter(x for x in ep_season_arr.tolist() if x > 0)
    series_ep_count = np.bincount(ep_series, minlength=NS + 1)[1:]
    series_season_count = np.bincount(season_series, minlength=NS + 1)[1:]
    out[("content", "series")]["total_season_count"] = series_season_count
    out[("content", "series")]["total_episode_count"] = series_ep_count
    sd = pd.DataFrame(
        {
            "season_id": np.arange(1, NSEAS + 1),
            "series_id": season_series,
            "season_number": season_num,
            "season_status": "Completed",
            "original_air_date": pd.to_datetime(D(premiere)),
            "finale_date": pd.to_datetime(D(premiere + 7 * 15)),
            "episode_count_ordered": [season_ep_count.get(k, 0) for k in range(1, NSEAS + 1)],
            "episode_count_aired": [season_ep_count.get(k, 0) for k in range(1, NSEAS + 1)],
            "production_year": D(premiere).astype("datetime64[Y]").astype(np.int64) + 1970,
            "network_original": "TV Tokyo Partner Network",
            "language_original": "Japanese",
        }
    )
    out[("content", "season")] = sd
    print(
        f"catalog: {NS} series, {NSEAS} seasons, {NT} titles, {n_eps} episodes",
        flush=True,
    )

    # ---------- ott platforms and plans ----------
    plat = []
    for region in ["NA", "LATAM", "EMEA", "APAC"]:
        for kind, label, res in [
            ("WM", "Web and Mobile", "1080p"),
            ("TV", "TV and Console", "4K"),
        ]:
            plat.append(
                {
                    "ott_platform_id": PLATFORM[region][0 if kind == "WM" else 1],
                    "platform_code": f"HS-{region}-{kind}",
                    "platform_name": f"Hoshi Stream {region} {label}",
                    "parent_brand": "Hoshi Stream",
                    "platform_status": "Live",
                    "service_tier": "Standard",
                    "launch_date": date(2019, 4, 1) if region != "LATAM" else date(2020, 9, 15),
                    "billing_currency": "USD",
                    "drm_system": "Widevine, FairPlay, PlayReady",
                    "primary_streaming_protocol": "DASH, HLS",
                    "max_video_resolution": res,
                    "max_concurrent_streams": 4,
                }
            )
    out[("distribution", "ott_platform")] = pd.DataFrame(plat).sort_values("ott_platform_id").reset_index(drop=True)
    out[("subscriber", "subscription_plan")] = pd.DataFrame(
        [
            {
                "subscription_plan_id": pid,
                "plan_code": c,
                "plan_name": n,
                "plan_type": ty,
                "service_tier": tier,
                "base_price": p,
                "currency_code": "USD",
                "ad_supported": ad,
                "contract_term_months": term,
                "trial_duration_days": trial,
                "plan_status": "Active",
                "launch_date": date(2019, 4, 1),
            }
            for pid, (c, n, ty, tier, p, term, trial, ad) in PLANS.items()
        ]
    )

    # ---------- rights and partner reference ----------
    out[("rights", "territory")] = pd.DataFrame(
        [
            {
                "territory_id": i + 1,
                "code": t[0],
                "name": t[2],
                "iso_alpha_2_code": t[0],
                "iso_alpha_3_code": t[1],
                "territory_group": t[3],
                "territory_type": "Country",
                "currency_code": t[4],
                "language_primary": t[5],
                "time_zone": t[6],
                "population": t[7],
            }
            for i, t in enumerate(TERRITORIES)
        ]
    )
    hr = rng("holders")
    holder_names = unique_names(
        ["Tsuki Studios Ltd."] + [f"{a} {b} Co." for a, b in zip(hr.choice(ADJ, 39), hr.choice(NOUN, 39))]
    )
    out[("rights", "holder")] = pd.DataFrame(
        {
            "holder_id": np.arange(1, 41),
            "rights_holder_name": holder_names,
            "rights_holder_code": [f"LIC-{i:03d}" for i in range(1, 41)],
            "rights_holder_status": "Active",
            "entity_type": hr.choice(
                ["Corporation", "Limited company", "Sole proprietor"],
                40,
                p=[0.6, 0.3, 0.1],
            ),
            "territory_of_incorporation": hr.choice(["JP", "US", "GB", "KR"], 40, p=[0.7, 0.1, 0.1, 0.1]),
            "relationship_start_date": dser(hr.integers(-1800, 0, 40)),
            "default_royalty_rate": np.round(hr.uniform(10, 30, 40), 2),
            "payment_terms_days": hr.choice([30, 45, 60], 40),
            "royalty_calculation_method": hr.choice(["Net receipts", "Gross receipts"], 40),
            "preferred_currency": "USD",
            "most_favored_nations_flag": hr.random(40) < 0.25,
        }
    )
    pr = rng("partners")
    out[("partner", "partner")] = pd.DataFrame(
        {
            "partner_id": np.arange(1, 31),
            "code": [f"PTR-{i:03d}" for i in range(1, 31)],
            "name": unique_names([f"{a} {b} Partners" for a, b in zip(pr.choice(ADJ, 30), pr.choice(NOUN, 30))]),
            "partner_type": pr.choice(["Studio", "Distributor", "Broadcaster", "Platform"], 30),
            "subtype": pr.choice(["Anime studio", "Co-production", "Library owner"], 30),
            "relationship_status": "Active",
            "relationship_start_date": dser(pr.integers(-1500, 0, 30)),
            "risk_tier": pr.choice(["Low", "Medium", "High"], 30, p=[0.5, 0.35, 0.15]),
            "strategic_tier": pr.choice(["Strategic", "Core", "Opportunistic"], 30),
            "domicile_country_code": pr.choice(["JP", "US", "KR", "GB"], 30, p=[0.7, 0.1, 0.1, 0.1]),
            "is_exclusive": pr.random(30) < 0.3,
            "content_specialization": pr.choice(["Action", "Romance", "Kids", "Sports", "Mecha"], 30),
        }
    )

    # ---------- subscribers and subscriptions: monthly simulation ----------
    sr = rng("subs")
    NSUB = 50000
    reg_names = list(REGION_SHARE)
    sub_reg_i = sr.choice(len(reg_names), NSUB, p=list(REGION_SHARE.values()))
    sub_region = np.array(reg_names, dtype=object)[sub_reg_i]
    sub_country = np.zeros(NSUB, dtype=np.int64)
    for reg in reg_names:
        idx = np.where(sub_region == reg)[0]
        sub_country[idx] = sr.choice(REGION_RANGE[reg], idx.size, p=COUNTRY_WEIGHTS[reg])
    sub_month = sr.choice(n_months, NSUB)
    sub_method = np.array(PAY_METHODS, dtype=object)[sr.choice(len(PAY_METHODS), NSUB, p=PAY_P)]
    sub_chan = sr.choice(len(CHANNELS), NSUB, p=CHANNEL_P)

    CAP = 300000
    s_sub = np.full(CAP, -1, dtype=np.int64)
    s_plan = np.zeros(CAP, dtype=np.int64)
    s_act = np.zeros(CAP, dtype=np.int64)
    s_term = np.full(CAP, -1, dtype=np.int64)
    s_status = np.full(CAP, "", dtype=object)
    s_reason = np.full(CAP, -1, dtype=np.int64)
    s_promo = np.zeros(CAP, dtype=bool)
    s_chan = np.zeros(CAP, dtype=np.int64)
    n_rows = 0
    lr = rng("churn")

    def new_row(sub, plan, act):
        nonlocal n_rows
        i = n_rows
        s_sub[i], s_plan[i], s_act[i], s_term[i] = sub, plan, act, -1
        s_promo[i] = plan >= 2 and lr.random() < 0.05
        s_chan[i] = sub_chan[sub]
        n_rows += 1

    for mi in range(n_months):
        m_lo, m_hi = bounds[mi], bounds[mi + 1]
        spike = t_inc <= m_lo < spike_end
        for sub in np.where(sub_month == mi)[0]:
            new_row(
                int(sub),
                int(sr.choice(7, p=PLAN_MIX)) + 1,
                int(sr.integers(m_lo, m_hi)),
            )
        elig = np.where((s_term[:n_rows] < 0) & (s_act[:n_rows] < m_lo))[0]
        if elig.size == 0:
            continue
        plans = s_plan[elig]
        kinds = np.where(plans == 1, "free", np.where(plans >= 5, "annual", "monthly"))
        h = np.array([BASE_HAZARD[k] for k in kinds])
        latam = sub_region[s_sub[elig]] == "LATAM"
        h = np.where(latam & spike, h * SPIKE_MULT, h)
        churn = lr.random(elig.size) < h
        for ridx in elig[churn]:
            s_term[ridx] = int(lr.integers(max(m_lo, s_act[ridx] + 1), m_hi))
            s_status[ridx] = "Cancelled"
            if sub_region[s_sub[ridx]] == "LATAM" and spike and lr.random() < 0.7:
                s_reason[ridx] = 0  # price
            else:
                s_reason[ridx] = int(lr.choice(6, p=REASON_P))
        kept = elig[~churn]
        for ridx in kept[lr.random(kept.size) < SWITCH_P]:
            s_term[ridx] = int(lr.integers(max(m_lo, s_act[ridx] + 1), m_hi))
            s_status[ridx] = "Superseded"
            newp = int(lr.choice(6, p=SWITCH_MIX)) + 2
            if newp == s_plan[ridx]:
                newp = 2 if newp != 2 else 3
            new_row(int(s_sub[ridx]), newp, int(s_term[ridx]))
    s_status[:n_rows][s_term[:n_rows] < 0] = "Active"

    R = slice(0, n_rows)
    sub_s, plan_s, act_s, term_s = s_sub[R], s_plan[R], s_act[R], s_term[R]
    status_s = s_status[R]
    region_s = sub_region[sub_s]
    latam_s = region_s == "LATAM"
    base_s = np.array([PLANS[p][4] for p in plan_s])
    new_s = np.array([LATAM_NEW_PRICE.get(int(p), PLANS[int(p)][4]) for p in plan_s])
    rate_s = np.where(latam_s & ((term_s < 0) | (term_s >= t_inc)), new_s, base_s)
    subtype_s = np.where(plan_s == 1, "Free", np.where(plan_s >= 5, "Annual", "Monthly"))
    period_s = np.where(plan_s >= 5, 365, 30)
    ref_end = np.minimum(np.where(term_s >= 0, term_s, A), A)
    cur_start = act_s + period_s * np.maximum(0, (ref_end - 1 - act_s) // period_s)
    cur_end = cur_start + period_s - 1
    cur_end = np.where(term_s >= 0, np.minimum(cur_end, term_s), cur_end)
    subs_df = pd.DataFrame(
        {
            "subscription_id": np.arange(1, n_rows + 1),
            "subscriber_id": sub_s + 1,
            "subscription_plan_id": plan_s,
            "subscription_number": [f"HS-SUB-{i:07d}" for i in range(1, n_rows + 1)],
            "subscription_status": status_s,
            "subscription_type": subtype_s,
            "activation_date": dser(act_s),
            "current_term_start_date": dser(cur_start),
            "current_term_end_date": dser(cur_end),
            "termination_date": dser(np.maximum(term_s, 0), term_s >= 0),
            "base_rate_amount": np.round(rate_s, 2),
            "currency_code": "USD",
            "auto_renew_flag": (plan_s >= 2) & (term_s < 0),
            "promotional_rate_flag": s_promo[R],
            "acquisition_channel": np.array(CHANNELS, dtype=object)[s_chan[R]],
        }
    )
    out[("subscriber", "subscription")] = subs_df

    first_act = np.full(NSUB, 10**9, dtype=np.int64)
    np.minimum.at(first_act, sub_s, act_s)
    order = np.argsort(act_s, kind="stable")
    last_plan = np.zeros(NSUB, dtype=np.int64)
    last_plan[sub_s[order]] = plan_s[order]
    has_active = np.zeros(NSUB, dtype=bool)
    has_active[sub_s[status_s == "Active"]] = True
    subscriber_df = pd.DataFrame(
        {
            "subscriber_id": np.arange(1, NSUB + 1),
            "territory_id": sub_country + 1,
            "country_code": [TERRITORIES[c][0] for c in sub_country],
            "preferred_language": [TERRITORIES[c][5] for c in sub_country],
            "account_status": np.where(has_active, "Active", "Cancelled"),
            "service_tier": [PLANS[int(p)][3] for p in last_plan],
            "registration_source": sr.choice(
                ["Web", "iOS app", "Android app", "Smart TV", "Partner bundle"],
                NSUB,
                p=[0.3, 0.2, 0.2, 0.15, 0.15],
            ),
            "registration_timestamp": pd.Series(TS(first_act * 86400 - sr.integers(0, 14 * 86400, NSUB))),
            "billing_cycle": np.where(
                last_plan == 1,
                "Not billed",
                np.where(last_plan >= 5, "Annual", "Monthly"),
            ),
            "marketing_opt_in": sr.random(NSUB) < 0.6,
            "total_viewing_hours": 0.0,
            "ltv": 0.0,
            "arpu": 0.0,
            "last_viewing_timestamp": None,
        }
    )

    out[("subscriber", "subscriber")] = subscriber_df

    # ---------- playback sessions ----------
    pr_ = rng("sessions")
    NSESS = 2000000
    top_shares = [0.058, 0.052, 0.045, 0.040, 0.034, 0.034, 0.031, 0.025, 0.018, 0.013]
    flag_ranks = {5: 0.034, 8: 0.025, 9: 0.018, 10: 0.013}
    assert abs(sum(flag_ranks.values()) - 0.090) < 1e-9
    tail = np.array([1.0 / (k + 20) for k in range(1, NT - 10 + 1)])
    tail = tail / tail.sum() * (1 - sum(top_shares))
    share = np.concatenate([top_shares, tail])
    assert abs(share.sum() - 1) < 1e-9
    # share is a watch-time share: sessions per title scale with share / mean runtime
    rt_sum = np.bincount(np.asarray(ep["title_id"]), weights=ep_run, minlength=NT + 1)[1:]
    rt_mean = rt_sum / ep_count[1:]
    sess_w = share / rt_mean
    n_per = np.floor(sess_w / sess_w.sum() * NSESS).astype(np.int64)
    n_per[0] += NSESS - n_per.sum()
    title_of = np.repeat(np.arange(1, NT + 1), n_per)
    n_real = title_of.size
    ep_pick = ep_idx_start[title_of] + np.floor(pr_.random(n_real) * ep_count[title_of]).astype(np.int64)
    sim = simulcast[title_of]
    air_of = ep_vod[ep_pick - 1]
    off_sim = np.where(
        pr_.random(n_real) < 0.85,
        pr_.exponential(2.0, n_real),
        pr_.uniform(7.0, 60.0, n_real),
    )
    days = np.arange(A)
    wday = np.array(
        [
            1.6
            if (
                date.fromordinal(start.toordinal() + int(d)).month in (1, 4, 7, 10)
                and date.fromordinal(start.toordinal() + int(d)).day <= 21
            )
            else 0.85
            for d in days
        ]
    )
    t_back = pr_.choice(days, size=n_real, p=wday / wday.sum()).astype(np.float64)
    t_day = np.where(sim, air_of + off_sim, t_back)
    t_day = np.where(t_day >= A, A - pr_.random(n_real), t_day)
    t_sec = np.floor(t_day * 86400 + pr_.random(n_real) * 86400)
    t_sec = np.minimum(t_sec, A * 86400 - 1).astype(np.int64)
    srt = np.argsort(t_sec, kind="stable")
    t_sec, ep_pick, title_of = t_sec[srt], ep_pick[srt], title_of[srt]
    day_of = t_sec // 86400
    sess_row = pick_covering(pr_, day_of, act_s, term_s)
    sess_sub = sub_s[sess_row]
    plan_of = plan_s[sess_row]
    reg_of = sub_region[sess_sub]
    ctry_of = sub_country[sess_sub]

    complete = pr_.beta(4.0, 1.2, n_real)
    error = pr_.random(n_real) < 0.004
    complete = np.where(error, complete * 0.2, complete)
    runtime = ep_run[ep_pick - 1]
    watch = np.floor(complete * runtime).astype(np.int64)
    ad_breaks = np.where(plan_of == 1, pr_.integers(2, 5, n_real), 0)
    end_sec = t_sec + watch + ad_breaks * 45 + 10
    tv = pr_.random(n_real) < 0.45
    plat_id = np.where(
        tv,
        np.array([PLATFORM[g][1] for g in reg_of]),
        np.array([PLATFORM[g][0] for g in reg_of]),
    )
    ptype = np.where(
        tv,
        pr_.choice(["Smart TV", "Console"], n_real),
        pr_.choice(["Mobile", "Web browser", "Tablet"], n_real),
    )
    res = np.where(
        plan_of >= 4,
        np.where(pr_.random(n_real) < 0.5, "4K", "1080p"),
        np.where(pr_.random(n_real) < 0.6, "1080p", "720p"),
    )

    # audio and subtitle language by region (Story 4)
    u = pr_.random(n_real)
    audio = np.empty(n_real, dtype=object)
    subs_lang = np.empty(n_real, dtype=object)
    for reg in reg_names:
        m_ = reg_of == reg
        x, c = u[m_], ctry_of[m_]
        if reg == "NA":
            dub = x < 0.62
            a = np.where(dub, "English", "Japanese")
            s_ = np.where(dub, None, "English")
        elif reg == "LATAM":
            is_br = c == TER_BR
            dub = x < 0.58
            a = np.where(dub, np.where(is_br, "Portuguese", "Spanish"), "Japanese")
            s_ = np.where(dub, None, np.where(is_br, "Portuguese", "Spanish"))
        elif reg == "EMEA":
            local = np.array([TERRITORIES[k][5] for k in c], dtype=object)
            a = np.where(x < 0.30, "English", np.where(x < 0.42, local, "Japanese"))
            s_ = np.where(a == "Japanese", "English", None)
        else:
            dub = x < 0.15
            a = np.where(dub, "English", "Japanese")
            s_ = np.where(dub, None, np.where(c == TER_KR, "Korean", "English"))
        audio[m_] = a
        subs_lang[m_] = s_
    exit_reason = np.where(error, "Error", np.where(complete >= 0.9, "Finished", "Stopped"))

    sess_id = np.arange(1, n_real + 1)
    sessions_df = pd.DataFrame(
        {
            "playback_session_id": sess_id,
            "subscriber_id": sess_sub + 1,
            "ott_platform_id": plat_id,
            "content_episode_id": ep_pick,
            "session_start_timestamp": pd.to_datetime(TS(t_sec)),
            "session_end_timestamp": pd.to_datetime(TS(end_sec)),
            "total_watch_duration_seconds": watch,
            "content_duration_seconds": runtime,
            "completion_percentage": np.round(complete * 100, 2),
            "platform_type": ptype,
            "video_resolution": res,
            "playback_mode": np.where(pr_.random(n_real) < 0.95, "Streaming", "Download"),
            "ad_breaks_served_count": ad_breaks,
            "audio_language": audio,
            "subtitle_language": subs_lang,
            "exit_reason": exit_reason,
        }
    )
    out[("distribution", "playback_session")] = sessions_df
    print(f"sessions: {n_real}", flush=True)

    agg = pd.DataFrame({"s": sess_sub + 1, "w": watch, "t": t_sec})
    hours = (agg.groupby("s")["w"].sum() / 3600.0).reindex(subscriber_df["subscriber_id"]).fillna(0).round(2)
    subscriber_df["total_viewing_hours"] = hours.values
    lastv = agg.groupby("s")["t"].max().reindex(subscriber_df["subscriber_id"]).values
    subscriber_df["last_viewing_timestamp"] = pd.Series(TS(np.nan_to_num(lastv))).where(~np.isnan(lastv))

    # ---------- ad impressions and campaigns (Story 7) ----------
    ir = rng("impressions")
    free_idx = np.where(ad_breaks > 0)[0]
    free_start = t_sec[free_idx]
    NC, NADV, BIG = 900, 150, 1
    camp_adv = np.concatenate([np.full(30, BIG), ir.integers(2, NADV + 1, NC - 30)])
    camp_big = camp_adv == BIG
    camp_type = ir.choice(OBJECTIVES, NC, p=[0.3, 0.3, 0.25, 0.15])
    camp_cpm = np.array([CPM_BASE[x] for x in camp_type])
    camp_start = ir.integers(0, A - 60, NC)
    camp_end = np.minimum(camp_start + ir.integers(30, 151, NC), A - 1)
    size_w = np.exp(ir.normal(0, 0.6, NC)) * np.where(camp_big, 3.0, 1.0)
    D_c = np.maximum(50, np.round(300000 * size_w / size_w.sum())).astype(np.int64)
    ratio = np.where(camp_big, 0.70, ir.uniform(0.92, 1.06, NC))
    target_c = np.round(D_c / ratio).astype(np.int64)
    imp_sess = []
    for c in range(NC):
        lo = np.searchsorted(free_start, camp_start[c] * 86400)
        hi = np.searchsorted(free_start, (camp_end[c] + 1) * 86400)
        if hi <= lo:
            raise RuntimeError(f"campaign {c + 1} has no free-tier sessions in its flight")
        imp_sess.append(free_idx[ir.integers(lo, hi, D_c[c])])
    imp_sess = np.concatenate(imp_sess)
    imp_camp = np.repeat(np.arange(1, NC + 1), D_c)
    NI = imp_sess.size
    ins = ir.choice(["Pre-roll", "Mid-roll", "Post-roll"], NI, p=[0.2, 0.7, 0.1])
    cpm_real = camp_cpm[imp_camp - 1] * ir.uniform(0.92, 1.08, NI)
    out[("sales", "impression_delivery")] = pd.DataFrame(
        {
            "impression_delivery_id": np.arange(1, NI + 1),
            "campaign_id": imp_camp,
            "content_episode_id": ep_pick[imp_sess],
            "playback_session_id": sess_id[imp_sess],
            "subscriber_id": sess_sub[imp_sess] + 1,
            "delivery_date": pd.to_datetime(D(t_sec[imp_sess] // 86400)),
            "delivery_timestamp": pd.to_datetime(TS(t_sec[imp_sess] + ir.integers(60, 600, NI))),
            "insertion_type": ins,
            "ad_pod_position": ir.integers(1, 5, NI),
            "total_impressions_served": 1,
            "viewable_impressions": (ir.random(NI) < 0.72).astype(np.int64),
            "completed_views": (ir.random(NI) < np.where(ins == "Pre-roll", 0.9, 0.7)).astype(np.int64),
            "cpm_realized": np.round(cpm_real, 4),
            "revenue_amount": np.round(cpm_real / 1000.0, 2),
            "currency_code": "USD",
            "verification_status": np.where(ir.random(NI) < 0.9, "Verified", "Unverified"),
        }
    )

    ar = rng("advertisers")
    adv_names = [f"{a} {b}" for a, b in zip(ar.choice(ADJ, NADV), ar.choice(NOUN, NADV))]
    adv_names = unique_names(adv_names)
    adv_names[BIG - 1] = "Larkspur Motors"
    out[("sales", "advertiser")] = pd.DataFrame(
        {
            "advertiser_id": np.arange(1, NADV + 1),
            "legal_name": [f"{n} Inc." for n in adv_names],
            "trade_name": adv_names,
            "industry_category": ar.choice(
                [
                    "Automotive",
                    "Retail",
                    "Telecom",
                    "Finance",
                    "Food and beverage",
                    "Gaming",
                ],
                NADV,
            ),
            "account_status": "Active",
            "annual_spend_tier": np.where(
                np.arange(1, NADV + 1) == BIG,
                "Tier 1",
                ar.choice(["Tier 2", "Tier 3"], NADV),
            ),
            "credit_status": "Good standing",
            "contract_start_date": dser(ar.integers(0, A // 2, NADV)),
            "contract_end_date": pd.NaT,
            "is_political_advertiser": False,
            "payment_terms": "Net 30",
            "preferred_currency_code": "USD",
            "billing_country_code": "US",
        }
    )
    camp_status = np.where(camp_end < A - 1, "Completed", "Live")
    out[("sales", "campaign")] = pd.DataFrame(
        {
            "campaign_id": np.arange(1, NC + 1),
            "advertiser_id": camp_adv,
            "series_id": ar.integers(1, NS + 1, NC),
            "code": [f"CMP-{i:04d}" for i in range(1, NC + 1)],
            "name": [f"{adv_names[a - 1]} {t} {i}" for i, (a, t) in enumerate(zip(camp_adv, camp_type), 1)],
            "campaign_type": camp_type,
            "campaign_status": camp_status,
            "start_date": dser(camp_start),
            "end_date": dser(camp_end),
            "currency_code": "USD",
            "total_budget_amount": np.round(target_c * camp_cpm / 1000.0, 2),
            "target_cpm": camp_cpm,
            "target_impressions": target_c,
            "priority_level": ar.choice(["High", "Medium", "Low"], NC),
            "product_brand": [adv_names[a - 1] for a in camp_adv],
        }
    )
    orders = []
    oid = 1
    for c in range(NC):
        k = int(ar.choice([2, 3, 4], p=[0.4, 0.4, 0.2]))
        shares = ar.dirichlet(np.ones(k))
        for j in range(k):
            tgt = max(1, round(target_c[c] * shares[j]))
            orders.append(
                {
                    "ad_order_id": oid,
                    "advertiser_id": int(camp_adv[c]),
                    "campaign_id": c + 1,
                    "ott_platform_id": int(ar.integers(1, 9)),
                    "order_number": f"ORD-{oid:06d}",
                    "order_type": str(ar.choice(["Direct", "Programmatic", "Upfront"], p=[0.5, 0.35, 0.15])),
                    "order_status": camp_status[c] if camp_status[c] == "Completed" else "Live",
                    "flight_start_date": pd.Timestamp(D(camp_start[c])),
                    "flight_end_date": pd.Timestamp(D(camp_end[c])),
                    "currency_code": "USD",
                    "contracted_cpm": float(camp_cpm[c]),
                    "total_contracted_value": round(tgt * camp_cpm[c] / 1000.0, 2),
                    "net_order_value": round(tgt * camp_cpm[c] / 1000.0 * 0.85, 2),
                    "payment_terms": "Net 30",
                }
            )
            oid += 1
    out[("sales", "ad_order")] = pd.DataFrame(orders)

    # ---------- acquisition deals and minimum guarantees (Story 8) ----------
    dr = rng("deals")
    ND = 300
    deal_start = dr.integers(-1200, A, ND)
    deal_term = dr.integers(730, 1460, ND)
    mg_amt = np.round(np.exp(dr.normal(12.2, 0.8, ND)), 2)
    out[("partner", "acquisition_deal")] = pd.DataFrame(
        {
            "acquisition_deal_id": np.arange(1, ND + 1),
            "partner_id": dr.integers(1, 31, ND),
            "deal_number": [f"ACQ-{i:05d}" for i in range(1, ND + 1)],
            "deal_title": [f"Library deal {i}" for i in range(1, ND + 1)],
            "deal_type": dr.choice(
                ["Library acquisition", "Output deal", "Co-production"],
                ND,
                p=[0.5, 0.3, 0.2],
            ),
            "deal_status": np.where(deal_start + deal_term > A, "Active", "Expired"),
            "deal_effective_date": dser(deal_start),
            "deal_expiration_date": dser(deal_start + deal_term),
            "deal_value_amount": np.round(mg_amt * 1.2, 2),
            "minimum_guarantee_amount": mg_amt,
            "currency_code": "USD",
            "exclusivity_flag": dr.random(ND) < 0.4,
            "territory_coverage": dr.choice(
                ["Worldwide", "NA", "LATAM", "EMEA", "APAC"],
                ND,
                p=[0.3, 0.15, 0.15, 0.2, 0.2],
            ),
            "revenue_share_percentage": np.round(dr.uniform(10, 30, ND), 2),
        }
    )
    mr = rng("mgs")
    unrec = np.zeros(ND, dtype=bool)
    unrec[mr.permutation(ND)[:60]] = True  # exactly 60 of 300 (20 percent) are not recouped
    rec_frac = np.where(unrec, mr.uniform(0.15, 0.8, ND), 1.0)
    rec_amt = np.round(mg_amt * rec_frac, 2)
    fully = dser(np.minimum(deal_start + 365, A - 1), ~unrec)
    out[("partner", "minimum_guarantee")] = pd.DataFrame(
        {
            "minimum_guarantee_id": np.arange(1, ND + 1),
            "acquisition_deal_id": np.arange(1, ND + 1),
            "mg_number": [f"MG-{i:05d}" for i in range(1, ND + 1)],
            "mg_type": np.where(mr.random(ND) < 0.6, "Recoupable", "Non-returnable"),
            "mg_status": np.where(unrec, "Recouping", "Recouped"),
            "mg_amount": mg_amt,
            "currency_code": "USD",
            "recouped_to_date_amount": rec_amt,
            "outstanding_balance_amount": np.round(mg_amt - rec_amt, 2),
            "recoupment_percentage": 100.0,
            "is_recoupable": True,
            "effective_start_date": dser(deal_start),
            "effective_end_date": dser(deal_start + deal_term),
            "fully_recouped_date": fully,
            "overage_royalty_rate": np.round(mr.uniform(10, 25, ND), 2),
        }
    )

    # ---------- license agreements (Story 6) ----------
    lr2 = rng("licenses")
    NL = 600
    lic_holder = lr2.integers(2, 41, NL)
    expiry = np.zeros(NL, dtype=np.int64)
    lic_holder[:15] = 1  # one licensor holds a third of the 45 expiring agreements
    expiry[:45] = A + lr2.integers(1, 90, 45)  # expire within 90 days after as-of
    expiry[45:345] = lr2.integers(0, A, 300)
    expiry[345:] = A + 90 + lr2.integers(1, 1200, NL - 345)
    eff = expiry - lr2.integers(730, 1825, NL)
    out[("rights", "license_agreement")] = pd.DataFrame(
        {
            "license_agreement_id": np.arange(1, NL + 1),
            "primary_license_holder_id": lic_holder,
            "acquisition_deal_id": (np.arange(NL) % ND) + 1,
            "agreement_number": [f"LA-{i:05d}" for i in range(1, NL + 1)],
            "agreement_type": lr2.choice(["Licensing", "Output deal", "Sublicense"], NL, p=[0.7, 0.2, 0.1]),
            "agreement_status": np.where(expiry < A, "Expired", "Active"),
            "effective_date": dser(eff),
            "expiry_date": dser(expiry),
            "signed_date": dser(eff - 30),
            "territory_scope": lr2.choice(
                ["Worldwide", "NA", "LATAM", "EMEA", "APAC"],
                NL,
                p=[0.3, 0.15, 0.15, 0.2, 0.2],
            ),
            "exclusivity_flag": lr2.random(NL) < 0.5,
            "minimum_guarantee_amount": np.round(np.exp(lr2.normal(11.5, 0.9, NL)), 2),
            "total_license_fee": np.round(np.exp(lr2.normal(12.5, 0.9, NL)), 2),
            "royalty_percentage": np.round(lr2.uniform(12, 30, NL), 2),
            "currency_code": "USD",
            "windowing_strategy": lr2.choice(["SVOD first", "AVOD first", "Simulcast"], NL, p=[0.5, 0.3, 0.2]),
        }
    )

    # royalty statements: quarterly per agreement while in force; 7 percent of past-due statements are overdue
    sr2 = rng("statements")
    rows_s = []
    for li in range(NL):
        last = min(int(expiry[li]), A)
        q = int(eff[li])
        while q + 90 <= last:
            q_end = q + 89
            due = q_end + 45
            if due < A:
                st = "Overdue" if sr2.random() < 0.07 else "Paid"
            else:
                st = "Pending" if q_end + 20 >= A else "Issued"
            gross = round(float(np.exp(sr2.normal(9.5, 0.8)) * sr2.uniform(0.9, 1.1)), 2)
            wht = round(gross * 0.10, 2)
            rows_s.append(
                {
                    "holder_id": int(lic_holder[li]),
                    "license_agreement_id": li + 1,
                    "statement_period_start_date": q,
                    "statement_period_end_date": q_end,
                    "statement_due_date": due,
                    "statement_issue_date": min(q_end + 20, A - 1),
                    "statement_status": st,
                    "gross": gross,
                    "wht": wht,
                    "paid": (due - int(sr2.integers(0, 20))) if st == "Paid" else None,
                }
            )
            q += 91
    rsd = pd.DataFrame(rows_s)
    rsd.insert(0, "royalty_statement_id", np.arange(1, len(rsd) + 1))
    rsd.insert(3, "statement_number", [f"RS-{i:06d}" for i in range(1, len(rsd) + 1)])
    rsd["statement_frequency"] = "Quarterly"
    rsd["currency_code"] = "USD"
    rsd["gross_royalty_amount"] = rsd.pop("gross")
    rsd["withholding_tax_amount"] = rsd.pop("wht")
    rsd["net_royalty_amount"] = (rsd["gross_royalty_amount"] - rsd["withholding_tax_amount"]).round(2)
    paid_days = rsd.pop("paid")
    for c in [
        "statement_period_start_date",
        "statement_period_end_date",
        "statement_due_date",
        "statement_issue_date",
    ]:
        rsd[c] = dser(rsd[c].values)
    rsd["paid_timestamp"] = pd.Series(TS(np.nan_to_num(paid_days.astype(float).values) * 86400)).where(
        paid_days.notna().values
    )
    out[("rights", "royalty_statement")] = rsd

    # content windows: top 10 titles cover all 22 served countries with three planted gaps (Story 6)
    wr = rng("windows")
    gaps = {(1, TER_BR), (1, TER_MX), (5, TER_PH)}
    win = []
    for t in range(1, 11):
        for ti in range(22):
            if (t, ti) in gaps:
                win.append((t, ti, A - 120, A - 30))
            else:
                win.append((t, ti, A - 700, A + 400))
    while len(win) < 3000:
        t = int(wr.integers(11, NT + 1))
        ti = int(wr.integers(0, len(TERRITORIES)))
        op = int(wr.integers(-400, A + 200))
        win.append((t, ti, op, op + int(wr.integers(180, 900))))
    W = pd.DataFrame(win, columns=["title_id", "terr", "op", "cl"])
    W["active"] = (W["op"] <= A - 1) & (W["cl"] >= A - 1)
    W["status"] = np.where(W["active"], "Active", np.where(W["cl"] < A - 1, "Expired", "Scheduled"))
    W["ott"] = [
        PLATFORM[TERRITORIES[ti][3]][0 if wr.random() < 0.6 else 1]
        if TERRITORIES[ti][3] in PLATFORM
        else int(wr.integers(1, 9))
        for ti in W["terr"]
    ]
    out[("rights", "content_window")] = pd.DataFrame(
        {
            "content_window_id": np.arange(1, len(W) + 1),
            "title_id": W["title_id"].values,
            "ott_platform_id": W["ott"].values,
            "territory_id": W["terr"].values + 1,
            "window_type": wr.choice(["SVOD", "AVOD", "TVOD"], len(W), p=[0.6, 0.3, 0.1]),
            "window_open_date": dser(W["op"].values),
            "window_close_date": dser(W["cl"].values),
            "availability_status": W["status"].values,
            "active_flag": W["active"].values,
            "exclusivity_tier": wr.choice(["Exclusive", "Non-exclusive"], len(W), p=[0.4, 0.6]),
            "license_fee_amount": np.round(np.exp(wr.normal(10.5, 1.0, len(W))), 2),
            "license_fee_currency": "USD",
            "blackout_flag": wr.random(len(W)) < 0.03,
            "window_priority": wr.integers(1, 4, len(W)),
        }
    )

    # ---------- talent (off limits) ----------
    tr = rng("talent")
    NTAL = 2000
    out[("talent", "talent_profile")] = pd.DataFrame(
        {
            "talent_profile_id": np.arange(1, NTAL + 1),
            "stage_name": [f"{a} {b}" for a, b in zip(tr.choice(ADJ, NTAL), tr.choice(NOUN, NTAL))],
            "talent_type": tr.choice(["Voice actor", "Director", "Writer", "Animator", "Composer"], NTAL),
            "talent_tier": tr.choice(["A", "B", "C"], NTAL, p=[0.15, 0.45, 0.4]),
            "union_affiliation": tr.choice(["SAG-AFTRA", "WGA", "DGA", "None"], NTAL, p=[0.3, 0.2, 0.1, 0.4]),
            "nationality": tr.choice(
                ["Japan", "United States", "South Korea", "United Kingdom"],
                NTAL,
                p=[0.6, 0.2, 0.1, 0.1],
            ),
            "primary_language": tr.choice(["Japanese", "English", "Korean"], NTAL, p=[0.6, 0.3, 0.1]),
            "profile_status": tr.choice(["Active", "Inactive"], NTAL, p=[0.85, 0.15]),
            "clearance_status": tr.choice(["Cleared", "Pending"], NTAL, p=[0.9, 0.1]),
            "residual_eligibility_flag": tr.random(NTAL) < 0.7,
            "work_authorization_status": "Authorized",
            "gdpr_consent_status": "Not applicable",
        }
    )
    NCON = 3000
    con_start = tr.integers(-1000, A, NCON)
    con_base = np.round(np.exp(tr.normal(11.0, 0.7, NCON)), 2)
    out[("talent", "contract")] = pd.DataFrame(
        {
            "contract_id": np.arange(1, NCON + 1),
            "talent_profile_id": tr.integers(1, NTAL + 1, NCON),
            "contract_number": [f"TC-{i:06d}" for i in range(1, NCON + 1)],
            "contract_type": tr.choice(
                ["Voice-over agreement", "Writing agreement", "Direction agreement"],
                NCON,
            ),
            "contract_status": np.where(con_start + 365 > A, "Active", "Completed"),
            "engagement_role": tr.choice(
                ["Lead voice", "Supporting voice", "Series director", "Episode writer"],
                NCON,
            ),
            "effective_start_date": dser(con_start),
            "effective_end_date": dser(con_start + 365),
            "base_compensation_amount": con_base,
            "compensation_currency": "USD",
            "backend_participation_percentage": np.round(tr.uniform(0, 5, NCON), 2),
            "guild_affiliation": tr.choice(["SAG-AFTRA", "WGA", "DGA", "None"], NCON),
            "exclusivity_flag": tr.random(NCON) < 0.3,
            "pay_or_play_flag": tr.random(NCON) < 0.5,
            "option_exercise_status": tr.choice(["Exercised", "Pending", "Not applicable"], NCON),
            "governing_cba": "SAG-AFTRA TV/Theatrical",
        }
    )
    out[("talent", "compensation_structure")] = pd.DataFrame(
        {
            "compensation_structure_id": np.arange(1, NCON + 1),
            "contract_id": np.arange(1, NCON + 1),
            "structure_name": tr.choice(["Per-episode fee", "Weekly guarantee", "Flat fee"], NCON),
            "structure_status": "Active",
            "compensation_type": tr.choice(["Episode fee", "Weekly", "Flat"], NCON),
            "base_episode_fee": np.round(con_base * 0.02, 2),
            "daily_rate": np.round(con_base / 40, 2),
            "weekly_guarantee": np.round(con_base / 6, 2),
            "bonus_amount": np.round(con_base * tr.uniform(0, 0.1, NCON), 2),
            "deferred_compensation_amount": np.round(con_base * tr.uniform(0, 0.2, NCON), 2),
            "currency_code": "USD",
            "overtime_multiplier": 1.5,
            "residual_eligibility_flag": tr.random(NCON) < 0.7,
            "effective_start_date": dser(con_start),
        }
    )

    # ---------- offers and redemptions ----------
    orr = rng("offers")
    offer_kinds = ["Discount", "Free trial", "Win-back", "Bundle"]
    offers, offer_start = [], []
    for oi in range(1, 21):
        st_ = int(orr.integers(0, A - 120))
        kind = offer_kinds[oi % 4]
        offer_start.append(st_)
        offers.append(
            {
                "offer_id": oi,
                "ott_platform_id": int(orr.integers(1, 9)),
                "code": f"OFR-{oi:03d}",
                "name": f"{kind} offer {oi}",
                "offer_type": kind,
                "offer_status": "Active" if st_ + 90 >= A - 1 else "Expired",
                "discount_percentage": {
                    "Discount": 25.0,
                    "Free trial": None,
                    "Win-back": 50.0,
                    "Bundle": None,
                }[kind],
                "discount_amount": None,
                "price_amount": None,
                "effective_start_date": pd.Timestamp(D(st_)),
                "effective_end_date": pd.Timestamp(D(st_ + 90)),
                "trial_duration_days": 14 if kind == "Free trial" else None,
            }
        )
    out[("subscriber", "offer")] = pd.DataFrame(offers)
    NR = 12000
    off_pick = orr.integers(1, 21, NR)
    ts_day = np.clip(
        np.array([offer_start[o - 1] for o in off_pick]) + orr.integers(0, 90, NR),
        0,
        A - 1,
    )
    ts_sec = ts_day * 86400 + orr.integers(0, 86400, NR)
    rsub = pick_covering(orr, ts_day, act_s, term_s)
    disc_pct = np.array([o["discount_percentage"] or 0.0 for o in offers])
    applied = np.round(
        np.array([PLANS[int(p)][4] for p in plan_s[rsub]]) * disc_pct[off_pick - 1] / 100.0,
        2,
    )
    out[("subscriber", "offer_redemption")] = pd.DataFrame(
        {
            "offer_redemption_id": np.arange(1, NR + 1),
            "offer_id": off_pick,
            "subscriber_id": sub_s[rsub] + 1,
            "subscription_id": rsub + 1,
            "resulting_subscription_plan_id": plan_s[rsub],
            "redemption_timestamp": pd.to_datetime(TS(ts_sec)),
            "redemption_channel": orr.choice(["Web", "App", "Partner", "Customer care"], NR, p=[0.4, 0.35, 0.15, 0.1]),
            "redemption_status": orr.choice(["Applied", "Expired", "Reversed"], NR, p=[0.85, 0.08, 0.07]),
            "discount_type": np.array([o["offer_type"] for o in offers], dtype=object)[off_pick - 1],
            "applied_discount_amount": applied,
            "discount_duration_months": orr.integers(0, 4, NR),
            "first_time_subscriber_flag": orr.random(NR) < 0.6,
            "revenue_impact_amount": -applied,
        }
    )

    # ---------- invoices, payments, refunds (Story 5) ----------
    ir2 = rng("invoices")
    paid_rows = np.where(plan_s >= 2)[0]
    p_per = np.where(plan_s[paid_rows] >= 5, 365, 30)
    end_eff = np.where(term_s[paid_rows] >= 0, term_s[paid_rows], A)
    n_per_sub = np.maximum(0, -(-(end_eff - act_s[paid_rows]) // p_per))
    NINV = int(n_per_sub.sum())
    rows_rep = np.repeat(paid_rows, n_per_sub)
    k_idx = np.arange(NINV) - np.repeat(np.cumsum(n_per_sub) - n_per_sub, n_per_sub)
    per_rep = np.repeat(p_per, n_per_sub)
    inv_start = act_s[rows_rep] + per_rep * k_idx
    lat = sub_region[sub_s[rows_rep]] == "LATAM"
    plan_rep = plan_s[rows_rep]
    old_p = np.array([PLANS[int(p)][4] for p in plan_rep])
    new_p = np.array([LATAM_NEW_PRICE.get(int(p), PLANS[int(p)][4]) for p in plan_rep])
    subtotal = np.round(np.where(lat & (inv_start >= t_inc), new_p, old_p), 2)
    promo = s_promo[rows_rep] & (k_idx == 0)
    discount = np.where(promo, np.round(subtotal * 0.5, 2), 0.0)
    region_inv = sub_region[sub_s[rows_rep]]
    tax = np.round((subtotal - discount) * np.array([TAX[g] for g in region_inv]), 2)
    total = np.round(subtotal - discount + tax, 2)
    method_inv = sub_method[sub_s[rows_rep]]
    failed = ir2.random(NINV) < np.array([PAY_FAIL[m] for m in method_inv])
    inv_due = inv_start + 14
    paid_off = inv_start + ir2.integers(0, 5, NINV)
    invoice_status = np.where(~failed, "Paid", np.where(inv_due < A, "Overdue", "Open"))
    out[("billing", "invoice")] = pd.DataFrame(
        {
            "invoice_id": np.arange(1, NINV + 1),
            "subscriber_id": sub_s[rows_rep] + 1,
            "subscription_plan_id": plan_rep,
            "invoice_number": [f"INV-{i:08d}" for i in range(1, NINV + 1)],
            "invoice_date": dser(inv_start),
            "billing_period_start_date": dser(inv_start),
            "billing_period_end_date": dser(inv_start + per_rep - 1),
            "due_date": dser(inv_due),
            "paid_date": dser(paid_off, ~failed),
            "invoice_status": invoice_status,
            "currency_code": "USD",
            "subtotal_amount": subtotal,
            "discount_amount": discount,
            "tax_amount": tax,
            "total_amount_due": total,
            "amount_paid": np.where(failed, 0.0, total),
        }
    )

    annual_inv = plan_rep >= 5
    cand = np.where((~failed) & (ir2.random(NINV) < np.where(annual_inv, 0.22, 0.008)))[0]
    NREF = cand.size
    req_off = inv_start[cand] + ir2.integers(3, 31, NREF)
    proc_off = req_off + ir2.integers(2, 11, NREF)
    processed = proc_off < A
    rtype = np.where(ir2.random(NREF) < 0.7, "Full", "Partial")
    amt = np.where(rtype == "Full", total[cand], np.round(total[cand] * 0.5, 2))
    rcode = ir2.choice(list(REFUND_REASON_TEXT), NREF, p=[0.35, 0.1, 0.15, 0.4])
    out[("billing", "refund")] = pd.DataFrame(
        {
            "refund_id": np.arange(1, NREF + 1),
            "payment_id": cand + 1,
            "invoice_id": cand + 1,
            "subscriber_id": sub_s[rows_rep][cand] + 1,
            "refund_number": [f"RF-{i:06d}" for i in range(1, NREF + 1)],
            "request_date": dser(req_off),
            "processing_date": dser(proc_off, processed),
            "refund_status": np.where(processed, "Processed", "Requested"),
            "refund_type": rtype,
            "reason_code": rcode,
            "reason_description": [REFUND_REASON_TEXT[c] for c in rcode],
            "amount": amt,
            "currency_code": "USD",
        }
    )
    refunded = np.zeros(NINV)
    np.add.at(refunded, cand, amt)
    out[("billing", "payment")] = pd.DataFrame(
        {
            "payment_id": np.arange(1, NINV + 1),
            "invoice_id": np.arange(1, NINV + 1),
            "payment_number": [f"PAY-{i:08d}" for i in range(1, NINV + 1)],
            "payment_date": dser(inv_start),
            "payment_timestamp": pd.to_datetime(TS(inv_start * 86400 + ir2.integers(0, 86400, NINV))),
            "payment_status": np.where(failed, "Failed", "Succeeded"),
            "method_type": method_inv,
            "gateway": "Adyen",
            "failure_reason": [FAIL_REASON[m] if f else None for m, f in zip(method_inv, failed)],
            "is_autopay": ir2.random(NINV) < 0.9,
            "amount": total,
            "currency_code": "USD",
            "refund_amount": np.round(refunded, 2),
        }
    )

    paid_sum = pd.Series(np.where(failed, 0.0, total)).groupby(sub_s[rows_rep] + 1).sum()
    ltv = paid_sum.reindex(subscriber_df["subscriber_id"]).fillna(0).round(2).values
    tenure_m = np.maximum(1.0, (A - first_act) / 30.0)
    subscriber_df["ltv"] = ltv
    subscriber_df["arpu"] = np.round(ltv / tenure_m, 2)

    # ---------- churn events ----------
    cidx = np.where(status_s == "Cancelled")[0]
    ch_sub = sub_s[cidx]
    ch_day = term_s[cidx]
    ch_sec = ch_day * 86400 + lr.integers(0, 86400, cidx.size)
    keys = sub_s[sess_row] * 10**10 + t_sec
    ordk = np.argsort(keys, kind="stable")
    sk = keys[ordk]
    pos = np.searchsorted(sk, ch_sub * 10**10 + ch_sec, side="right") - 1
    pos_c = np.clip(pos, 0, None)
    hit = ordk[pos_c]
    valid = (pos >= 0) & (sess_sub[hit] == ch_sub)
    last_title_id = ep_title_of_session(ep_pick[hit], ep_df)
    last_sec = np.where(valid, t_sec[hit], act_s[cidx] * 86400)
    days_since = ch_day - last_sec // 86400
    fail_by_sub = pd.Series(failed.astype(np.int64)).groupby(sub_s[rows_rep] + 1).sum()
    pf = fail_by_sub.reindex(ch_sub + 1).fillna(0).astype(np.int64).values
    involuntary = (pf > 0) & (lr.random(cidx.size) < 0.5)
    out[("subscriber", "churn_event")] = pd.DataFrame(
        {
            "churn_event_id": np.arange(1, cidx.size + 1),
            "subscriber_id": ch_sub + 1,
            "subscription_id": cidx + 1,
            "last_viewed_title_id": [int(x) if v else None for x, v in zip(last_title_id, valid)],
            "ott_platform_id": [PLATFORM[g][0] for g in region_s[cidx]],
            "churn_timestamp": pd.to_datetime(TS(ch_sec)),
            "churn_type": np.where(involuntary, "Involuntary", "Voluntary"),
            "cancellation_reason_code": np.array(REASONS, dtype=object)[s_reason[cidx]],
            "cancellation_reason_description": [REASON_TEXT[REASONS[x]] for x in s_reason[cidx]],
            "subscription_tenure_months": np.maximum(0, (ch_day - act_s[cidx]) // 30),
            "days_since_last_viewing": days_since,
            "payment_failure_count": pf,
            "total_lifetime_revenue": ltv[ch_sub],
            "service_tier": [PLANS[int(p)][3] for p in plan_s[cidx]],
        }
    )

    # ---------- write ----------
    for t in subset["tables"]:
        key = (t["schema"], t["table"])
        if key not in out:
            raise RuntimeError(f"no generator for {key}")
        missing = [c for c in t["columns"] if c not in out[key].columns]
        if missing:
            raise RuntimeError(f"{key} missing generated columns {missing}")
    if args.dry_run:
        for key, df in out.items():
            print(f"dry-run {key[0]}.{key[1]}: {len(df)} rows", flush=True)
        pd.to_pickle(out, Path(tempfile.gettempdir()) / "hoshi_dry_run.pkl")
        print("dry-run complete", flush=True)
        return
    from pyspark.sql import SparkSession

    spark = SparkSession.builder.getOrCreate()
    total_rows = 0
    for t in subset["tables"]:
        key = (t["schema"], t["table"])
        df = out[key][t["columns"]]
        write_table(spark, cat, prefix, key[0], key[1], df)
        total_rows += len(df)
    write_manifest(spark, cat, prefix, as_of, SEED, subset["source"]["sha"], len(subset["tables"]), total_rows)
    print("generation complete", flush=True)


def ep_title_of_session(ep_ids, ep_df):
    lookup = ep_df["title_id"].values
    return lookup[np.asarray(ep_ids) - 1]


if __name__ == "__main__":
    main()
