from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def test_command_page_exists_with_markers():
    html = (ROOT / "static/command/index.html").read_text()
    assert 'id="grid"' in html and "app.js" in html
    js = (ROOT / "static/command/app.js").read_text()
    assert "manual_override" in js and "sim_mode" in js

def test_command_page_has_alert_log_and_sim_toggle():
    html = (ROOT / "static/command/index.html").read_text()
    assert 'id="alertlog"' in html and 'id="simbadge"' in html
    js = (ROOT / "static/command/app.js").read_text()
    assert "alertlog" in js and 'key.toLowerCase() === "s"' in js

def test_operator_page_exists_with_markers():
    html = (ROOT / "static/operator/index.html").read_text()
    assert "app.js" in html and "game.js" in html
    js = (ROOT / "static/operator/app.js").read_text()
    assert "TRIGGER_INTERVENTION" in js and "client_ready" in js
    game = (ROOT / "static/operator/game.js").read_text()
    assert "createCanvas" in game and "END_INTERVENTION" in js

def test_shared_ws_helper_exists():
    ws = (ROOT / "static/shared/ws.js").read_text()
    assert "backoff" in ws and "onmessage" in ws
