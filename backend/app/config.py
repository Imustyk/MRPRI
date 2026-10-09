from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_PROCESSED = ROOT / "data" / "processed"
RESULTS = ROOT / "results"
TABLES_DIR = RESULTS / "tables"
MODELS_DIR = ROOT / "backend" / "models"
