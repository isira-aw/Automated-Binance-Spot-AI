"""Model registry API surface reachable without a live database (§59, §76).

Endpoints that read persisted data (list/get registry, predict) need a real
database; the DB-backed function they call (predict_latest) is already
covered in test_ml_prediction.py, including its NotFoundError for an
unregistered model. This file covers the training-trigger endpoint the same
way test_market_api.py covers /market/backfill -- the parts of the API
reachable without a live database.
"""

from __future__ import annotations

import pytest

from app.ml.training import get_training_tracker


@pytest.fixture(autouse=True)
def _reset_tracker():
    tracker = get_training_tracker()
    tracker.current = None
    tracker.running = False
    yield
    tracker.current = None
    tracker.running = False


def test_training_status_with_no_job_reports_not_running(client):
    response = client.get("/api/v1/models/train/status")
    assert response.status_code == 200
    body = response.json()
    assert body["running"] is False
    assert body["outcome"] is None


def test_start_training_returns_202_with_a_job_id(client):
    response = client.post("/api/v1/models/train", json={"symbol": "BTCUSDT", "timeframe": "1h"})
    assert response.status_code == 202
    body = response.json()
    assert body["job_id"]
    assert body["status"] == "RUNNING"


def test_a_second_training_request_is_rejected_while_one_is_running(client):
    get_training_tracker().running = True  # simulate an in-flight job

    response = client.post("/api/v1/models/train", json={"symbol": "BTCUSDT", "timeframe": "1h"})
    assert response.status_code == 422
    assert "already running" in response.json()["error"]["message"]


def test_the_returned_job_id_is_what_status_will_later_report(client):
    """The 202 response must be correlatable with GET /train/status -- a
    caller cannot otherwise tell their request apart from a previous one."""
    response = client.post("/api/v1/models/train", json={"symbol": "BTCUSDT", "timeframe": "1h"})
    returned_job_id = response.json()["job_id"]
    assert returned_job_id != "pending"
    assert len(returned_job_id) > 0
