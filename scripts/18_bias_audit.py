"""Step 18 (methodology cycle, section E) - bias audit of the risk bands.

Question: do the bands (low / medium / high / critical) track procurement
behaviour, or do they track *who* the parties are - buyer size, region,
industry, procedure type, supplier seniority? Open Moldovan procurement data
carries no protected attributes (gender, ethnicity), so this audit checks
structural groups and the features that act as their proxies.

Groups audited (section E.1):
  buyer size        - quintiles of procedures per buyer
  buyer type        - central / local / public body (OCDS typeOfBuyer first,
                      name heuristic as fallback; coverage is reported)
  buyer spend       - quintiles of the buyer's total awarded value (OCDS has
                      no budget field - this is the documented proxy)
  buyer region      - buyer locality (Chişinău / Bălţi / ... / other / unknown)
  supplier region   - supplier address region from OCDS, keyed by the CUATM
                      region code so Cyrillic/Latin spellings of one region
                      merge (only published with the award; coverage is
                      reported)
  industry          - CPV first two digits, top-10 + other
  procedure type    - direct award / micro / small / open / other
  contract value    - the money bands already used in results/tables/value_bands.csv
  supplier seniority- first contract vs repeat supplier
  supplier size     - quintiles of awards won (many vs few procedures)
  publication year  - 2018 .. 2024
  audit period      - tuning (2018-2021) vs holdout (2022-2024)
  publication completeness - bid+award data / award data only / neither

Metrics per group (section E.3):
  disparity ratio   - share high+critical in group / share in the rest of the corpus
                      with a bootstrap 95% CI; verdict bands [0.8, 1.25]
  band & percentile - the four band shares (low/medium/high/critical) plus the
                      group's median ranking percentile and its share in the
                      corpus top decile
  conditional gap   - the same share after direct standardisation over the
                      legitimate factors the model may use (each dimension is
                      controlled by the factors it is *not* itself); tolerance
                      proposed in the report (max(0.5 pp, 25% of the expected
                      share)) - this is also the per-group calibration rule
  TPR / FPR         - against the external AAP label, only where >= 10 labelled
                      procedures exist in the group, with the gap to the corpus
                      TPR (selection bias is reported, never averaged away)

Section E.4 additionally measures, for every model feature, its point-biserial
correlation with the structural group indicators: a feature with |r| >= 0.3 is
flagged as a structural proxy for the author's decision (removal is a
recommendation, never applied silently).

Stop criterion C6 (scripts/20_cycle_framework.py) reads the verdict counts from
results/methodology/bias_audit.json: any "нарушение" or "предупреждение" fails
it. The audit is corpus-level (production bands) and is re-run whenever a new
band configuration is proposed for adoption.

OCDS party attributes (buyer type, supplier region) are read-only over
data/raw/ocds_packages and cached in results/tables/party_attributes.csv;
re-scan with ``--rescan``.

Outputs:
    reports/bias_audit.md, results/tables/bias_audit_groups.csv,
    results/tables/bias_audit_feature_proxies.csv,
    results/figures/bias_audit.png, results/methodology/bias_audit.json

Usage:
    .venv/bin/python scripts/18_bias_audit.py [--rescan]
"""

from __future__ import annotations

import csv
import gzip
import json
import re
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.config import (DATA_FEATURES, DATA_RAW, FIGURES,  # noqa: E402
                                RESULTS, TABLES)
from src.mtender.eval_metrics import wilson_ci  # noqa: E402
from src.mtender.external_labels import load_scored_corpus  # noqa: E402
from src.mtender.features import FEATURE_COLUMNS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"

#: Proposed tolerance for the *conditional* gap (report section "Tolerances").
ABS_TOLERANCE_PP = 0.5          # percentage points
REL_TOLERANCE = 0.25            # 25% of the expected share
#: Proposed disparity band: the four-fifths rule, adapted to anomaly screening.
DISPARITY_OK = (0.8, 1.25)
BOOT = 500
MIN_POSITIVES_FOR_TPR = 10

MONEY_EDGES = [0, 100_000, 500_000, 1_000_000, 5_000_000, 10_000_000, 50_000_000, np.inf]
MONEY_LABELS = ["<100k", "100k-500k", "500k-1m", "1m-5m", "5m-10m", "10m-50m", ">=50m"]
MAIN_TYPES = ["directaward", "microvalue", "smallvalue", "opentender"]


def region_of(locality) -> str:
    """``mun.Chişinău (mun.Chişinău)`` -> ``Chişinău``; placeholders -> unknown.

    A prefix only counts when followed by a separator (``mun.`` / ``or.`` /
    whitespace): the previous pattern accepted it without a dot and silently
    turned ``Orhei`` into ``hei`` and ``Comrat`` into ``rat``.
    """
    if not isinstance(locality, str) or not locality.strip():
        return "unknown"
    text = locality.split("(")[0].strip()
    text = re.sub(
        r"^(municipiul|orasul|comuna|mun|or|sat|com|r-l|мун|ор|сат|ком)"
        r"(?:\.\s*|\s+)", "", text, flags=re.I)
    text = text.strip(" .-")
    if not text or text.lower() in {"locality", "unknown", "n/a"}:
        return "unknown"
    return text


#: Official OCDS ``typeOfBuyer`` values observed in the corpus -> audit groups.
CENTRAL_BUYER_TYPES = {"MINISTRY", "NATIONAL_AGENCY"}
LOCAL_BUYER_TYPES = {"REGIONAL_AUTHORITY", "REGIONAL_AGENCY"}
#: Name fallback when typeOfBuyer is absent (documented as a heuristic).
NAME_CENTRAL = re.compile(
    r"^(MINISTERUL|GUVERNUL|CANCELARIA|PARLAMENTUL|CURTEA|BANCA|FONDUL|"
    r"AGEN|ACADEMIA|UNIVERSITATEA|CENTRUL)")
NAME_LOCAL = re.compile(
    r"^(PRIM|CONSILIUL|MUNICIPIUL|ORA[ȘS]UL|ORASUL|COMUNA|SATUL)")


def classify_buyer_type(official, name) -> tuple[str, str]:
    """OCDS ``typeOfBuyer`` first, name heuristic as fallback -> (group, source).

    Returns ``(central | local | public body | other | unknown, source)`` so the
    report can show how much of each group came from the official field rather
    than from the keyword guess.
    """
    o = str(official or "").strip().upper()
    if o in CENTRAL_BUYER_TYPES:
        return "central", "ocds"
    if o in LOCAL_BUYER_TYPES:
        return "local", "ocds"
    if o == "BODY_PUBLIC":
        return "public body", "ocds"
    if o:
        return "other", "ocds"
    n = str(name or "").upper()
    if NAME_CENTRAL.match(n):
        return "central", "name heuristic"
    if NAME_LOCAL.match(n):
        return "local", "name heuristic"
    return "unknown", "none"


def supplier_region_of(cell, labels: dict[str, str]) -> str:
    """``"0101000::mun.Chişinău"`` -> the region, keyed by the CUATM code.

    Grouping happens on the *code*, so Cyrillic and Latin spellings of the
    same region land in one group; the human-readable label is the most
    frequent description of that code (``labels``). Several distinct codes ->
    ``multi-region``, no award address -> ``unknown``.
    """
    if not isinstance(cell, str) or not cell.strip():
        return "unknown"
    keys: set[str] = set()
    for pair in cell.split(";"):
        code, _, desc = pair.partition("::")
        key = code.strip() or desc.strip()
        if key:
            keys.add(key)
    if not keys:
        return "unknown"
    if len(keys) > 1:
        return "multi-region"
    key = next(iter(keys))
    return region_of(labels.get(key) or key)


def _first_nonempty(values) -> str:
    """First non-empty string in a group (used to roll EV/AC records up)."""
    for v in values:
        if isinstance(v, str) and v:
            return v
    return ""


def scan_ocds_party_attributes(cache: Path) -> None:
    """Read-only scan of the raw OCDS packages (~45 s for 152,378 .gz files).

    Only ``data/raw`` is read; the cache is the single artefact written by this
    function. Award-stage records (``-EV-``/``-AC-``) carry the supplier
    addresses, so every record of a package is scanned and the loader rolls
    them up onto the base ocid later.
    """
    files = sorted((DATA_RAW / "ocds_packages").glob("*.json.gz"))
    if not files:
        raise FileNotFoundError(f"no OCDS packages under {DATA_RAW / 'ocds_packages'}")
    rows: list[tuple[str, str, str]] = []
    for path in files:
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        for record in payload.get("records", []):
            ocid = record.get("ocid")
            if not ocid:
                continue
            compiled = record.get("compiledRelease") or {}
            buyer_type = ""
            regions: set[str] = set()
            for party in compiled.get("parties", []):
                roles = party.get("roles") or []
                details = party.get("details") or {}
                if "buyer" in roles and not buyer_type and details.get("typeOfBuyer"):
                    buyer_type = str(details["typeOfBuyer"])
                if "supplier" in roles:
                    address = (party.get("address") or {}).get("addressDetails") or {}
                    region = address.get("region") or {}
                    code = str(region.get("id") or "").strip()
                    desc = str(region.get("description") or "").strip()
                    if code or desc:
                        regions.add(f"{code}::{desc}")
            rows.append((ocid, buyer_type, ";".join(sorted(regions))))
    if not rows:
        raise ValueError("OCDS scan produced no records - raw data unchanged?")
    with cache.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["ocid", "buyer_type", "supplier_regions"])
        writer.writerows(rows)


def load_party_attributes(rescan: bool = False) -> pd.DataFrame:
    """Cached record-level OCDS party attributes (read-only over data/raw).

    ``supplier_regions`` stores ``CUATM-code::description`` pairs; a cache from
    the older description-only format cannot unify Cyrillic/Latin spellings of
    the same region and is re-scanned automatically.
    """
    cache = TABLES / "party_attributes.csv"
    force = rescan or not cache.exists() or cache.stat().st_size == 0
    if not force:
        probe = pd.read_csv(cache, usecols=["supplier_regions"],
                            low_memory=False)["supplier_regions"].dropna()
        probe = probe[probe != ""]
        force = probe.empty or not probe.str.contains("::", na=False).any()
    if force:
        print(f"scanning {DATA_RAW / 'ocds_packages'} -> {cache}", flush=True)
        scan_ocds_party_attributes(cache)
    return pd.read_csv(cache, usecols=["ocid", "buyer_type", "supplier_regions"])


def region_label_map(party: pd.DataFrame) -> dict[str, str]:
    """CUATM code -> most frequent description across the cache."""
    counters: dict[str, dict[str, int]] = {}
    for cell in party["supplier_regions"]:
        if not isinstance(cell, str) or not cell:
            continue
        for pair in cell.split(";"):
            code, _, desc = pair.partition("::")
            code = code.strip()
            if not code:
                continue
            seen = counters.setdefault(code, {})
            seen[desc] = seen.get(desc, 0) + 1
    return {code: max(seen, key=seen.get) or code
            for code, seen in counters.items()}


def quintile_labels(series: pd.Series, name: str) -> pd.Series:
    """Q1 smallest .. Q5 largest, with ties broken by position."""
    try:
        q = pd.qcut(series.rank(method="first"), 5, labels=[f"{name} Q1", f"{name} Q2",
                                                            f"{name} Q3", f"{name} Q4",
                                                            f"{name} Q5"])
    except ValueError:
        return pd.Series(f"{name} all", index=series.index)
    return q.astype(str)


def bootstrap_disparity(g_flag: np.ndarray, rest_flag: np.ndarray,
                        seed: int = 42) -> tuple[float, float, float]:
    """Point estimate and 95% CI of (share_highplus_group / share_highplus_rest)."""
    if rest_flag.size == 0 or g_flag.size == 0 or rest_flag.mean() == 0:
        return float("nan"), float("nan"), float("nan")
    point = float(g_flag.mean() / rest_flag.mean())
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(BOOT):
        g = rng.choice(g_flag, size=g_flag.size, replace=True).mean()
        r = rng.choice(rest_flag, size=rest_flag.size, replace=True).mean()
        if r > 0:
            draws.append(g / r)
    if not draws:
        return point, float("nan"), float("nan")
    arr = np.asarray(draws)
    return point, float(np.quantile(arr, 0.025)), float(np.quantile(arr, 0.975))


def main() -> int:
    warnings.filterwarnings("ignore")
    corpus = load_scored_corpus()
    feats = pd.read_csv(DATA_FEATURES / "features.csv", low_memory=False)
    # award_total / cpv_primary already come from the label table: only the
    # columns the corpus does not carry are fetched from features.csv here
    df = corpus.merge(
        feats[["ocid", "buyer_id", "buyer_locality",
               "procurement_method_details", "winner_identifier",
               "supplier_award_count_log", "has_bid_data", "has_award_data"]],
        on="ocid", how="left", validate="one_to_one",
    )

    # ---- OCDS party attributes (buyer type, supplier region) --------------
    # Cached read-only extraction: base ocid -> first non-empty value over the
    # package's records (award-stage EV/AC records hold the supplier address).
    party = load_party_attributes(rescan="--rescan" in sys.argv)
    base_attrs = (
        party.assign(base=party["ocid"].str.replace(r"-(EV|AC|PN)-.*$", "",
                                                    regex=True))
        .groupby("base")
        .agg(ocds_buyer_type=("buyer_type", _first_nonempty),
             supplier_regions=("supplier_regions", _first_nonempty))
    )
    df = df.merge(base_attrs, left_on="ocid", right_index=True, how="left")
    df["ocds_buyer_type"] = df["ocds_buyer_type"].fillna("")
    df["supplier_regions"] = df["supplier_regions"].fillna("")

    votes = df["n_models_flagging"].astype(int)
    df["high_plus"] = (votes >= 2).astype(int)      # high + critical
    df["critical"] = (votes >= 3).astype(int)
    df["band"] = np.select([votes == 0, votes == 1, votes == 2],
                           ["low", "medium", "high"], default="critical")
    df["money_band"] = pd.cut(df["award_total"].fillna(0), bins=MONEY_EDGES,
                              labels=MONEY_LABELS, right=False).astype(str)
    df["proc_type"] = df["procurement_method_details"].where(
        df["procurement_method_details"].isin(MAIN_TYPES), "other")

    buyer_counts = df.groupby("buyer_id")["ocid"].transform("size")
    df["buyer_size"] = quintile_labels(buyer_counts, "buyer_size")
    df["region"] = df["buyer_locality"].map(region_of)
    top_regions = df["region"].value_counts().head(10).index
    df["region_group"] = df["region"].where(df["region"].isin(top_regions), "other")
    cpv2 = df["cpv_primary"].astype(str).str[:2]
    top_cpv = cpv2.value_counts().head(10).index
    df["industry"] = cpv2.where(cpv2.isin(top_cpv), "other")
    supplier_awards = np.expm1(pd.to_numeric(df["supplier_award_count_log"],
                                             errors="coerce").fillna(0.0))
    df["supplier_seniority"] = np.where(supplier_awards <= 1, "first contract",
                                        "repeat supplier")
    df["supplier_size"] = quintile_labels(supplier_awards, "supplier_size")

    # ---- section E.1 additions -------------------------------------------
    # buyer type: official typeOfBuyer, name heuristic as the documented
    # fallback; the source split is reported as data coverage, not hidden
    classified = [classify_buyer_type(t, n)
                  for t, n in zip(df["ocds_buyer_type"], df["buyer_name"].fillna(""))]
    df["buyer_type"] = [c[0] for c in classified]
    df["buyer_type_source"] = [c[1] for c in classified]

    # budget proxy: OCDS carries no buyer budget - total awarded value is used
    buyer_spend = df.groupby("buyer_id")["award_total"].transform(
        lambda s: s.fillna(0).sum())
    df["buyer_spend"] = quintile_labels(buyer_spend, "buyer_spend")

    # supplier region: CUATM-code groups, top-10 (incl. explicit "unknown"),
    # everything else other
    region_labels = region_label_map(party)
    df["supplier_region"] = df["supplier_regions"].map(
        lambda cell: supplier_region_of(cell, region_labels))
    top_sup = df["supplier_region"].value_counts().head(10).index
    df["supplier_region_group"] = df["supplier_region"].where(
        df["supplier_region"].isin(top_sup), "other")

    # time and publication completeness
    pub_year = pd.to_datetime(df["published_date"], errors="coerce").dt.year
    df["pub_year"] = pub_year.map(lambda y: str(int(y)) if pd.notna(y) else "unknown")
    df["audit_period"] = np.select(
        [pub_year.between(2018, 2021), pub_year.between(2022, 2024)],
        ["tuning 2018-2021", "holdout 2022-2024"], default="unknown")
    has_bid = df["has_bid_data"].astype(str).str.lower().isin({"true", "1"})
    has_award = df["has_award_data"].astype(str).str.lower().isin({"true", "1"})
    df["pub_completeness"] = np.select(
        [has_bid & has_award, has_award],
        ["bid+award data", "award data only"], default="no bid/award data")

    # ranking percentiles used by the band/percentile columns (E.3)
    df["max_score"] = pd.to_numeric(df["max_score"], errors="coerce")
    top_decile_at = float(df["max_score"].quantile(0.9))
    corpus_tpr = float(df.loc[df["is_aap_positive"] == 1, "high_plus"].mean())

    # ---- strata for direct standardisation --------------------------------
    # A dimension must not be controlled by its own factor: standardising
    # "procedure type" over (money band x procedure type) would force its
    # conditional gap to ~0 by construction and hide the very effect the audit
    # is supposed to measure. Each dimension is therefore standardised over the
    # legitimate factors it is *not* itself. "Publication completeness" is the
    # exception that proves the rule: its money band is built from award_total,
    # which is missing exactly when publication is incomplete - controlling it
    # would absorb the audited effect, so only the procedure type is used.
    DIM_STRATA = {
        "buyer size (procedures per buyer)": ["money_band", "proc_type"],
        "buyer type (central/local)": ["money_band", "proc_type"],
        "buyer spend (total awarded, budget proxy)": ["money_band", "proc_type"],
        "buyer region (locality)": ["money_band", "proc_type"],
        "supplier region (OCDS address)": ["money_band", "proc_type"],
        "industry (CPV 2 digits)": ["money_band", "proc_type"],
        "procedure type": ["money_band"],
        "contract value band": ["proc_type"],
        "supplier seniority": ["money_band", "proc_type"],
        "supplier size (awards won)": ["money_band", "proc_type"],
        "publication year": ["money_band", "proc_type"],
        "audit period (tuning/holdout)": ["money_band", "proc_type"],
        "publication completeness": ["proc_type"],
    }

    def stratum_keys(frame: pd.DataFrame, cols: list[str]) -> pd.Series:
        """Vectorised ``a|b|...`` keys (``agg(..., axis=1)`` is far too slow
        to run once per group over the full corpus)."""
        keys = frame[cols[0]].astype(str)
        for col in cols[1:]:
            keys = keys + "|" + frame[col].astype(str)
        return keys

    # corpus-level rates per stratum cell depend only on the band vector, so
    # they are computed once per stratum tuple, not once per group
    cell_cache: dict[tuple[str, ...], tuple[pd.Series, pd.Series]] = {}

    def standardised_expectation(sub: pd.DataFrame, strata_cols: list[str]) -> float:
        """Mean over the group of the corpus rate within each stratum cell."""
        key = tuple(strata_cols)
        if key not in cell_cache:
            full_keys = stratum_keys(df, strata_cols)
            cell_cache[key] = (full_keys.value_counts(),
                               df["high_plus"].groupby(full_keys).mean())
        counts, rates = cell_cache[key]
        keys = stratum_keys(sub, strata_cols)
        cell_rate = keys.map(rates)
        cell_n = keys.map(counts)
        corpus_rate = float(df["high_plus"].mean())
        return float(np.where(cell_n >= 50, cell_rate, corpus_rate).mean())

    GROUPS = {
        "buyer size (procedures per buyer)": "buyer_size",
        "buyer type (central/local)": "buyer_type",
        "buyer spend (total awarded, budget proxy)": "buyer_spend",
        "buyer region (locality)": "region_group",
        "supplier region (OCDS address)": "supplier_region_group",
        "industry (CPV 2 digits)": "industry",
        "procedure type": "proc_type",
        "contract value band": "money_band",
        "supplier seniority": "supplier_seniority",
        "supplier size (awards won)": "supplier_size",
        "publication year": "pub_year",
        "audit period (tuning/holdout)": "audit_period",
        "publication completeness": "pub_completeness",
    }

    rows = []
    for label, col in GROUPS.items():
        for value, sub in df.groupby(col, dropna=False):
            if pd.isna(value) or str(value).lower() in {"nan", "none", ""}:
                continue
            rest = df[df[col] != value]
            g_flag = sub["high_plus"].to_numpy()
            rest_flag = rest["high_plus"].to_numpy()
            rate = float(g_flag.mean())
            lo, hi = wilson_ci(int(g_flag.sum()), int(g_flag.size))
            point, dlo, dhi = bootstrap_disparity(g_flag, rest_flag)

            # conditional (standardised) expectation over the OTHER factors
            expected = standardised_expectation(sub, DIM_STRATA[label])
            gap_pp = (rate - expected) * 100
            tol_pp = max(ABS_TOLERANCE_PP, REL_TOLERANCE * expected * 100)

            positives = int(sub["is_aap_positive"].sum())
            tpr = fpr = tpr_gap = None
            if positives >= MIN_POSITIVES_FOR_TPR:
                pos = sub[sub["is_aap_positive"] == 1]
                neg = sub[sub["is_aap_positive"] == 0]
                tpr = round(float(pos["high_plus"].mean()), 6)
                fpr = round(float(neg["high_plus"].mean()), 6)
                tpr_gap = round((tpr - corpus_tpr) * 100, 4)

            band_share = sub["band"].value_counts(normalize=True)

            # Section E.4 requires the two cases kept apart:
            #   - raw disparity outside the band BUT conditional gap inside
            #     tolerance -> the difference is EXPLAINED by the legitimate
            #     factors the model is allowed to use
            #   - conditional gap itself outside tolerance -> NOT explained
            ci_outside = bool(dhi < DISPARITY_OK[0] or dlo > DISPARITY_OK[1]) \
                if dlo == dlo else False
            ci_straddles = bool(not ci_outside and (point < DISPARITY_OK[0]
                                or point > DISPARITY_OK[1])) if point == point else False
            gap_outside = bool(abs(gap_pp) > tol_pp)

            verdict = "допустимо"
            reasons = []
            if ci_outside and not gap_outside:
                verdict = "допустимо (разница объяснена легитимными факторами)"
                reasons.append(f"disparity CI [{dlo:.2f}, {dhi:.2f}] вне границы, "
                               f"но условное отклонение {gap_pp:+.2f} pp внутри "
                               f"допуска {tol_pp:.2f} pp")
            elif ci_outside and gap_outside:
                verdict = "нарушение"
                reasons.append(f"disparity CI [{dlo:.2f}, {dhi:.2f}] вне границы И "
                               f"условное отклонение {gap_pp:+.2f} pp > допуска "
                               f"{tol_pp:.2f} pp — не объясняется легитимными факторами")
            elif ci_straddles:
                verdict = "предупреждение"
                reasons.append(f"disparity point {point:.2f} вне границы, "
                               "но ДИ пересекает её")
            if gap_outside and not ci_outside:
                verdict = ("нарушение" if verdict.startswith("нарушение")
                           else "предупреждение")
                reasons.append(f"условное отклонение {gap_pp:+.2f} pp > допуска "
                               f"{tol_pp:.2f} pp")

            rows.append({
                "group_dimension": label,
                "group": value,
                "n": int(len(sub)),
                "share_of_corpus": round(len(sub) / len(df), 6),
                "share_high_plus": round(rate, 6),
                "share_high_plus_ci_lo": round(lo, 6) if lo == lo else None,
                "share_high_plus_ci_hi": round(hi, 6) if hi == hi else None,
                "share_low": round(float(band_share.get("low", 0.0)), 6),
                "share_medium": round(float(band_share.get("medium", 0.0)), 6),
                "share_high": round(float(band_share.get("high", 0.0)), 6),
                "share_critical": round(float(band_share.get("critical", 0.0)), 6),
                "median_ranking_percentile": round(
                    float(sub["max_score"].median()), 6),
                "share_in_top_decile": round(
                    float((sub["max_score"] >= top_decile_at).mean()), 6),
                "disparity_ratio": round(point, 4) if point == point else None,
                "disparity_ci_lo": round(dlo, 4) if dlo == dlo else None,
                "disparity_ci_hi": round(dhi, 4) if dhi == dhi else None,
                "expected_share_standardised": round(expected, 6),
                "conditional_gap_pp": round(gap_pp, 4),
                "tolerance_pp": round(tol_pp, 4),
                "calibration_ok": bool(not gap_outside),
                "n_aap_labelled": positives,
                "tpr_vs_aap": tpr,
                "fpr_vs_aap": fpr,
                "tpr_gap_vs_corpus_pp": tpr_gap,
                "verdict": verdict,
                "reasons": "; ".join(reasons),
            })

    groups = pd.DataFrame(rows)
    groups.to_csv(TABLES / "bias_audit_groups.csv", index=False)

    # ---- E.4: features as proxies for structural groups -------------------
    proxy_targets = {
        "capital_region": (df["region"] == "Chişinău").to_numpy(),
        "large_buyer_top_decile": (
            buyer_counts >= buyer_counts.quantile(0.9)).to_numpy(),
        "direct_award": (df["proc_type"] == "directaward").to_numpy(),
        "construction_cpv45": (cpv2 == "45").to_numpy(),
        "first_contract_supplier": (df["supplier_seniority"] == "first contract").to_numpy(),
    }
    proxy_rows = []
    for col in [c for c in FEATURE_COLUMNS if c in df.columns]:
        values = pd.to_numeric(df[col], errors="coerce").fillna(0.0).to_numpy()
        row = {"feature": col}
        for target, mask in proxy_targets.items():
            row[f"corr_{target}"] = round(float(np.corrcoef(values, mask.astype(float))[0, 1]), 4)
        worst = max((abs(v) for k, v in row.items() if k.startswith("corr_")), default=0.0)
        row["max_abs_corr"] = round(float(worst), 4)
        row["flagged_structural_proxy"] = bool(worst >= 0.3)
        proxy_rows.append(row)
    proxies = pd.DataFrame(proxy_rows).sort_values("max_abs_corr", ascending=False)
    proxies.to_csv(TABLES / "bias_audit_feature_proxies.csv", index=False)

    # ---- AAP label coverage (selection bias of the external source) -------
    coverage = []
    for label, col in GROUPS.items():
        sub = df[df["is_aap_positive"] == 1]
        for value, part in sub.groupby(col, dropna=False):
            base = df[df[col] == value]
            coverage.append({
                "group_dimension": label,
                "group": value,
                "n_in_corpus": int(len(base)),
                "n_labelled": int(len(part)),
                "label_rate_in_group": round(len(part) / max(len(base), 1), 6),
            })
    coverage_df = pd.DataFrame(coverage)
    coverage_df.to_csv(TABLES / "bias_audit_label_coverage.csv", index=False)

    calibration_within = int(groups["calibration_ok"].sum())
    summary = {
        "n_procedures": int(len(df)),
        "n_dimensions": int(groups["group_dimension"].nunique()),
        "high_plus_share_corpus": round(float(df["high_plus"].mean()), 6),
        "critical_share_corpus": round(float(df["critical"].mean()), 6),
        "corpus_tpr_vs_aap": round(corpus_tpr, 6),
        "tolerances": {
            "disparity_ratio_ok_band": list(DISPARITY_OK),
            "disparity_band_rationale": (
                "adapted four-fifths rule: below 0.8 or above 1.25 the group's screening "
                "rate is hard to defend as behaviour-driven without a documented cause"
            ),
            "conditional_gap": f"max({ABS_TOLERANCE_PP} pp, {REL_TOLERANCE:.0%} of expected)",
            "conditional_gap_rationale": (
                "after standardising over money band x procedure type, a residual gap "
                "larger than this is not explained by the legitimate factors the model "
                "is allowed to use"
            ),
            "calibration_rule": (
                "per-group calibration: the observed high+ share must stay within the "
                "proposed conditional tolerance of the standardised expectation; "
                "groups outside it are listed in the report with their reasons"
            ),
        },
        "calibration": {
            "within_tolerance": calibration_within,
            "outside_tolerance": int(len(groups) - calibration_within),
        },
        "data_coverage": {
            "buyer_type_source": df["buyer_type_source"].value_counts().to_dict(),
            "buyer_type_group": df["buyer_type"].value_counts().to_dict(),
            "supplier_region_known_share": round(
                float((df["supplier_region"] != "unknown").mean()), 4),
            "publication_completeness": df["pub_completeness"].value_counts().to_dict(),
            "note": (
                "typeOfBuyer is published for part of the corpus only - the name "
                "heuristic fills part of the gap and 'unknown' stays an explicit "
                "group; the supplier address appears with the award record only"
            ),
        },
        "verdict_counts": groups["verdict"].value_counts().to_dict(),
        "groups_flagged": groups[groups["verdict"].str.startswith(
            ("нарушение", "предупреждение"))][
            ["group_dimension", "group", "disparity_ratio", "disparity_ci_lo",
             "disparity_ci_hi", "conditional_gap_pp", "verdict", "reasons"]
        ].to_dict("records"),
        "structural_proxies": proxies[proxies["flagged_structural_proxy"]][
            "feature"].tolist(),
        "external_label_selection_bias": (
            "the AAP list contains only caught suppliers; labelled procedures concentrate "
            "in the groups those suppliers happen to serve, so TPR/FPR by group is "
            "reported with counts and never averaged over the corpus"
        ),
        "protected_attributes": (
            "none are present in open MTender OCDS data; region, buyer size, buyer type, "
            "supplier size and region, publication year and completeness are the "
            "structural attributes that can be audited instead"
        ),
        "c6_stop_criterion": (
            "scripts/20_cycle_framework.py fails C6 while verdict_counts contains any "
            "'нарушение' or 'предупреждение' - every group must sit inside the band or "
            "have its residual gap explained by legitimate factors and documented. "
            "The audit is corpus-level (production bands): re-run this script whenever "
            "a new band configuration is proposed for adoption"
        ),
        "publication_completeness_note": (
            "part of the buyers do not publish bid or award data at all; the audit "
            "reports it as an explicit group rather than dropping those procedures"
        ),
        "disclaimer": "Indicators of potential risk, not evidence of corruption.",
    }
    REPORTS.mkdir(exist_ok=True)
    out_dir = RESULTS / "methodology"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "bias_audit.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"corpus {len(df):,}; high+critical {df['high_plus'].mean():.4f}; "
          f"critical {df['critical'].mean():.4f}")
    print("\nverdicts:")
    print(groups["verdict"].value_counts().to_string())
    print("\nflagged groups:")
    print(groups[groups["verdict"].str.startswith(("нарушение", "предупреждение"))][
        ["group_dimension", "group", "n", "share_high_plus", "disparity_ratio",
         "disparity_ci_lo", "disparity_ci_hi", "conditional_gap_pp", "verdict"]
    ].to_string(index=False))
    print("\ntop structural proxies:")
    print(proxies.head(10)[["feature", "max_abs_corr", "flagged_structural_proxy"]]
          .to_string(index=False))
    print(f"\ntable  -> {TABLES / 'bias_audit_groups.csv'}")
    print(f"table  -> {TABLES / 'bias_audit_feature_proxies.csv'}")
    print(f"report -> {REPORTS / 'bias_audit.md'}")
    _plot(groups, df)
    _write_markdown(groups, proxies, coverage_df, summary)
    return 0


def _plot(groups: pd.DataFrame, df: pd.DataFrame) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # noqa: BLE001
        print(f"plot skipped: {exc}")
        return
    g_all = groups.dropna(subset=["disparity_ratio"])
    fig, axes = plt.subplots(1, 2, figsize=(15, max(6, 0.17 * len(g_all) + 2)))

    ax = axes[0]
    g = groups.dropna(subset=["disparity_ratio"]).copy()
    g["label"] = g["group_dimension"].str.slice(0, 12) + ": " + g["group"].astype(str)
    g = g.iloc[::-1]
    colors = {"допустимо": "tab:blue",
              "допустимо (разница объяснена легитимными факторами)": "tab:green",
              "предупреждение": "tab:orange",
              "нарушение": "tab:red"}
    for i, row in enumerate(g.itertuples()):
        ax.plot([row.disparity_ci_lo, row.disparity_ci_hi], [i, i],
                color=colors.get(row.verdict, "grey"), lw=2)
        ax.plot([row.disparity_ratio], [i], marker="o",
                color=colors.get(row.verdict, "grey"))
    ax.axvspan(*DISPARITY_OK, color="green", alpha=0.08, label="proposed OK band")
    ax.axvline(1.0, color="black", lw=0.8)
    ax.set_yticks(range(len(g)), g["label"], fontsize=6)
    ax.set_xlabel("disparity ratio (share high+ in group / share in rest), 95% CI")
    ax.set_title("Bias audit: disparity by group")
    ax.legend(fontsize=7)

    ax = axes[1]
    for dim, col in (("procedure type", "proc_type"), ("supplier seniority", "supplier_seniority")):
        sub = df.groupby(col)["high_plus"].mean().sort_values()
        ax.barh([f"{dim[:6]}: {i}" for i in sub.index], sub.values, alpha=0.7)
    ax.set_xlabel("share of procedures in high+ / critical band")
    ax.set_title("Screening rate by group (unconditional)")

    fig.suptitle("Bias audit - bands as behaviour vs bands as group membership "
                 "(indicator of potential risk, not evidence of corruption)", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIGURES / "bias_audit.png", dpi=140)
    print(f"figure -> {FIGURES / 'bias_audit.png'}")


def _write_markdown(groups: pd.DataFrame, proxies: pd.DataFrame,
                    coverage: pd.DataFrame, summary: dict) -> None:
    def table(frame: pd.DataFrame, cols: list[str]) -> str:
        """Markdown table without a tabulate dependency (repo keeps deps minimal)."""
        view = frame[cols].astype(str).fillna("")
        header = "| " + " | ".join(cols) + " |"
        rule = "|" + "|".join(["---"] * len(cols)) + "|"
        body = ["| " + " | ".join(row) + " |" for row in view.to_numpy()]
        return "\n".join([header, rule, *body])

    flagged = groups[groups["verdict"].str.startswith(("нарушение", "предупреждение"))]
    explained = groups[groups["verdict"].str.startswith("допустимо (")]
    with_tpr = groups[groups["tpr_vs_aap"].notna()].sort_values(
        "n_aap_labelled", ascending=False)
    calib = summary["calibration"]
    cov = summary["data_coverage"]
    src = cov["buyer_type_source"]
    n_all = max(sum(src.values()), 1)

    def pct(part: int, whole: int) -> str:
        return f"{100 * part / max(whole, 1):.1f}%"

    lines = [
        "# Аудит смещения (bias audit) полос риска",
        "",
        "Дата: 2026-10-17. Корпус: 152,378 процедур, полосы по числу голосов детекторов "
        "(high+ = 2 и более голоса, critical = 3 и более).",
        "",
        "Индикатор потенциального риска, а не доказательство коррупции: все доли ниже — "
        "это частоты попадания в экранинговую полосу, а не частоты нарушений.",
        "",
        "## 1. Метод и допустимые границы",
        "",
        f"- **Disparity ratio** = доля high+ в группе / доля high+ в остальном корпусе, "
        f"бутстрап-ДИ ({BOOT} реплик). Допустимая полоса **{DISPARITY_OK[0]}–"
        f"{DISPARITY_OK[1]}** (адаптированное «правило четырёх пятых»).",
        "- **Распределение полос и перцентилей** — доли четырёх полос (low / medium / "
        "high / critical) внутри группы, медианный перцентиль места в продакшн-"
        "ранжировании (`max_score`) и доля процедур группы в верхней декили корпуса.",
        f"- **Условное (стандартизованное) отклонение** — ожидаемая доля считается по "
        f"строкам той же группы с учётом легитимных факторов, при этом проверяемый "
        f"фактор **не входит в свой же контроль**: иначе его условное отклонение было "
        f"бы ≈0 по построению. Для денежной полосы контролируются объём и тип "
        f"процедуры; для полноты публикации — только тип процедуры (денежная полоса "
        f"строится из `award_total`, которого нет как раз у неполных публикаций). "
        f"Допуск **max({ABS_TOLERANCE_PP} пп, {REL_TOLERANCE:.0%} от ожидаемой доли)** — "
        f"это и есть предложенный **правило калибровки по группам**: наблюдаемая доля "
        f"high+ должна укладываться в него относительно стандартизованного ожидания.",
        "- **TPR/FPR против внешней метки AAP** — только для групп с ≥10 размеченными "
        "процедурами, вместе с отклонением TPR от корпусного TPR; пропорция AAP известна "
        "только для пойманных поставщиков (selection bias), поэтому эти числа не "
        "усредняются по корпусу.",
        "- **Критерий остановки C6** (см. `scripts/20_cycle_framework.py`): аудит "
        "смещения считается пройденным, когда все группы внутри границы либо "
        "оставшиеся отклонения объяснены легитимными факторами и задокументированы — "
        "механически: ни одного вердикта «нарушение» и ни одного «предупреждение». "
        "Аудит корпусный (прод-полосы) и перезапускается при предложении новой "
        "конфигурации полос.",
        "",
        "## 2. Итоги по группам",
        "",
        f"Всего групп проверено: {len(groups)} в {summary['n_dimensions']} измерениях. "
        "Вердикты: "
        + ", ".join(f"{k} — {v}" for k, v in summary["verdict_counts"].items()) + ".",
        "",
        f"Калибровка по группам (|наблюдаемая − ожидаемая| ≤ предложенного допуска): "
        f"внутри допуска — {calib['within_tolerance']} групп, вне допуска — "
        f"{calib['outside_tolerance']} (все они перечислены в разделе 4 с причинами).",
        "",
        table(groups.sort_values(["group_dimension", "group"]),
              ["group_dimension", "group", "n", "share_high_plus", "disparity_ratio",
               "disparity_ci_lo", "disparity_ci_hi", "expected_share_standardised",
               "conditional_gap_pp", "verdict"]),
        "",
        "## 3. Распределение полос и перцентилей по группам",
        "",
        "Доли полос считаются внутри группы (строки суммируются до 1), перцентиль — "
        "место группы в продакшн-ранжировании `max_score`, top-decile — доля процедур "
        "группы, попавших в верхние 10% корпуса по этому ранжированию:",
        "",
        table(groups.sort_values(["group_dimension", "group"]),
              ["group_dimension", "group", "n", "share_low", "share_medium",
               "share_high", "share_critical", "median_ranking_percentile",
               "share_in_top_decile"]),
        "",
        "## 4. Группы с отклонениями и объяснение",
        "",
    ]
    if len(flagged):
        for r in flagged.itertuples():
            lines.append(f"- **{r.group_dimension} / {r.group}** — {r.verdict}: "
                         f"{r.reasons or 'см. таблицу'}")
    else:
        lines.append("- отклонений за пределами допуска нет")
    if len(explained):
        lines += [
            "",
            "### Разница объяснена легитимными факторами",
            "",
            "Эти группы отличаются по сырой доле попадания в high+, но после "
            "стандартизации остаются внутри допуска — их различия объясняются "
            "факторами, которые модель имеет право учитывать (объём, тип процедуры):",
            "",
        ]
        for r in explained.itertuples():
            lines.append(f"- **{r.group_dimension} / {r.group}** — {r.reasons}")
    lines += [
        "",
        "## 5. Внешняя проверка: TPR/FPR по группам",
        "",
        f"Корпусный TPR против метки AAP: {summary.get('corpus_tpr_vs_aap', float('nan')):.4f} "
        "там, где группа содержит ≥10 размеченных процедур; `tpr_gap` — отклонение "
        "группового TPR от корпусного в п.п. Большой |gap| при малом n — шум "
        "внешней метки, а не свойство группы:",
        "",
    ]
    if len(with_tpr):
        lines.append(table(with_tpr,
                           ["group_dimension", "group", "n", "n_aap_labelled",
                            "tpr_vs_aap", "fpr_vs_aap", "tpr_gap_vs_corpus_pp"]))
    else:
        lines.append("- ни одна группа не набрала ≥10 размеченных процедур")
    lines += [
        "",
        "## 6. Прокси в признаках модели (E.4)",
        "",
        "Каждый признак проверен на корреляцию (point-biserial) с пятью структурными "
        "индикаторами: столичный регион, крупный заказчик, прямая закупка, CPV 45 "
        "(строительство), поставщик с первым контрактом. |r| ≥ 0.3 → структурный прокси.",
        "",
        table(proxies.head(12),
              ["feature", "max_abs_corr", "flagged_structural_proxy"]),
        "",
        "## 7. Покрытие внешней метки (selection bias источника)",
        "",
        "AAP публикует только поставщиков, которых поймали. Размеченные процедуры "
        "сосредоточены в определённых группах, поэтому TPR/FPR по группам приведён "
        "там, где n ≥ 10, и всегда вместе с числом наблюдений:",
        "",
        table(coverage.sort_values("n_labelled", ascending=False).head(15),
              ["group_dimension", "group", "n_in_corpus", "n_labelled",
               "label_rate_in_group"]),
        "",
        "## 8. Что делать при нарушении (меры E.5 — рекомендации)",
        "",
        "Ниже — список мер для автора при получении вердикта «нарушение». Это "
        "рекомендации, а не автоматические действия: любое изменение выдачи модели "
        "требует ablation и фиксации в `docs/model_card.md`. Невыполнимые решения "
        "(удаление признаков, групповые пороги) здесь не применяются, только "
        "предлагаются. Индикатор потенциального риска, а не доказательство коррупции.",
        "",
        "1. **Нормализация в референтной группе**: процентили признака (например, "
        "«число процедур поставщика») считаются относительно референтной группы "
        "(регион, размер заказчика), а не всего корпуса — тогда сравнение групп "
        "становится сравнением одинаковых единиц.",
        "2. **Удаление или объединение прокси-признаков**: если признак воспроизводит "
        "структурную группу (раздел 6, |r| ≥ 0.3), предложить автору его удаление "
        "или объединение с коррелированными признаками; решение — только с ablation "
        "по протоколу цикла.",
        "3. **Групповые пороги**: допустимы только с записью обоснования в "
        "`docs/model_card.md` (почему порог различается, как это влияет на precision/"
        "recall каждой группы); без такой записи различие порогов — скрытая "
        "дискриминация по группе.",
        "4. **Исправление данных**: неполнота публикации (раздел 9) и неполнота "
        "`typeOfBuyer` лечатся требованиями к публикации со стороны заказчика и "
        "ETL, а не настройкой модели; аудит фиксирует проблему, но не устраняет её.",
        "5. **Компромисс precision/recall**: если после мер 1–4 отклонение "
        "сохраняется, допустимо сместить порог полос для группы в сторону recall — "
        "с обязательной записью обоих эффектов (TPR/FPR по группе) в model_card.",
        "",
        "## 9. Ограничения",
        "",
        "- Защищённых атрибутов (пол, национальность) в открытых данных MTender нет; "
        "проверяются только структурные группы и признаки-прокси.",
        "- Регион взят по `buyer_locality` (свободный текст), точность группировки "
        "ограничена; 7,712 записей несут плейсхолдер «locality» и вынесены в unknown.",
        "- Внешняя выборка мала: 633 размеченной процедуры у 17 поставщиков.",
        "- AAP-список содержит только пойманных поставщиков — смещение отбора источника "
        "не устранимо без независимого источника меток.",
        f"- Тип заказчика покрыт не полностью: официальное поле `typeOfBuyer` — "
        f"{pct(src.get('ocds', 0), n_all)}, эвристика по названию — "
        f"{pct(src.get('name heuristic', 0), n_all)}, неизвестно — "
        f"{pct(src.get('none', 0), n_all)}; «unknown» остаётся отдельной группой "
        f"аудита и не исключается из расчётов.",
        f"- Регион поставщика известен для {100 * cov['supplier_region_known_share']:.1f}% "
        "процедур: адрес публикуется вместе с записью награждения, поэтому группы "
        "«unknown» и «multi-region» сохраняются явно.",
        "- В OCDS нет бюджета заказчика — вместо него взята сумма его контрактов "
        "(прокси, групповое измерение «buyer spend»).",
        "- **Возможная неполнота публикации у части заказчиков**: "
        + ", ".join(f"{k} — {v:,}" for k, v in
                    cov["publication_completeness"].items())
        + ". Процедуры без данных о заявках и ценах остаются в корпусе и в аудите, "
        "но их признаки усечены — это ограничение, а не основание для исключения.",
        "",
        "Таблицы: `results/tables/bias_audit_groups.csv`, "
        "`results/tables/bias_audit_feature_proxies.csv`, "
        "`results/tables/bias_audit_label_coverage.csv`; "
        "график: `results/figures/bias_audit.png`.",
    ]
    (REPORTS / "bias_audit.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
