"""Generate a realistic synthetic Moldova public-procurement dataset.

The generator mixes ordinary competitive tenders with planted red-flag
patterns so the anomaly detector has a known ground-truth subset for
evaluation (thesis Chapter 3). It is not a dump of real MTender records.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

RANDOM_SEED = 1312015  # Law No. 131/2015

BUYERS = [
    {"id": "MD-10001", "name": "Ministerul Sănătății", "locality": "Chișinău", "type": "ministry"},
    {"id": "MD-10002", "name": "Ministerul Educației și Cercetării", "locality": "Chișinău", "type": "ministry"},
    {"id": "MD-10003", "name": "Ministerul Infrastructurii și Dezvoltării Regionale", "locality": "Chișinău", "type": "ministry"},
    {"id": "MD-10004", "name": "Ministerul Afacerilor Interne", "locality": "Chișinău", "type": "ministry"},
    {"id": "MD-10005", "name": "Primăria municipiului Chișinău", "locality": "Chișinău", "type": "municipality"},
    {"id": "MD-10006", "name": "Primăria municipiului Bălți", "locality": "Bălți", "type": "municipality"},
    {"id": "MD-10007", "name": "Primăria municipiului Cahul", "locality": "Cahul", "type": "municipality"},
    {"id": "MD-10008", "name": "Consiliul Raional Orhei", "locality": "Orhei", "type": "rayon"},
    {"id": "MD-10009", "name": "Consiliul Raional Ungheni", "locality": "Ungheni", "type": "rayon"},
    {"id": "MD-10010", "name": "Spitalul Clinic Republican", "locality": "Chișinău", "type": "hospital"},
    {"id": "MD-10011", "name": "Universitatea de Stat din Moldova", "locality": "Chișinău", "type": "university"},
    {"id": "MD-10012", "name": "Agenția de Stat pentru Resurse Minerale", "locality": "Chișinău", "type": "agency"},
    {"id": "MD-10013", "name": "Î.S. Calea Ferată din Moldova", "locality": "Chișinău", "type": "soe"},
    {"id": "MD-10014", "name": "Primăria orașului Comrat", "locality": "Comrat", "type": "municipality"},
    {"id": "MD-10015", "name": "Direcția Generală Educație Chișinău", "locality": "Chișinău", "type": "agency"},
]

CPV = [
    {"code": "33100000-1", "label": "Echipamente medicale", "median": 420_000},
    {"code": "45000000-7", "label": "Lucrări de construcții", "median": 2_800_000},
    {"code": "72000000-5", "label": "Servicii IT", "median": 380_000},
    {"code": "09000000-3", "label": "Produse petroliere", "median": 1_100_000},
    {"code": "15000000-8", "label": "Produse alimentare", "median": 240_000},
    {"code": "30000000-9", "label": "Echipamente de birou", "median": 95_000},
    {"code": "34000000-7", "label": "Vehicule", "median": 890_000},
    {"code": "50000000-5", "label": "Servicii de reparații", "median": 160_000},
    {"code": "60000000-8", "label": "Servicii de transport", "median": 210_000},
    {"code": "80000000-4", "label": "Servicii de educație", "median": 130_000},
    {"code": "90910000-9", "label": "Servicii de curățenie", "median": 85_000},
    {"code": "44110000-4", "label": "Materiale de construcții", "median": 310_000},
]

PROCEDURES = [
    ("open", 0.62),
    ("restricted", 0.12),
    ("negotiated", 0.10),
    ("small_value", 0.16),
]

STATUSES = [("complete", 0.78), ("cancelled", 0.08), ("active", 0.14)]

BIDDER_NAMES = [
    "SRL Construct Nord",
    "SRL MedFarm Plus",
    "SRL SoftMoldova",
    "SRL AgroComert",
    "SRL TransLogis",
    "SRL EcoClean",
    "SRL OfficeTrade",
    "SRL AutoPark",
    "SRL PetroLux",
    "SRL EduServicii",
    "SRL Drumuri Moderne",
    "SRL Clinic Supply",
    "SRL DataNet",
    "SRL Panificație Est",
    "SRL Beton Pro",
    "SRL GuardForce",
    "SRL PrintHouse",
    "SRL GreenEnergy",
    "ÎI Popescu Ion",
    "SRL Universal Grup",
    "SRL Delta Build",
    "SRL PharmaImport",
    "SRL CloudNine",
    "SRL MeatTrade",
    "SRL FuelExpress",
    "SRL SchoolBooks",
    "SRL Asfalt Tehnic",
    "SRL SterilMed",
    "SRL NetCom",
    "SRL Lactis",
    "SRL Favored One",
    "SRL Twin Bid A",
    "SRL Twin Bid B",
    "SRL Threshold Split",
    "SRL Rapid Award",
]


def _weighted_choice(rng: random.Random, pairs: list[tuple[str, float]]) -> str:
    labels, weights = zip(*pairs)
    return rng.choices(list(labels), weights=list(weights), k=1)[0]


def _idno(rng: random.Random) -> str:
    return "".join(str(rng.randint(0, 9)) for _ in range(13))


def generate_procurement_frame(n_tenders: int = 1200, seed: int = RANDOM_SEED) -> pd.DataFrame:
    rng = random.Random(seed)
    bidders = []
    for i, name in enumerate(BIDDER_NAMES):
        bidders.append(
            {
                "bidder_id": f"BID-{i+1:03d}",
                "bidder_name": name,
                "idno": _idno(rng),
                "locality": rng.choice(["Chișinău", "Bălți", "Cahul", "Orhei", "Ungheni", "Comrat"]),
                "founding_year": rng.randint(2004, 2024),
            }
        )

    # Shared contact cluster for collusion pattern
    for idx in (31, 32):  # Twin Bid A/B
        bidders[idx]["phone"] = "+373-22-555-010"
        bidders[idx]["address"] = "str. Ismail 42, Chișinău"
    for b in bidders:
        b.setdefault("phone", f"+373-22-{rng.randint(100,999)}-{rng.randint(100,999)}")
        b.setdefault("address", f"str. {rng.choice(['Ștefan cel Mare','București','Pushkin','Decebal'])} {rng.randint(1,180)}")

    start = datetime(2022, 1, 10)
    rows: list[dict] = []
    planted: dict[str, str] = {}

    for i in range(n_tenders):
        buyer = rng.choice(BUYERS)
        cpv = rng.choice(CPV)
        procedure = _weighted_choice(rng, PROCEDURES)
        status = _weighted_choice(rng, STATUSES)
        published = start + timedelta(days=rng.randint(0, 980))
        bid_window = rng.randint(12, 40)
        n_bids = max(1, int(rng.gauss(4.2, 1.8)))
        n_bids = min(n_bids, 12)
        value = max(18_000, rng.gauss(cpv["median"], cpv["median"] * 0.28))
        pattern = "normal"

        # --- planted red-flag patterns (~14% of rows) ---
        roll = rng.random()
        if roll < 0.04:
            pattern = "single_bidder"
            n_bids = 1
            procedure = rng.choice(["negotiated", "small_value", "open"])
            bid_window = rng.randint(3, 8)
        elif roll < 0.07:
            pattern = "price_outlier"
            value = cpv["median"] * rng.uniform(2.4, 4.8)
            n_bids = rng.randint(1, 3)
        elif roll < 0.09:
            pattern = "short_deadline"
            bid_window = rng.randint(2, 6)
            n_bids = rng.randint(1, 2)
        elif roll < 0.11:
            pattern = "repeat_winner"
            n_bids = rng.randint(1, 3)
            buyer = BUYERS[0]  # Ministry of Health lock-in
        elif roll < 0.125:
            pattern = "bid_rotation"
            n_bids = 3
        elif roll < 0.14:
            pattern = "lot_splitting"
            value = rng.uniform(190_000, 248_000)  # just below a typical threshold
            procedure = "small_value"
            n_bids = rng.randint(1, 2)
        elif roll < 0.15:
            pattern = "round_price"
            value = rng.choice([100_000, 250_000, 500_000, 1_000_000, 2_000_000])
            n_bids = rng.randint(1, 3)

        chosen = rng.sample(bidders, k=n_bids)
        if pattern == "repeat_winner":
            chosen[0] = bidders[30]  # Favored One
        elif pattern == "bid_rotation":
            chosen = [bidders[31], bidders[32], rng.choice(bidders[:20])]
        elif pattern == "lot_splitting":
            chosen[0] = bidders[33]
        elif pattern == "short_deadline":
            chosen[0] = bidders[34]

        winner = chosen[0]
        winner_share = rng.uniform(0.72, 0.98) if n_bids == 1 else rng.uniform(0.51, 0.88)
        winner_price = round(value * winner_share, 2)
        bids = []
        remaining = value - winner_price
        for j, bidder in enumerate(chosen):
            if j == 0:
                price = winner_price
            else:
                bump = remaining / max(n_bids - 1, 1) * rng.uniform(1.02, 1.35)
                price = round(winner_price + bump, 2)
            bids.append(
                {
                    "bidder_id": bidder["bidder_id"],
                    "bidder_name": bidder["bidder_name"],
                    "idno": bidder["idno"],
                    "price": price,
                    "is_winner": j == 0,
                }
            )

        tender_id = f"ocds-md-{published.year}-{i+1:05d}"
        if pattern != "normal":
            planted[tender_id] = pattern

        deadline = published + timedelta(days=bid_window)
        award_date = deadline + timedelta(days=rng.randint(3, 25))
        rows.append(
            {
                "tender_id": tender_id,
                "ocid": tender_id,
                "title": f"{cpv['label']} — {buyer['name']}",
                "buyer_id": buyer["id"],
                "buyer_name": buyer["name"],
                "buyer_locality": buyer["locality"],
                "buyer_type": buyer["type"],
                "cpv_code": cpv["code"],
                "cpv_label": cpv["label"],
                "procedure": procedure,
                "status": status,
                "published_at": published.date().isoformat(),
                "bid_deadline": deadline.date().isoformat(),
                "award_date": award_date.date().isoformat(),
                "bid_window_days": bid_window,
                "n_bids": n_bids,
                "estimated_value_mdl": round(value, 2),
                "award_value_mdl": winner_price,
                "currency": "MDL",
                "winner_id": winner["bidder_id"],
                "winner_name": winner["bidder_name"],
                "winner_idno": winner["idno"],
                "winner_locality": winner["locality"],
                "winner_founding_year": winner["founding_year"],
                "winner_phone": winner["phone"],
                "winner_address": winner["address"],
                "bids_json": json.dumps(bids, ensure_ascii=False),
                "planted_pattern": pattern,
                "is_planted_anomaly": pattern != "normal",
            }
        )

    return pd.DataFrame(rows)


def save_raw(df: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    out = root / "data" / "raw" / "tenders_synthetic.csv"
    frame = generate_procurement_frame()
    save_raw(frame, out)
    print(f"Wrote {len(frame)} tenders to {out}")
    print(frame["planted_pattern"].value_counts().to_string())
