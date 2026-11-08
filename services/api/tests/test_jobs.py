from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def create_job(task: str = "report-generation") -> dict:
    response = client.post("/jobs", json={"task": task, "payload": {"month": "10"}})
    assert response.status_code == 201
    return response.json()


def test_create_job_returns_pending_job():
    job = create_job()
    assert job["task"] == "report-generation"
    assert job["status"] == "pending"
    assert job["payload"] == {"month": "10"}


def test_create_job_rejects_empty_task():
    response = client.post("/jobs", json={"task": ""})
    assert response.status_code == 422


def test_get_job():
    job = create_job()
    response = client.get(f"/jobs/{job['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == job["id"]


def test_get_unknown_job_returns_404():
    response = client.get(f"/jobs/{uuid4()}")
    assert response.status_code == 404


def test_list_jobs():
    create_job("task-a")
    create_job("task-b")
    response = client.get("/jobs")
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_cancel_pending_job():
    job = create_job()
    response = client.post(f"/jobs/{job['id']}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_cancel_twice_returns_409():
    job = create_job()
    client.post(f"/jobs/{job['id']}/cancel")
    response = client.post(f"/jobs/{job['id']}/cancel")
    assert response.status_code == 409


def test_cancel_unknown_job_returns_404():
    response = client.post(f"/jobs/{uuid4()}/cancel")
    assert response.status_code == 404


def test_create_job_publishes_message(publisher):
    job = create_job()
    assert [str(job_id) for job_id in publisher.published] == [job["id"]]


def test_queue_failure_returns_503_and_marks_job_failed(publisher):
    publisher.fail = True
    response = client.post("/jobs", json={"task": "report-generation"})
    assert response.status_code == 503
    jobs = client.get("/jobs").json()
    assert len(jobs) == 1
    assert jobs[0]["status"] == "failed"
