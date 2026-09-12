"""Composition root: wire concrete adapters into application-owned ports."""
from app.application.services import ReviewService
from app.infrastructure.bedrock import BedrockFieldExtractor
from app.infrastructure.paddle_pdf import PaddlePdfReader
from app.infrastructure.persistence import SQLiteReviewRepository
from app.infrastructure.text_pdf import read_pdf


def build_service(settings, pdf=None, ai=None):
    repository = SQLiteReviewRepository(settings.data_dir)
    repository.initialize()
    return ReviewService(repository, pdf or PaddlePdfReader(settings, repository), ai or BedrockFieldExtractor(settings, repository))


def sample_document(settings):
    path = settings.reference('sample')
    if not path:
        return None
    data = path.read_bytes()
    pages = [dict(page, method='reference-text') for page in read_pdf(data)]
    return data, path.name, pages
