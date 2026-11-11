from fastapi.testclient import TestClient

from backend.app import store
from backend.app.main import app


def test_combines_tender_filters_before_pagination(monkeypatch):
    rows = [
        {"tender_id": "match", "published_at": "2024-03-31T12:00:00Z",
         "award_total_mdl": 0, "cpv_code": "30100000-0", "risk_score": 0},
        {"tender_id": "outside-date", "published_at": "2024-04-01T00:00:00Z",
         "award_total_mdl": 0, "cpv_code": "30100000-0", "risk_score": 0},
        {"tender_id": "missing-value", "published_at": "2024-03-31T12:00:00Z",
         "award_total_mdl": None, "cpv_code": "30100000-0", "risk_score": 0},
        {"tender_id": "other-category", "published_at": "2024-03-31T12:00:00Z",
         "award_total_mdl": 0, "cpv_code": "45100000-0", "risk_score": 0},
        {"tender_id": "unscored", "published_at": "2024-03-31T12:00:00Z",
         "award_total_mdl": 0, "cpv_code": "30100000-0", "risk_score": None},
    ]
    monkeypatch.setattr(store, "artefacts_ready", lambda: True)
    monkeypatch.setattr(store, "load_tenders", lambda: rows)
    client = TestClient(app)
    params = {"date_from": "2024-03-31", "date_to": "2024-03-31", "max_value": 0,
              "cpv": "30", "scored": "true", "limit": 1}
    response = client.get("/api/tenders", params=params)
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["tender_id"] == "match"
    assert client.get("/api/tenders", params={**params, "offset": 1}).json() == {
        "total": 1, "items": [],
    }
    assert client.get("/api/tenders", params={**params, "scored": "false"}).json()["items"][0][
        "tender_id"
    ] == "unscored"


def test_invalid_ranges_return_validation_error(monkeypatch):
    monkeypatch.setattr(store, "artefacts_ready", lambda: True)
    monkeypatch.setattr(store, "load_tenders", lambda: [])
    client = TestClient(app)
    assert client.get("/api/tenders?date_from=2024-05-01&date_to=2024-04-30").status_code == 422
    assert client.get("/api/tenders?min_value=1&max_value=0").status_code == 422
    assert client.get("/api/tenders?cpv=abc").status_code == 422


def test_concurrent_case_creation_allocates_unique_references(monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from src.mtender import workspace

    monkeypatch.setattr(workspace, "WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(workspace, "DB_PATH", tmp_path / "workspace.db")
    client = TestClient(app)
    assert client.get("/api/workspace/cases").status_code == 200
    barrier = Barrier(12)

    def create(index):
        barrier.wait(timeout=10)
        return client.post("/api/workspace/cases", json={"title": f"Parallel case {index}"})

    with ThreadPoolExecutor(max_workers=12) as executor:
        responses = list(executor.map(create, range(12)))
    assert [response.status_code for response in responses] == [201] * 12
    assert len({response.json()["ref"] for response in responses}) == 12
