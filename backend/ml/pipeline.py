"""End-to-end pipeline: ingest → features → detect → graph → artefacts."""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
import pandas as pd

from .detect import evaluate_against_planted, fit_detectors, save_models, score_frame
from .features import FEATURE_COLUMNS, engineer_features
from .generate_data import generate_procurement_frame, save_raw
from .ocds_loader import load_ocds

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
MODELS = ROOT / "backend" / "models"


def _build_graph(df: pd.DataFrame) -> dict:
    g = nx.Graph()
    for _, row in df.iterrows():
        b_id, w_id = row["buyer_id"], row["winner_id"]
        g.add_node(b_id, kind="buyer", name=row["buyer_name"], locality=row["buyer_locality"])
        g.add_node(w_id, kind="bidder", name=row["winner_name"], locality=row["winner_locality"])
        if g.has_edge(b_id, w_id):
            g[b_id][w_id]["weight"] += 1
            g[b_id][w_id]["value"] += float(row["award_value_mdl"])
            g[b_id][w_id]["max_risk"] = max(g[b_id][w_id]["max_risk"], float(row["risk_score"]))
        else:
            g.add_edge(
                b_id,
                w_id,
                weight=1,
                value=float(row["award_value_mdl"]),
                max_risk=float(row["risk_score"]),
            )

    # Keep the most suspicious edges so the UI stays readable
    edges_sorted = sorted(g.edges(data=True), key=lambda e: e[2]["max_risk"], reverse=True)[:180]
    keep_nodes = {u for u, v, _ in edges_sorted} | {v for u, v, _ in edges_sorted}
    nodes = []
    for n in keep_nodes:
        data = g.nodes[n]
        nodes.append(
            {
                "id": n,
                "kind": data.get("kind"),
                "name": data.get("name"),
                "locality": data.get("locality"),
                "degree": int(g.degree(n)),
            }
        )
    links = [
        {
            "source": u,
            "target": v,
            "weight": d["weight"],
            "value": round(d["value"], 2),
            "max_risk": round(d["max_risk"], 1),
        }
        for u, v, d in edges_sorted
    ]
    return {"nodes": nodes, "links": links}


def _stats(df: pd.DataFrame, metrics: dict) -> dict:
    high = df[df["risk_score"] >= 55]
    return {
        "n_tenders": int(len(df)),
        "n_buyers": int(df["buyer_id"].nunique()),
        "n_winners": int(df["winner_id"].nunique()),
        "total_award_mdl": float(df["award_value_mdl"].sum()),
        "high_risk_count": int(len(high)),
        "high_risk_value_mdl": float(high["award_value_mdl"].sum()),
        "single_bidder_share": float((df["single_bidder"] == 1).mean()),
        "mean_n_bids": float(df["n_bids"].mean()),
        "mean_risk": float(df["risk_score"].mean()),
        "level_counts": df["risk_level"].value_counts().to_dict(),
        "procedure_counts": df["procedure"].value_counts().to_dict(),
        "top_cpv": (
            df.groupby("cpv_label")
            .agg(n=("tender_id", "count"), avg_risk=("risk_score", "mean"), value=("award_value_mdl", "sum"))
            .reset_index()
            .sort_values("avg_risk", ascending=False)
            .head(8)
            .to_dict(orient="records")
        ),
        "monthly": (
            pd.to_datetime(df["published_at"])
            .dt.to_period("M")
            .astype(str)
            .to_frame("month")
            .join(df[["risk_score", "award_value_mdl"]])
            .groupby("month")
            .agg(n=("risk_score", "count"), avg_risk=("risk_score", "mean"), value=("award_value_mdl", "sum"))
            .reset_index()
            .to_dict(orient="records")
        ),
        "top_risky_buyers": (
            df.groupby(["buyer_id", "buyer_name"])
            .agg(n=("tender_id", "count"), avg_risk=("risk_score", "mean"), high=("risk_score", lambda s: int((s >= 55).sum())))
            .reset_index()
            .sort_values("avg_risk", ascending=False)
            .head(8)
            .to_dict(orient="records")
        ),
        "metrics": metrics,
        "features": FEATURE_COLUMNS,
    }


def run_pipeline(
    source: str = "synthetic",
    ocds_path: str | None = None,
    n_tenders: int = 1200,
) -> dict:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    MODELS.mkdir(parents=True, exist_ok=True)

    if source == "ocds":
        if not ocds_path:
            raise ValueError("ocds_path is required when source='ocds'")
        df = load_ocds(Path(ocds_path))
    else:
        csv_path = RAW_DIR / "tenders_synthetic.csv"
        df = generate_procurement_frame(n_tenders=n_tenders)
        save_raw(df, csv_path)

    featured = engineer_features(df)
    X = featured[FEATURE_COLUMNS].to_numpy(dtype=float)
    models = fit_detectors(X)
    scored = score_frame(featured, models)
    metrics = evaluate_against_planted(scored)
    graph = _build_graph(scored)
    stats = _stats(scored, metrics)

    save_models(models, MODELS / "detectors.joblib")
    scored.to_csv(PROCESSED / "tenders_scored.csv", index=False)

    # Compact JSON for the API (drop bulky unused columns)
    records = json.loads(
        scored.sort_values("risk_score", ascending=False).to_json(orient="records", force_ascii=False)
    )
    (PROCESSED / "tenders.json").write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    (PROCESSED / "stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    (PROCESSED / "graph.json").write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
    meta = {
        "source": source,
        "n_tenders": int(len(scored)),
        "feature_columns": FEATURE_COLUMNS,
        "model": "IsolationForest + LOF + rule layer",
        "hybrid_weights": {"isolation_forest": 0.40, "lof": 0.15, "rules": 0.45},
    }
    (PROCESSED / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {"ok": True, "n": int(len(scored)), "metrics": metrics, "source": source}


if __name__ == "__main__":
    result = run_pipeline()
    print(json.dumps(result, indent=2))
