from backend.logging_db import LoggingDB

def test_roundtrip_and_export(tmp_path):
    db = LoggingDB(str(tmp_path / "t.db"))
    db.log_event(1.0, "op1", "STATE_CHANGE", "nominal->warning")
    db.log_score(1.0, "op1", 68, "warning")
    db.log_score(2.0, "op1", 71, "warning")
    rows = db.events_between(0.0, 10.0)
    assert len(rows) == 1 and rows[0][2] == "STATE_CHANGE"
    scores = db.scores_between(0.0, 10.0, "op1")
    assert len(scores) == 2 and scores[1][2] == 71
    out = tmp_path / "out.csv"
    db.export_csv(str(out))
    assert "STATE_CHANGE" in out.read_text()
    db.close()
