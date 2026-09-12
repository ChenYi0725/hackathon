"""SQLite and local-file adapter for the valuation review bounded context."""
import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from app.application.ports import RevisionConflict
from app.domain.models import Case
from app.domain.rules import default_rules
from app.domain.workflow import digest


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
                CREATE TABLE IF NOT EXISTS evidence_documents (
                    document_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL,
                    ruleset_id TEXT NOT NULL, ruleset_version TEXT NOT NULL,
                    locality TEXT NOT NULL, land_use TEXT NOT NULL,
                    valid_from TEXT NOT NULL, valid_to TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS evidence_scope ON evidence_documents
                    (ruleset_id, ruleset_version, locality, land_use, valid_from, valid_to);
                CREATE TABLE IF NOT EXISTS request_gate (id TEXT PRIMARY KEY, next_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS review_runs (id TEXT PRIMARY KEY, case_id TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS dispositions (id TEXT PRIMARY KEY, case_id TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS external_evidence (id TEXT PRIMARY KEY, case_id TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL);
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
        rid = 'custom-' + uuid.uuid4().hex
        if ruleset.get('approval_state') == 'published':
            rid = 'published-' + digest({k:v for k,v in ruleset.items() if k not in ('id','approved_at')})
        saved = dict(ruleset, id=rid)
        with self.db() as c:
            c.execute('INSERT OR IGNORE INTO rulesets VALUES (?,?)', (saved['id'], json.dumps(saved, ensure_ascii=False)))
        return self.get_rules(saved['id'])

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

    def save_run(self, run):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT body FROM cases WHERE id=?', (run['case_id'],)).fetchone()
            if not row or json.loads(row['body'])['revision'] != run['case_revision']:
                raise RevisionConflict('檢核期間案件已修改，舊結果不予套用。')
            current = self._external_rows(c, run['case_id'], run['case_revision'])
            if digest(current) != run['evidence_hash']:
                raise RevisionConflict('檢核期間佐證已變更，舊結果不予套用。')
            c.execute('INSERT OR IGNORE INTO review_runs VALUES (?,?,?,?)',
                      (run['id'], run['case_id'], run['case_revision'], json.dumps(run, ensure_ascii=False)))
        return self.get_run(run['case_id'], run['id'])

    def get_run(self, case_id, run_id):
        with self.db() as c:
            row = c.execute('SELECT body FROM review_runs WHERE id=? AND case_id=?', (run_id, case_id)).fetchone()
        if not row:
            raise KeyError(run_id)
        return json.loads(row['body'])

    def dispositions(self, case_id):
        with self.db() as c:
            return [json.loads(r['body']) for r in c.execute('SELECT body FROM dispositions WHERE case_id=? ORDER BY rowid', (case_id,))]

    def save_disposition(self, record):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            existing = c.execute('SELECT body FROM dispositions WHERE id=?', (record['id'],)).fetchone()
            if existing:
                old = json.loads(existing['body'])
                keys = ('case_id', 'run_id', 'check_id', 'decision', 'reason')
                if any(old[k] != record[k] for k in keys):
                    raise RevisionConflict('相同操作 ID 不得用於不同人工處置。')
                return old
            row = c.execute('SELECT body FROM cases WHERE id=?', (record['case_id'],)).fetchone()
            if not row or json.loads(row['body'])['revision'] != record['case_revision']:
                raise RevisionConflict('人工處置的案件版本已過期。')
            run = c.execute('SELECT body FROM review_runs WHERE id=? AND case_id=?', (record['run_id'], record['case_id'])).fetchone()
            if not run or json.loads(run['body'])['evidence_hash'] != digest(self._external_rows(c, record['case_id'], record['case_revision'])):
                raise RevisionConflict('人工處置的佐證版本已過期。')
            c.execute('INSERT INTO dispositions VALUES (?,?,?)',
                      (record['id'], record['case_id'], json.dumps(record, ensure_ascii=False)))
        return record

    def external_for(self, case_id, revision):
        with self.db() as c:
            return self._external_rows(c, case_id, revision)

    @staticmethod
    def _external_rows(c, case_id, revision):
        latest = {}
        for row in c.execute('SELECT body FROM external_evidence WHERE case_id=? AND revision=? ORDER BY rowid', (case_id, revision)):
            item = json.loads(row['body'])
            # Preserve all rows for history, but a retry replaces the current outcome of that query type.
            key = (item.get('comparison_id', 'primary'), item['factor_id'], item['mode'], item.get('query', {}).get('dataset', 'parks'))
            latest[key] = item
        return [latest[key] for key in sorted(latest)]

    def save_external(self, case_id, revision, result):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT body FROM cases WHERE id=?', (case_id,)).fetchone()
            if not row or json.loads(row['body'])['revision'] != revision:
                raise RevisionConflict('外部查詢期間案件已修改；請重新查詢。')
            c.execute('INSERT INTO external_evidence VALUES (?,?,?,?)',
                      (result['id'], case_id, revision, json.dumps(result, ensure_ascii=False)))
        return result


    def save_evidence_document(self, data, name, pages, ruleset, valid_from, valid_to):
        document_id = uuid.uuid4().hex
        digest = hashlib.sha256(data).hexdigest()
        path = self.data_dir / 'uploads' / (document_id + '.pdf')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        try:
            with self.db() as c:
                c.execute('INSERT INTO documents VALUES (?,?,?,?)',
                          (document_id, name, str(path.resolve()), json.dumps(pages, ensure_ascii=False)))
                c.execute('INSERT INTO evidence_documents VALUES (?,?,?,?,?,?,?,?)',
                          (document_id, digest, ruleset['id'], ruleset['version'], ruleset['locality'],
                           ruleset['land_use'], valid_from.isoformat(), valid_to.isoformat()))
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return dict(document_id=document_id, sha256=digest, name=name, ruleset_id=ruleset['id'],
                    ruleset_version=ruleset['version'], valid_from=valid_from.isoformat(), valid_to=valid_to.isoformat())

    def list_evidence_documents(self, ruleset_id):
        self.get_rules(ruleset_id)
        with self.db() as c:
            return [dict(r) for r in c.execute("""SELECT e.*, d.name FROM evidence_documents e
                JOIN documents d ON d.id=e.document_id WHERE e.ruleset_id=? ORDER BY e.document_id""", (ruleset_id,))]

    def evidence_sources(self, query):
        with self.db() as c:
            rows = c.execute("""SELECT e.*, d.name, d.pages FROM evidence_documents e
                JOIN documents d ON d.id=e.document_id
                WHERE e.ruleset_id=? AND e.ruleset_version=? AND e.locality=? AND e.land_use=?
                AND e.valid_from<=? AND e.valid_to>=? ORDER BY e.document_id""",
                (query.ruleset_id, query.ruleset_version, query.locality, query.land_use,
                 query.valuation_date.isoformat(), query.valuation_date.isoformat())).fetchall()
        return [dict(r, pages=json.loads(r['pages'])) for r in rows]
