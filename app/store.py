"""Compatibility facade for existing local scripts; the web app injects repositories."""
from app.infrastructure.settings import Settings, ROOT
from app.infrastructure.persistence import SQLiteReviewRepository, now

DATA = Settings().data_dir


def _repository():
    return SQLiteReviewRepository(DATA)


def db(): return _repository().db()
def initialize(): return _repository().initialize()
def get_case(cid): return _repository().get_case(cid)
def save_case(case, action='修改案件', new=False): return _repository().save_case(case, action, new=new)
def get_rules(rid): return _repository().get_rules(rid)
def document(docid): return _repository().get_document(docid)
