import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from app.models import Case
from app.rules import default_rules

ROOT=Path(__file__).resolve().parent.parent
DATA=Path(os.getenv('APP_DATA_DIR',str(ROOT/'data')))


def now():return datetime.now(timezone.utc).isoformat()


@contextmanager
def db():
    DATA.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(DATA/'review.sqlite3',timeout=15) as conn:
        conn.row_factory=sqlite3.Row
        yield conn


def initialize():
    with db() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, body TEXT NOT NULL, updated TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS rulesets (id TEXT PRIMARY KEY, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL, pages TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, case_id TEXT NOT NULL, action TEXT NOT NULL, at TEXT NOT NULL, snapshot TEXT NOT NULL);''')
        r=default_rules()
        c.execute('INSERT OR IGNORE INTO rulesets VALUES (?,?)',(r['id'],json.dumps(r,ensure_ascii=False)))


def get_case(cid):
    with db() as c:row=c.execute('SELECT body FROM cases WHERE id=?',(cid,)).fetchone()
    if not row:raise KeyError(cid)
    return Case.model_validate_json(row['body'])


def save_case(case,action='修改案件',new=False):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if new:case.id=uuid.uuid4().hex;case.revision=0
        else:
            row=c.execute('SELECT body FROM cases WHERE id=?',(case.id,)).fetchone()
            if not row:raise KeyError(case.id)
            if json.loads(row['body'])['revision']!=case.revision:
                raise ValueError('案件已被其他操作更新，請重新載入後再儲存。')
        case.revision+=1
        body=case.model_dump_json();stamp=now()
        c.execute('INSERT OR REPLACE INTO cases VALUES (?,?,?)',(case.id,body,stamp))
        c.execute('INSERT INTO audit(case_id,action,at,snapshot) VALUES (?,?,?,?)',(case.id,action,stamp,body))
    return case


def get_rules(rid):
    with db() as c:row=c.execute('SELECT body FROM rulesets WHERE id=?',(rid,)).fetchone()
    if not row:raise KeyError(rid)
    return json.loads(row['body'])


def document(docid):
    with db() as c:row=c.execute('SELECT * FROM documents WHERE id=?',(docid,)).fetchone()
    if not row:raise KeyError(docid)
    return dict(row)
