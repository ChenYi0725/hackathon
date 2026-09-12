"""SQLite and local-file adapter for the valuation review bounded context."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from app.application.ports import RevisionConflict
from app.domain.models import Case
from app.domain.rules import default_rules


def now():
    return datetime.now(timezone.utc).isoformat()


class SQLiteReviewRepository:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)

    @contextmanager
    def db(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.data_dir / 'review.sqlite3', timeout=15)
        try:
            conn.row_factory = sqlite3.Row
            with conn:
                yield conn
        finally:
            conn.close()

    def initialize(self):
        with self.db() as c:
            c.execute('PRAGMA journal_mode=WAL')
            c.executescript('''
                CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, body TEXT NOT NULL, updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS rulesets (id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL, pages TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, case_id TEXT NOT NULL, action TEXT NOT NULL, at TEXT NOT NULL, snapshot TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS extraction_cache (key TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS request_gate (id TEXT PRIMARY KEY, next_at REAL NOT NULL);
            ''')
            rules = default_rules()
            c.execute('INSERT OR IGNORE INTO rulesets VALUES (?,?)', (rules['id'], json.dumps(rules, ensure_ascii=False)))

    def list_cases(self):
        with self.db() as c:
            return [(Case.model_validate_json(r['body']), r['updated']) for r in c.execute('SELECT body,updated FROM cases ORDER BY updated DESC')]

    def get_case(self, case_id):
        with self.db() as c:
            row = c.execute('SELECT body FROM cases WHERE id=?', (case_id,)).fetchone()
        if not row:
            raise KeyError(case_id)
        return Case.model_validate_json(row['body'])

    def save_case(self, case, action, *, new=False):
        saved = case.model_copy(deep=True)
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if new:
                saved.id = uuid.uuid4().hex
                saved.revision = 0
            else:
                row = c.execute('SELECT body FROM cases WHERE id=?', (saved.id,)).fetchone()
                if not row:
                    raise KeyError(saved.id)
                if json.loads(row['body'])['revision'] != saved.revision:
                    raise RevisionConflict('案件已被其他操作更新，請重新載入後再儲存。')
            saved.revision += 1
            body, stamp = saved.model_dump_json(), now()
            c.execute('INSERT OR REPLACE INTO cases VALUES (?,?,?)', (saved.id, body, stamp))
            c.execute('INSERT INTO audit(case_id,action,at,snapshot) VALUES (?,?,?,?)', (saved.id, action, stamp, body))
        return saved

    def list_rules(self):
        with self.db() as c:
            return [json.loads(r['body']) for r in c.execute('SELECT body FROM rulesets')]

    def get_rules(self, ruleset_id):
        with self.db() as c:
            row = c.execute('SELECT body FROM rulesets WHERE id=?', (ruleset_id,)).fetchone()
        if not row:
            raise KeyError(ruleset_id)
        return json.loads(row['body'])

    def add_rules(self, ruleset):
        saved = dict(ruleset, id='custom-' + uuid.uuid4().hex)
        with self.db() as c:
            c.execute('INSERT INTO rulesets VALUES (?,?)', (saved['id'], json.dumps(saved, ensure_ascii=False)))
        return saved

    def save_document(self, data, name, pages):
        document_id = uuid.uuid4().hex
        path = self.data_dir / 'uploads' / (document_id + '.pdf')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        try:
            with self.db() as c:
                c.execute('INSERT INTO documents VALUES (?,?,?,?)', (document_id, name, str(path.resolve()), json.dumps(pages, ensure_ascii=False)))
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return document_id

    def get_document(self, document_id):
        with self.db() as c:
            row = c.execute('SELECT * FROM documents WHERE id=?', (document_id,)).fetchone()
        if not row:
            raise KeyError(document_id)
        return dict(row, pages=json.loads(row['pages']))

    def audit(self, case_id):
        self.get_case(case_id)
        with self.db() as c:
            return [dict(r) for r in c.execute('SELECT id,action,at FROM audit WHERE case_id=? ORDER BY id DESC', (case_id,))]

    def snapshot(self, case_id, audit_id):
        with self.db() as c:
            row = c.execute('SELECT snapshot FROM audit WHERE case_id=? AND id=?', (case_id, audit_id)).fetchone()
        if not row:
            raise KeyError(audit_id)
        return json.loads(row['snapshot'])

    def cache_get(self, key):
        with self.db() as c:
            row = c.execute('SELECT body FROM extraction_cache WHERE key=?', (key,)).fetchone()
        return json.loads(row['body']) if row else None

    def cache_put(self, key, value):
        with self.db() as c:
            c.execute('INSERT OR REPLACE INTO extraction_cache VALUES (?,?)', (key, json.dumps(value, ensure_ascii=False)))
