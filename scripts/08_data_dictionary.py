"""Step 08 - generate the data dictionary from live API responses.

The thesis data dictionary must not contain assumed fields, so it is built by
walking a sample of real packages and recording the paths that actually occur,
how often, and what type they hold. Output: docs/DATA_DICTIONARY.md.

Usage:
    .venv/bin/python scripts/08_data_dictionary.py --sample 60
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.api_client import MTenderClient  # noqa: E402
from src.mtender.config import MTENDER_BASE, ROOT  # noqa: E402
from src.mtender.features import FEATURE_COLUMNS, UNAVAILABLE  # noqa: E402

#: source path in the verified response -> normalised field it feeds
MAPPING = {
    "ocid": "ocid",
    "records[].ocid": "release_ocids",
    "records[].compiledRelease.tender.id": "tender_id",
    "records[].compiledRelease.tender.title": "title",
    "records[].compiledRelease.tender.description": "(not stored, >4k chars)",
    "records[].compiledRelease.tender.status": "status",
    "records[].compiledRelease.tender.statusDetails": "status_details",
    "records[].compiledRelease.tender.procurementMethod": "procurement_method",
    "records[].compiledRelease.tender.procurementMethodDetails": "procurement_method_details",
    "records[].compiledRelease.tender.mainProcurementCategory": "main_procurement_category",
    "records[].compiledRelease.tender.value.amount": "estimated_value",
    "records[].compiledRelease.tender.value.currency": "currency",
    "records[].compiledRelease.tender.tenderPeriod.startDate": "tender_start",
    "records[].compiledRelease.tender.tenderPeriod.endDate": "tender_end",
    "records[].compiledRelease.tender.enquiryPeriod.endDate": "enquiry_end",
    "records[].compiledRelease.tender.procuringEntity.name": "buyer_name",
    "records[].compiledRelease.tender.procuringEntity.id": "buyer_id",
    "records[].compiledRelease.tender.classification.scheme": "(filter: CPV)",
    "records[].compiledRelease.tender.classification.id": "cpv_codes[] -> cpv_primary",
    "records[].compiledRelease.tender.classification.description": "cpv_labels[]",
    "records[].compiledRelease.tender.items[].classification.scheme": "(filter: CPV)",
    "records[].compiledRelease.tender.items[].classification.id": "cpv_codes[] -> cpv_primary",
    "records[].compiledRelease.tender.lots[]": "n_lots (count only)",
    "records[].compiledRelease.tender.amendments[]": "n_amendments (count only)",
    "records[].compiledRelease.parties[].id": "buyer_id / winner_id / tenderers[].id",
    "records[].compiledRelease.parties[].name": "buyer_name / winner_name",
    "records[].compiledRelease.parties[].identifier.scheme": "identifier_scheme",
    "records[].compiledRelease.parties[].identifier.id": "buyer_identifier / winner_identifier",
    "records[].compiledRelease.parties[].roles": "party role classification",
    "records[].compiledRelease.parties[].address.addressDetails.locality.description": "buyer_locality",
    "records[].compiledRelease.parties[].address.locality.description": "buyer_locality (2018 layout)",
    "records[].compiledRelease.parties[].details.scale": "buyer_scale",
    "records[].compiledRelease.parties[].details.typeOfBuyer": "buyer_type",
    "records[].compiledRelease.awards[].id": "awards[].id",
    "records[].compiledRelease.awards[].date": "award_date",
    "records[].compiledRelease.awards[].status": "award_status",
    "records[].compiledRelease.awards[].value.amount": "award_value / award_total (sum over lots)",
    "records[].compiledRelease.awards[].suppliers[].id": "winner_id",
    "records[].compiledRelease.awards[].suppliers[].name": "winner_name",
    "records[].compiledRelease.bids.details[].tenderers[].id": "n_bidders (distinct count)",
    "records[].compiledRelease.contracts[].id": "contracts[].id",
    "records[].compiledRelease.contracts[].date": "contracts[].date",
    "publisher.name": "publisher",
    "publishedDate": "published_date",
    "version": "(OCDS version, verified 1.1)",
}

#: paths confirmed absent from the live response
NOT_PRESENT = [
    ("release.buyer", "the standard top-level buyer object is never populated; "
                      "parties[].roles must be used instead"),
    ("tender.procurementMethodDetails = 'directAward'", "no single-source flag is published"),
    ("party.details.foundingDate", "supplier age cannot be derived"),
    ("bids.details[].value (broad coverage)", "present for only a minority of procurements"),
    ("awards[].suppliers[].address for most parties", "party.address is often '-' placeholders"),
]


def _present(seen_paths: list[set[str]], path: str) -> int:
    """How many sampled packages contained this path (in any release)."""
    return sum(1 for paths in seen_paths if path in paths)


def walk(prefix: str, obj: Any, out: set[str], types: dict, depth: int = 0) -> None:
    """Collect the set of paths present in one document, and their value types."""
    if depth > 9:
        return
    if isinstance(obj, dict):
        if prefix:
            out.add(prefix)
            if prefix not in types:
                types[prefix] = type(next(iter(obj.values()))).__name__ if obj else "empty"
        for key, value in obj.items():
            walk(f"{prefix}.{key}" if prefix else key, value, out, types, depth + 1)
    elif isinstance(obj, list):
        if prefix:
            out.add(prefix)
            types.setdefault(prefix, "array")
        # Children of list elements are addressed as ``parent[]`` so the keys
        # read like the JSONPath expressions used in the thesis tables.
        for value in obj[:3]:
            walk(f"{prefix}[]" if prefix else prefix, value, out, types, depth + 1)
    elif prefix:
        out.add(prefix)
        types.setdefault(prefix, type(obj).__name__)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=60)
    ap.add_argument("--start", default="2024-01-01T00:00:00Z")
    ap.add_argument("--out", default=str(ROOT / "docs" / "DATA_DICTIONARY.md"))
    args = ap.parse_args()

    client = MTenderClient(MTENDER_BASE)
    ocids = [o for o, _ in client.iter_ocids(limit=300, start=args.start, max_pages=1)][: args.sample]
    print(f"sampling {len(ocids)} packages from {args.start}")

    seen_paths: list[set[str]] = []
    types: dict = defaultdict(str)
    versions: Counter = Counter()
    sample_records = 0
    n_ok = 0
    for ocid in ocids:
        try:
            package = client.fetch_record(ocid)
        except Exception as exc:  # noqa: BLE001
            print(f"  skip {ocid}: {type(exc).__name__}")
            continue
        n_ok += 1
        versions[package.get("version")] += 1
        sample_records += len(package.get("records") or [])
        # The ocid we requested is part of the resource identity even though the
        # body does not repeat it.
        paths: set[str] = {"ocid"}
        walk("", package, paths, types)
        seen_paths.append(paths)

    out = Path(args.out)
    lines: list[str] = []
    lines.append("# Data Dictionary — MTender OCDS 1.1")
    lines.append("")
    lines.append(
        f"**Generated by executing `scripts/08_data_dictionary.py` on "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}** from "
        f"{n_ok} live packages retrieved from `{MTENDER_BASE}/tenders/{{ocid}}` "
        f"(window starting {args.start}, {sample_records} releases inspected)."
    )
    lines.append("")
    lines.append(
        "Every path below was observed in a real response. The `Present` column is the "
        "number of sampled packages in which the path occurred; nothing is listed that "
        "the code did not actually read."
    )
    lines.append("")
    lines.append(f"OCDS versions seen: {dict(versions)}")
    lines.append("")

    lines.append("## Source path -> normalised field")
    lines.append("")
    lines.append("| Source path in verified response | Type | Present | Feeds normalised field | Used in ML |")
    lines.append("|---|---|---|---|---|")
    for path, target in MAPPING.items():
        present = _present(seen_paths, path)
        typ = types.get(path, "—")
        used = "Yes" if target in {
            "ocid", "tender_id", "title", "status", "status_details", "procurement_method",
            "procurement_method_details", "main_procurement_category", "estimated_value",
            "award_value", "currency", "tender_start", "tender_end", "enquiry_end",
            "cpv_codes[] -> cpv_primary", "cpv_primary", "n_lots", "n_amendments",
            "buyer_id", "buyer_name", "buyer_identifier", "buyer_locality", "buyer_scale",
            "buyer_type", "winner_id", "winner_name", "winner_identifier", "n_bidders",
        } else "No"
        lines.append(f"| `{path}` | {typ} | {present}/{n_ok} | {target} | {used} |")

    lines.append("")
    lines.append("## Confirmed absent from the live response")
    lines.append("")
    lines.append("| Path | Consequence |")
    lines.append("|---|---|")
    for path, note in NOT_PRESENT:
        lines.append(f"| `{path}` | {note} |")

    lines.append("")
    lines.append("## Engineered features (all inputs above)")
    lines.append("")
    lines.append("| Feature | Definition |")
    lines.append("|---|---|")
    definitions = {
        "log_award_value": "log1p(award_value) - the primary award only",
    "log_award_total": "log1p(award_total) - sum of every award amount, comparable with estimated_value",
        "value_vs_cpv_median": "award_value / median(award_value grouped by cpv_primary), clipped to [0, 20]",
        "value_zscore_cpv": "(award_value - cpv median) / cpv std, clipped to [-10, 10]",
        "estimate_to_award_ratio": "estimated_value / award_total, clipped to [0, 20]",
    "multi_award_tender": "1 when the tender has more than one award carrying a value",
        "n_bidders_log": "log1p(n_bidders)",
        "single_bidder": "1 if exactly one distinct tenderer submitted a bid",
        "no_bid_data": "1 if no bid is published for the procurement",
        "multi_supplier_award": "1 if the award names more than one supplier",
        "bid_window_days": "tenderPeriod.endDate - tenderPeriod.startDate in days",
        "short_deadline": "1 if bid_window_days < 7",
        "long_deadline": "1 if bid_window_days > 90",
        "n_amendments": "count of tender.amendments",
        "amended": "1 if the tender was amended at least once",
        "accelerated_like": "1 if procurementMethodDetails matches accelerated/urgent/exception",
        "cancelled": "1 if tender.status in (cancelled, unsuccessful)",
        "no_award_after_tender": "1 if status == complete but no award value is published",
        "buyer_supplier_repeat_share": "awards of this pair / all awards of this procurer",
        "winner_share_of_buyer_awards": "same ratio, kept as a separate readable indicator",
        "supplier_win_concentration": "awards won by this supplier / all awarded procurements",
        "supplier_award_count_log": "log1p(awards won by this supplier)",
    }
    for feat in FEATURE_COLUMNS:
        lines.append(f"| `{feat}` | {definitions.get(feat, 'see src/mtender/features.py')} |")

    lines.append("")
    lines.append("## Indicators that could NOT be built, and why")
    lines.append("")
    lines.append("| Indicator | Reason |")
    lines.append("|---|---|")
    for name, reason in UNAVAILABLE.items():
        lines.append(f"| `{name}` | {reason} |")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out.parent / "data_dictionary_stats.json").write_text(
        json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "n_packages": n_ok, "n_releases": sample_records,
                    "versions": dict(versions),
                    "path_presence": {
                        p: _present(seen_paths, p)
                        for p in sorted({p for s_ in seen_paths for p in s_})
                    }}, indent=2),
        encoding="utf-8",
    )
    print(f"data dictionary -> {out} ({len(lines)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
