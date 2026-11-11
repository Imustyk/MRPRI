"""CSV fallback preserves exported scores, quoted text and column identity."""
import csv

import pytest
import backend.app.store as store


@pytest.fixture
def score_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "TABLES_DIR", tmp_path)
    store._csv_scores.cache_clear()
    yield tmp_path / "tender_anomaly_scores.csv"
    store._csv_scores.cache_clear()


@pytest.mark.parametrize("name", ['Name, with comma', 'Name "quoted"', 'Name\nsecond line'])
def test_quoted_text_does_not_shift_scores(score_csv, name):
    with score_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ocid", "buyer_name", "max_score", "n_models_flagging", "consensus"])
        writer.writerow(["ocds-test", name, 0.8, 2, 0])
    row = store._csv_scores()["ocds-test"]
    assert row["buyer_name"] == name
    assert row["max_score"] == 0.8
    assert row["n_models_flagging"] == 2
    assert row["consensus"] == 0
    assert row["_source"] == "results/tables/tender_anomaly_scores.csv"


def test_literal_quote_in_unquoted_field_is_preserved(score_csv):
    score_csv.write_text('ocid,buyer_name,max_score\nx,Name "quoted",0.8\n', encoding="utf-8")
    assert store._csv_scores()["x"]["buyer_name"] == 'Name "quoted"'
    assert store._csv_scores()["x"]["max_score"] == 0.8


@pytest.mark.parametrize("data", ['x,Name,unexpected,0.8', 'x,Name'])
def test_mismatched_column_count_is_rejected(score_csv, data):
    score_csv.write_text("ocid,buyer_name,max_score\n" + data + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="field count"):
        store._csv_scores()
    assert store._csv_scores.cache_info().currsize == 0
