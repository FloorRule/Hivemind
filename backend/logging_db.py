from __future__ import annotations
import csv, pathlib, sqlite3

class LoggingDB:
    def __init__(self, path: str):
        p = pathlib.Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(p))
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                ts REAL, user_id TEXT, event TEXT, detail TEXT);
            CREATE TABLE IF NOT EXISTS scores (
                ts REAL, user_id TEXT, score INTEGER, state TEXT);
            CREATE INDEX IF NOT EXISTS ix_scores_op ON scores(user_id, ts);
        """)
        self.conn.commit()

    def log_event(self, ts: float, user_id: str, event: str, detail: str = ""):
        self.conn.execute("INSERT INTO events VALUES (?,?,?,?)",
                          (ts, user_id, event, detail))
        self.conn.commit()

    def log_score(self, ts: float, user_id: str, score: int, state: str):
        self.conn.execute("INSERT INTO scores VALUES (?,?,?,?)",
                          (ts, user_id, score, state))
        self.conn.commit()

    def events_between(self, t0: float, t1: float) -> list:
        return self.conn.execute(
            "SELECT * FROM events WHERE ts BETWEEN ? AND ? ORDER BY ts",
            (t0, t1)).fetchall()

    def scores_between(self, t0: float, t1: float, user_id: str) -> list:
        return self.conn.execute(
            "SELECT * FROM scores "
            "WHERE ts BETWEEN ? AND ? AND user_id=? ORDER BY ts",
            (t0, t1, user_id)).fetchall()

    def export_csv(self, out_path: str):
        p = pathlib.Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["ts", "user_id", "event", "detail"])
            for row in self.conn.execute("SELECT * FROM events ORDER BY ts"):
                w.writerow(row)
            w.writerow([])
            w.writerow(["ts", "user_id", "score", "state"])
            for row in self.conn.execute("SELECT * FROM scores ORDER BY ts"):
                w.writerow(row)

    def close(self):
        self.conn.close()
