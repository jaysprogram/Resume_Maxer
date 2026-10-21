"""The web app end to end, through FastAPI's test client, with a fake tailor."""

import pytest
from anthropic.types import Usage
from fastapi.testclient import TestClient

from resume_maxer.auth import LoginLimiter, hash_password
from resume_maxer.claude import Answer
from resume_maxer.pipeline import Attempt, Tailored
from resume_maxer.resume_doc import ResumeDoc
from resume_maxer.web import ConfigError, WebConfig, create_app

PASSWORD = "correct horse battery"
HASH = hash_password(PASSWORD)  # once per module: scrypt is slow on purpose
SECRET = "s" * 48


@pytest.fixture
def make_client(tmp_path, sample_doc_data):
    def make(tailor_fn=None, secure=False, limiter=None):
        def fake(posting):
            return Tailored(
                doc=ResumeDoc.model_validate(sample_doc_data),
                pdf=b"%PDF-web",
                failures=[],
                flags=[],
                attempts=[
                    Attempt(
                        Answer(
                            parsed=None, stop_reason="completed",
                            usage=Usage(input_tokens=0, output_tokens=0),
                            cost_usd=0.07, request_id=None,
                        ),
                        None,
                        None,
                    )
                ],
            )  # fmt: skip

        config = WebConfig(HASH, SECRET, runs_dir=tmp_path / "runs", secure_cookies=secure)
        app = create_app(config, tailor_fn or fake, limiter)
        return TestClient(app, follow_redirects=False)

    return make


def sign_in(client):
    response = client.post("/login", data={"password": PASSWORD})
    assert response.status_code == 303 and response.headers["location"] == "/"
    return response


def test_every_page_but_login_needs_a_session(make_client):
    client = make_client()
    for method, path in [("get", "/"), ("post", "/runs"), ("get", "/runs/" + "a" * 32)]:
        response = getattr(client, method)(path)
        assert response.status_code == 303 and response.headers["location"] == "/login"
    assert client.get("/login").status_code == 200
    assert client.get("/healthz").json() == {"ok": True}


def test_no_api_docs_are_published(make_client):
    client = make_client()
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_wrong_password_is_refused_and_right_one_signs_in(make_client):
    client = make_client()
    wrong = client.post("/login", data={"password": "nope"})
    assert wrong.status_code == 401 and "Wrong password." in wrong.text
    sign_in(client)
    assert client.get("/").status_code == 200


def test_guessing_is_rate_limited(make_client):
    client = make_client(limiter=LoginLimiter(limit=3, window_s=900))
    for _ in range(3):
        assert client.post("/login", data={"password": "nope"}).status_code == 401
    blocked = client.post("/login", data={"password": PASSWORD})  # even the right one
    assert blocked.status_code == 429 and "Too many attempts" in blocked.text


def test_paste_run_and_download(make_client):
    client = make_client()
    sign_in(client)
    created = client.post("/runs", data={"posting": "We want Go.", "label": "Acme SWE"})
    assert created.status_code == 303
    run_url = created.headers["location"]
    client.app.state.store.wait_idle()

    page = client.get(run_url)
    assert page.status_code == 200
    assert "Every check passed" in page.text and 'http-equiv="refresh"' not in page.text
    pdf = client.get(run_url + "/resume.pdf")
    assert pdf.status_code == 200 and pdf.content == b"%PDF-web"
    assert pdf.headers["content-type"] == "application/pdf"
    # A name with a space is sent in the standard encoded form (RFC 6266).
    assert "filename*=utf-8''Acme%20SWE.pdf" in pdf.headers["content-disposition"]
    assert "Acme SWE" in client.get("/").text  # listed under recent runs


def test_pending_run_page_refreshes_itself(make_client):
    import threading

    release = threading.Event()

    def slow(posting):
        release.wait(5)
        raise RuntimeError("stopped")

    client = make_client(tailor_fn=slow)
    sign_in(client)
    run_url = client.post("/runs", data={"posting": "We want Go."}).headers["location"]
    assert 'http-equiv="refresh"' in client.get(run_url).text
    release.set()
    client.app.state.store.wait_idle()
    assert "The run failed: stopped" in client.get(run_url).text


def test_empty_posting_is_a_message_not_a_run(make_client):
    client = make_client()
    sign_in(client)
    response = client.post("/runs", data={"posting": "   "})
    assert response.status_code == 400 and "The job description is empty." in response.text


def test_huge_request_is_refused_before_parsing(make_client):
    client = make_client()
    sign_in(client)
    response = client.post("/runs", content=b"x" * 300_000, headers={"content-type": "text/plain"})
    assert response.status_code == 413


def test_posting_text_is_escaped_not_rendered(make_client):
    client = make_client()
    sign_in(client)
    response = client.post("/runs", data={"posting": "  ", "label": "<script>alert(1)</script>"})
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;" in response.text


@pytest.mark.parametrize("run_id", ["..%2F..%2Fdata", "ABC", "a" * 31])
def test_unknown_or_crafted_run_ids_are_not_found(make_client, run_id):
    client = make_client()
    sign_in(client)
    assert client.get(f"/runs/{run_id}").status_code == 404
    assert client.get(f"/runs/{run_id}/resume.pdf").status_code in (404, 405)


def test_security_headers_and_no_caching(make_client):
    client = make_client()
    response = client.get("/login")
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"


def test_session_cookie_is_strict_and_secure_in_production(make_client):
    cookie = sign_in(make_client(secure=True)).headers["set-cookie"].lower()
    assert "samesite=strict" in cookie and "secure" in cookie and "httponly" in cookie


def test_sign_out_ends_the_session(make_client):
    client = make_client()
    sign_in(client)
    client.post("/logout")
    assert client.get("/").headers["location"] == "/login"


def test_config_needs_a_password_hash_and_a_long_secret(monkeypatch):
    monkeypatch.delenv("RESUME_WEB_PASSWORD_HASH", raising=False)
    monkeypatch.setenv("RESUME_WEB_SECRET", SECRET)
    with pytest.raises(ConfigError, match="RESUME_WEB_PASSWORD_HASH"):
        WebConfig.from_env()
    monkeypatch.setenv("RESUME_WEB_PASSWORD_HASH", HASH)
    monkeypatch.setenv("RESUME_WEB_SECRET", "short")
    with pytest.raises(ConfigError, match="at least 32"):
        WebConfig.from_env()
    monkeypatch.setenv("RESUME_WEB_SECRET", SECRET)
    assert WebConfig.from_env().secure_cookies  # secure unless explicitly turned off
