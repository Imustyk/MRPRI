"""Step 25 (methodology cycle) - normative RAG layer: index + procedure sources.

Builds the explanation-with-sources layer required by the contract matrix:

1. Ingest the official corpus registered in ``src/mtender/rag.py`` (procurement
   law, AAP methodological material, official AAP interdiction register), split
   it into structural chunks (article / slide / register entry) with metadata,
   and persist ``results/rag/corpus_chunks.jsonl`` + ``results/rag/manifest.json``
   (URL, issuer, edition, download date, sha256 of every raw file).
2. Build a BM25 index over the chunks (no network at runtime - only the frozen
   local copies are used).
3. For **every procedure in the high/critical bands** produce an explanation:
   plain-language top-3 SHAP features of the production IsolationForest plus
   retrieved normative fragments with citations (act / article / verbatim
   quote). An explanation without any fragment above the relevance floor is
   recorded as ``coverage_ok = false`` - the matrix row requires 100%.
4. Emit ``results/rag/pipeline_summary.json`` with the coverage numbers that
   ``scripts/26_rag_eval.py`` and ``scripts/23_check_contract.py`` read.

Outputs:
    results/rag/corpus_chunks.jsonl
    results/rag/manifest.json
    results/rag/procedure_explanations.jsonl
    results/rag/pipeline_summary.json
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.mtender.config import DATA_FEATURES, MODELS, RESULTS  # noqa: E402
from src.mtender.rag import (  # noqa: E402
    BM25Index, DISCLAIMER, LEGAL_RAW, MIN_RELEVANCE_SCORE, SOURCES, load_corpus,
    relevant_hits,
)

ROOT = Path(__file__).resolve().parents[1]
RAG_DIR = RESULTS / "rag"
HIGH_MIN = 2       # n_models_flagging == 2 -> high
CRITICAL_MIN = 3   # n_models_flagging >= 3 -> critical


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _load_feature_text() -> dict[str, str]:
    path = ROOT / "scripts" / "17_explain_ocid.py"
    spec = importlib.util.spec_from_file_location("s17", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module.FEATURE_TEXT["ru"]


def band_of(n: int) -> str:
    return {0: "low", 1: "medium", 2: "high"}.get(int(n), "critical")


def build_corpus() -> tuple[list, BM25Index, dict]:
    chunks = load_corpus()
    if not chunks:
        raise SystemExit("corpus is empty - data/legal/raw is missing; see docs/rag_sources.md")
    RAG_DIR.mkdir(parents=True, exist_ok=True)
    with (RAG_DIR / "corpus_chunks.jsonl").open("w", encoding="utf-8") as fh:
        for c in chunks:
            fh.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")

    manifest = {"generated": "scripts/25_rag_pipeline.py", "sources": []}
    for src in SOURCES:
        files = []
        for name in src["files"]:
            p = LEGAL_RAW / name
            files.append({
                "file": name,
                "exists": p.exists(),
                "bytes": p.stat().st_size if p.exists() else None,
                "sha256": _sha256(p) if p.exists() else None,
            })
        entry = {k: src[k] for k in ("act_id", "title", "issuer", "kind", "url",
                                     "mirror_of", "edition", "downloaded_at", "units")}
        entry["files"] = files
        manifest["sources"].append(entry)
    by_act: dict[str, int] = {}
    for c in chunks:
        by_act[c.act_id] = by_act.get(c.act_id, 0) + 1
    manifest["chunks"] = {"total": len(chunks), "by_act": by_act}
    (RAG_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    index = BM25Index(chunks)
    print(f"corpus: {len(chunks)} chunks ({by_act})")
    return chunks, index, manifest


def explain_high_critical(index: BM25Index, feature_text: dict[str, str]) -> dict:
    scores = pd.read_csv(RESULTS / "tables" / "tender_anomaly_scores.csv",
                         usecols=["ocid", "n_models_flagging", "max_score"],
                         low_memory=False)
    flagged = scores[scores["n_models_flagging"] >= HIGH_MIN].copy()
    flagged["band"] = flagged["n_models_flagging"].map(band_of)

    bundle_cols = ["ocid"]
    features = pd.read_csv(DATA_FEATURES / "features.csv", low_memory=False)
    import joblib
    bundle = joblib.load(MODELS / "anomaly_models.joblib")
    iso, scaler = bundle["isolation_forest"], bundle["scaler"]
    feature_columns: list[str] = bundle["feature_columns"]

    merged = flagged.merge(features[bundle_cols + feature_columns], on="ocid",
                           how="left", validate="one_to_one")
    X = (merged[feature_columns].apply(pd.to_numeric, errors="coerce")
         .fillna(0.0).values.astype(float))
    xs = scaler.transform(X)

    import shap
    shap_v = -np.asarray(shap.TreeExplainer(iso).shap_values(xs))  # higher = more anomalous
    if isinstance(shap_v, list):
        shap_v = shap_v[0]

    out_path = RAG_DIR / "procedure_explanations.jsonl"
    n, covered = 0, 0
    band_total: dict[str, int] = {}
    band_covered: dict[str, int] = {}
    with out_path.open("w", encoding="utf-8") as fh:
        for i, row in merged.iterrows():
            vals = shap_v[i]
            top3 = np.argsort(-np.abs(vals))[:3]
            top_feats = [{
                "feature": feature_columns[j],
                "label": feature_text.get(feature_columns[j], feature_columns[j]),
                "shap": round(float(vals[j]), 4),
            } for j in top3]
            query = " ".join(f["label"] for f in top_feats) + " achizitie publica procedura legea 131"
            hits = relevant_hits(index, query, k=2)
            sources = [{
                "chunk_id": c.chunk_id, "act": c.act_title, "unit": c.unit,
                "unit_id": c.unit_id, "quote": c.text[:400], "score": round(s, 3),
            } for c, s in hits]
            band = row["band"]
            n += 1
            band_total[band] = band_total.get(band, 0) + 1
            if sources:
                covered += 1
                band_covered[band] = band_covered.get(band, 0) + 1
            fh.write(json.dumps({
                "ocid": row["ocid"],
                "band": band,
                "n_models_flagging": int(row["n_models_flagging"]),
                "max_score": float(row["max_score"]),
                "explanation": {
                    "method": "SHAP (IsolationForest), top-3 признака простым языком",
                    "top_features": top_feats,
                },
                "sources": sources,
                "coverage_ok": bool(sources),
                "disclaimer": DISCLAIMER,
            }, ensure_ascii=False) + "\n")

    summary = {
        "generated": "scripts/25_rag_pipeline.py",
        "population": "procedures with n_models_flagging >= 3 (critical) "
                      "or == 2 (high)",
        "n_high_critical": n,
        "coverage_share": round(covered / n, 6) if n else 0.0,
        "n_with_sources": covered,
        "by_band": {b: {"total": band_total[b],
                        "with_sources": band_covered.get(b, 0),
                        "coverage": round(band_covered.get(b, 0) / band_total[b], 6)}
                    for b in sorted(band_total)},
        "relevance_floor": MIN_RELEVANCE_SCORE,
        "outputs": ["results/rag/corpus_chunks.jsonl", "results/rag/manifest.json",
                    "results/rag/procedure_explanations.jsonl"],
        "disclaimer": DISCLAIMER,
    }
    (RAG_DIR / "pipeline_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"high/critical procedures: {n}; with sources: {covered} "
          f"({summary['coverage_share']:.4f})")
    return summary


def main() -> int:
    _, index, _ = build_corpus()
    feature_text = _load_feature_text()
    summary = explain_high_critical(index, feature_text)
    if summary["coverage_share"] < 1.0:
        print("NOTE: coverage < 100% - contract row B10 will be unmet until "
              "the corpus gaps are closed (docs/rag_sources.md)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
