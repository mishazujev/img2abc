import os
import time
from pathlib import Path

HERE = Path(__file__).parent
os.environ["AUDIVERIS_BIN"] = str(HERE / "fake_audiveris.sh")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
SAMPLE = HERE.parent / "static" / "samples" / "sample.png"


def wait(job_id):
    for _ in range(100):
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("done", "error"):
            return j
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def test_health():
    assert client.get("/api/health").json()["omr"] is True


def test_index_served():
    r = client.get("/")
    assert r.status_code == 200 and "Score2ABC" in r.text


def test_image_job_roundtrip():
    with SAMPLE.open("rb") as fh:
        r = client.post("/api/jobs", files=[("files", ("page1.png", fh, "image/png"))])
    assert r.status_code == 200, r.text
    j = wait(r.json()["id"])
    assert j["status"] == "done", j
    assert "T:Fixture Piece" in j["abc"]
    x = client.get(f"/api/jobs/{j['id']}/musicxml/0")
    assert x.status_code == 200 and x.content[:2] == b"PK"


def test_rejects_unknown_type():
    r = client.post("/api/jobs", files=[("files", ("notes.txt", b"hello", "text/plain"))])
    assert r.status_code == 400
    assert "Unsupported" in r.json()["error"]


def test_musicxml_direct():
    with (HERE / "fixtures" / "piano.mxl").open("rb") as fh:
        r = client.post("/api/musicxml", files={"file": ("piano.mxl", fh)})
    assert r.status_code == 200
    assert r.json()["abc"].startswith("X:1")


def test_bad_musicxml():
    r = client.post("/api/musicxml", files={"file": ("bad.xml", b"<nope", "text/xml")})
    assert r.status_code == 422
