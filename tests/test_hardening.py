"""Hardening tests: SSRF guard and DNS pinning, request-size and rate limits, cross-site writes,
decompression bombs, and what the API must not reveal."""

import base64
import http.server
import io
import threading
import zipfile

import httpx
import pymupdf
import pytest

import ai
import characterisation as c
import limits
import netguard
import sanitisation as sanmod
import server


@pytest.fixture(autouse=True)
def direct_network(monkeypatch):
    """These tests are about direct connections: no outbound proxy from the environment."""
    for name in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"):
        monkeypatch.delenv(name, raising=False)


# --- SSRF --------------------------------------------------------------------------------------

@pytest.mark.parametrize("ip", [
    "127.0.0.1", "::1", "169.254.169.254", "10.0.0.5", "192.168.1.1", "172.16.0.1",
    "100.64.0.1", "100.100.100.200",       # carrier-grade NAT: cloud metadata on some providers
    "::ffff:127.0.0.1", "::ffff:10.0.0.1",  # IPv4-mapped
    "2002:7f00:1::", "64:ff9b::7f00:1", "::7f00:1",  # 6to4, NAT64 and IPv4-compatible forms of 127.0.0.1
    "fe80::1", "fd00::1", "fec0::1", "ff02::1", "198.18.0.1",
])
def test_non_public_addresses_are_blocked(ip):
    assert netguard.address_block_reason(ip)


def test_unspecified_address_is_blocked():
    # The SSRF guard must refuse it; nothing binds to it here.
    assert netguard.address_block_reason("0.0.0.0")  # nosec B104


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"])
def test_public_addresses_are_allowed(ip):
    assert netguard.address_block_reason(ip) == ""


@pytest.mark.parametrize("ip", ["127.0.0.1", "169.254.169.254", "::ffff:127.0.0.1", "fe80::1"])
def test_private_endpoints_never_include_loopback_or_metadata(ip):
    assert netguard.address_block_reason(ip, allow_private=True)
    assert netguard.address_block_reason("10.0.0.5", allow_private=True) == ""


@pytest.mark.parametrize("url", [
    "http://[::ffff:127.0.0.1]/x", "http://[::1]/x", "http://100.64.0.1/x", "http://0.0.0.0/x", "http://2130706433/x",
    "http://user:pw@example.org/x", "http://metadata.google.internal/x", "http://printer.local/x", "gopher://example.org/x",
    "http://[fe80::1%25eth0]/x",
])
def test_dossier_urls_to_internal_targets_are_refused(url):
    with pytest.raises(ValueError):
        c.validate_url(url)


@pytest.mark.parametrize("url", ["https://[::ffff:169.254.169.254]/v1", "https://100.100.100.200/v1", "http://8.8.8.8/v1",
                                 "https://ollama.internal/v1"])
def test_ai_endpoints_to_internal_targets_are_refused(url):
    assert not ai.validate_endpoint(url)[0]


def test_host_resolving_to_a_private_address_is_refused(monkeypatch):
    monkeypatch.setattr(netguard.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0)), (2, 1, 6, "", ("10.0.0.7", 0))])
    with pytest.raises(netguard.BlockedURL):
        netguard.check_url("https://mixed.example.org/x")


class _Echo(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = f"host={self.headers['Host']}".encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture()
def local_server():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Echo)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


def test_connection_goes_to_the_checked_address_not_to_a_second_dns_answer(monkeypatch, local_server):
    """DNS rebinding: the name is resolved once, checked, and that address is the one connected to."""
    lookups = []

    def resolve(host, port, allow_private=False):
        lookups.append(host)
        return ["127.0.0.1"]  # stands for "the address that passed the check"
    monkeypatch.setattr(netguard, "resolve_checked", resolve)
    # If the transport resolved the name again, this would fail: rebind.invalid does not exist.
    with netguard.client(timeout=5) as client:
        r = client.get(f"http://rebind.invalid:{local_server}/x")
    assert r.status_code == 200 and r.text == f"host=rebind.invalid:{local_server}" and lookups == ["rebind.invalid"]


def test_pinned_client_refuses_internal_addresses_and_redirects(local_server):
    with netguard.client(timeout=5) as client:
        assert client.follow_redirects is False
        with pytest.raises(httpx.ConnectError, match="Refused"):
            client.get(f"http://127.0.0.1:{local_server}/x")


def test_fetch_revalidates_every_redirect_hop():
    def handler(request):
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    docs, notes = c.fetch_url_documents("http://8.8.8.8/dossier.pdf", 1, client=client)
    assert not docs and "refused" in notes[0].lower() and "169.254.169.254" in notes[0]


def test_fetch_budget_caps_total_download():
    def handler(request):
        return httpx.Response(200, content=b"x" * 4096, headers={"content-type": "text/plain"})
    budget = c.FetchBudget(max_bytes=1000)
    docs, notes = c.fetch_url_documents("http://8.8.8.8/a.txt", 1, client=httpx.Client(transport=httpx.MockTransport(handler)), budget=budget)
    assert not docs and "exceed" in notes[0]


# --- Request size, rate, concurrency ---------------------------------------------------------------

def test_oversized_json_body_is_refused(client):
    r = client.post("/api/chat", content=b'{"message":"' + b"a" * (limits.DEFAULT_BODY_LIMIT + 10) + b'"}',
                    headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_oversized_chunked_body_is_refused(client):
    def chunks():  # no Content-Length: only counting the bytes received can stop this
        yield b'{"message":"'
        for _ in range(limits.DEFAULT_BODY_LIMIT // 65536 + 2):
            yield b"a" * 65536
        yield b'"}'
    r = client.post("/api/chat", content=chunks(), headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_sign_in_form_body_is_small(anon_client):
    r = anon_client.post("/auth/email", content=b"email=" + b"a" * 100_000, headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 413


def test_body_limits_per_route():
    assert server._body_limit("POST", "/api/sanitisation/analyse") > sanmod.MAX_FILE_BYTES
    assert server._body_limit("POST", "/api/chat") == limits.DEFAULT_BODY_LIMIT
    assert server._body_limit("GET", "/api/aops") < 1024 * 1024


def test_rate_limit_on_outbound_probes(client, monkeypatch):
    monkeypatch.setenv("KEVIDENCE_RATE_LIMIT", "on")
    monkeypatch.setenv("KEVIDENCE_RATE_OUTBOUND", "2/600")
    limits.WINDOW.reset()
    try:
        answers = [client.post("/api/ai/models", json={"provider": "openai"}).status_code for _ in range(3)]
        assert answers == [400, 400, 429]
        assert client.post("/api/ai/models", json={"provider": "openai"}).headers.get("retry-after")
        assert client.get("/api/me").status_code == 200  # other routes are unaffected
    finally:
        limits.WINDOW.reset()


def test_general_rate_limit_applies_to_anonymous_clients(anon_client, monkeypatch):
    monkeypatch.setenv("KEVIDENCE_RATE_LIMIT", "on")
    monkeypatch.setenv("KEVIDENCE_RATE_GENERAL", "3/60")
    limits.WINDOW.reset()
    try:
        codes = [anon_client.get("/auth/signin").status_code for _ in range(4)]
        assert codes == [200, 200, 200, 429]
        assert anon_client.get("/api/health").status_code == 200  # monitoring is never throttled
    finally:
        limits.WINDOW.reset()


def test_heavy_jobs_are_capped_per_user_and_overall(monkeypatch):
    monkeypatch.setenv("KEVIDENCE_HEAVY_PER_USER", "2")
    monkeypatch.setenv("KEVIDENCE_HEAVY_TOTAL", "3")
    slots = limits.HeavySlots()
    assert slots.acquire("a") and slots.acquire("a") and not slots.acquire("a")
    assert slots.acquire("b") and not slots.acquire("c")
    slots.release("a")
    assert slots.acquire("c")


def test_ipv6_clients_are_limited_by_network():
    assert limits.client_key("2001:db8:1:2:aaaa::1") == limits.client_key("2001:db8:1:2:bbbb::2")
    assert limits.client_key("2001:db8:1:2::1") != limits.client_key("2001:db8:1:3::1")
    assert limits.client_key("::ffff:203.0.113.9") == "203.0.113.9"


# --- Cross-site writes and headers ------------------------------------------------------------------

def test_cross_site_write_without_origin_is_refused(client):
    assert client.post("/api/ai/models", json={}, headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert client.post("/api/ai/models", json={}, headers={"sec-fetch-site": "same-site"}).status_code == 403
    assert client.post("/api/ai/models", json={}, headers={"sec-fetch-site": "same-origin"}).status_code == 400


def test_production_accepts_only_the_configured_origin(client, monkeypatch):
    monkeypatch.setenv("KEVIDENCE_ENV", "production")
    monkeypatch.setenv("APP_URL", "http://testserver")  # keeps the test cookie name; only the origin rule is under test
    assert client.post("/api/ai/models", json={}, headers={"origin": "http://testserver"}).status_code == 400
    assert client.post("/api/ai/models", json={}, headers={"origin": "http://evil.example", "host": "evil.example"}).status_code == 403


def test_isolation_headers(client):
    h = client.get("/api/me").headers
    assert h["cross-origin-resource-policy"] == "same-origin" and h["x-permitted-cross-domain-policies"] == "none"


# --- Hostile documents -----------------------------------------------------------------------------

def _zip(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_docx_decompression_bomb_is_not_expanded(monkeypatch):
    monkeypatch.setattr(c, "MAX_EXPANDED_BYTES", 1024 * 1024)
    bomb = _zip({"word/document.xml": b"<w:p>" + b"A" * (8 * 1024 * 1024) + b"</w:p>"})
    assert len(bomb) < 100_000
    doc = c.extract_document("bomb.docx", bomb)
    assert not doc.pages and "too large once expanded" in doc.warnings[0]


def test_xlsx_decompression_bomb_is_not_expanded(monkeypatch):
    monkeypatch.setattr(c, "MAX_EXPANDED_BYTES", 1024 * 1024)
    bomb = _zip({"xl/worksheets/sheet1.xml": b"0" * (8 * 1024 * 1024)})
    doc = c.extract_document("bomb.xlsx", bomb)
    assert not doc.pages and "too large once expanded" in doc.warnings[0]


def test_ordinary_docx_still_reads():
    doc = c.extract_document("a.docx", _zip({"word/document.xml": "<w:p><w:t>Zinc &amp; copper &lt; 5 mg/kg</w:t></w:p>"}))
    assert doc.pages == ["Zinc & copper < 5 mg/kg\n"]


def test_preview_of_a_huge_page_is_bounded():
    pdf = pymupdf.open()
    pdf.new_page(width=600, height=180_000)
    preview = sanmod.render_previews(pdf)[0]
    pix = pymupdf.Pixmap(base64.b64decode(preview["image"].split(",", 1)[1]))
    assert pix.width * pix.height <= sanmod.MAX_PREVIEW_PIXELS * 1.05


# --- What the API must not reveal or choke on -----------------------------------------------------------

def test_status_endpoints_do_not_reveal_server_paths(client):
    for path in ("/api/openfoodtox/status", "/api/bioactivity/status"):
        body = client.get(path).text
        assert "sqlite_path" not in body and str(server.DATA_DIR) not in body


@pytest.mark.parametrize("message", [None, 5, ["x"], {"a": 1}, ""])
def test_chat_rejects_non_text_questions(client, message):
    assert client.post("/api/chat", json={"message": message}).status_code == 400


def test_chat_rejects_overlong_questions(client):
    assert client.post("/api/chat", json={"message": "a" * (server.MAX_QUESTION_CHARS + 1)}).status_code == 413


def test_listing_limit_is_capped(client):
    assert client.get("/api/aops?limit=999999999").status_code == 200
    assert client.get("/api/aops?limit=-5").status_code == 200


@pytest.mark.parametrize("email", ["a\x00b@example.org", "a​b@example.org", "a@exa\x7fmple.org"])
def test_emails_with_invisible_characters_are_refused(email):
    import accounts
    assert accounts.normalise_email(email) == ""


# --- Bandit follow-ups ------------------------------------------------------------------------------------

def _importer():
    import importlib.util
    spec = importlib.util.spec_from_file_location("import_openfoodtox", server.KEVIDENCE_HOME / "scripts" / "import_openfoodtox.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://zenodo.org/x", "https://evil.example/x.xlsx",
                                 "https://user:pw@zenodo.org/x", "ftp://zenodo.org/x", "https://zenodo.org.evil.example/x"])
def test_openfoodtox_importer_refuses_non_zenodo_urls(url):
    with pytest.raises(SystemExit):
        _importer()._checked_url(url)


def test_openfoodtox_importer_rechecks_redirects_and_names(monkeypatch, tmp_path):
    mod = _importer()
    record = {"files": [{"key": "../../evil name.xlsx", "links": {"self": "https://zenodo.org/f/1"}}]}

    def handler(request):
        if request.url.path.endswith(mod.ZENODO_RECORD_ID):
            return httpx.Response(200, json=record)
        return httpx.Response(302, headers={"location": "file:///etc/passwd"})
    real = httpx.Client
    monkeypatch.setattr(mod.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(SystemExit, match="only https://zenodo.org"):
        mod.download_latest_openfoodtox_excel(tmp_path)
    assert list(tmp_path.iterdir()) == []  # nothing written, no partial file left behind

    def ok(request):
        return httpx.Response(200, json=record) if request.url.path.endswith(mod.ZENODO_RECORD_ID) else httpx.Response(200, content=b"xlsx")
    monkeypatch.setattr(mod.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(ok), **kw))
    out = mod.download_latest_openfoodtox_excel(tmp_path)
    assert out.parent == tmp_path and out.name == "evil_name.xlsx" and out.read_bytes() == b"xlsx"


def test_personal_data_scan_failure_is_not_reported_as_clean(monkeypatch):
    import completeness as compmod
    import sanitisation as sanmod
    from pathlib import Path
    zip_bytes = (Path(server.KEVIDENCE_HOME) / "static/samples/completeness_demo_dossier.zip").read_bytes()

    def broken(*args, **kwargs):
        raise RuntimeError("parser crashed")
    monkeypatch.setattr(sanmod, "detect_local", broken)
    result = compmod.check_dossier([("dossier.zip", zip_bytes)], server.COMPLETENESS_RULES, domain="feed", application_type="new",
                                   sector=server._sani_sector("", "feed"))
    item = next(i for i in result["results"] if i["rule_id"] == "PA-ART4-5-PERSONAL-DATA")
    assert item["status"] == "review" and "could not be scanned" in item["detail"]
    assert any(e["note"].startswith("could not be scanned") for e in item["evidence"])


def test_sign_in_link_without_token_is_refused(anon_client):
    assert anon_client.get("/auth/verify").status_code == 400
