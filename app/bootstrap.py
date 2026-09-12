"""Composition root: wire concrete adapters into application-owned ports."""
from app.application.services import ReviewService
from app.application.rag import RagService
from app.application.agentic_rag import AgenticRagService
from app.infrastructure.bedrock_agent import BedrockAgentModel
from app.infrastructure.retrieval import LocalEvidenceRetriever
from app.infrastructure.bedrock_rag import BedrockEvidenceAnswerer
from app.infrastructure.bedrock import BedrockFieldExtractor
from app.infrastructure.paddle_pdf import PaddlePdfReader
from app.infrastructure.persistence import SQLiteReviewRepository
from app.infrastructure.text_pdf import read_pdf
from app.infrastructure.form_exports import TemplateFormRenderer
from app.application.workflow import WorkflowService
from app.infrastructure.documents import CaseDocumentReader
from app.infrastructure.reports import SnapshotRenderer
from app.infrastructure.external import OfficialEvidenceAdapter


def build_service(settings, pdf=None, ai=None, retriever=None, answerer=None, agent_model=None):
    repository = SQLiteReviewRepository(settings.data_dir)
    repository.initialize()
    pdf_reader = pdf or PaddlePdfReader(settings, repository)
    transport = BedrockFieldExtractor(settings, repository)
    retrieval = retriever or LocalEvidenceRetriever(repository)
    agent = AgenticRagService(repository, retrieval, agent_model or BedrockAgentModel(transport))
    rag = RagService(repository, pdf_reader, retrieval, answerer or BedrockEvidenceAnswerer(transport), agent=agent)
    service = ReviewService(repository, pdf_reader, ai or transport, rag=rag, renderer=TemplateFormRenderer(settings.form_template_dir))
    service.workflow = WorkflowService(service, CaseDocumentReader(pdf_reader), SnapshotRenderer(), OfficialEvidenceAdapter())
    agent.workflow = service.workflow
    return service


def sample_document(settings):
    path = settings.reference('sample')
    if not path:
        return None
    data = path.read_bytes()
    pages = [dict(page, method='reference-text') for page in read_pdf(data)]
    return data, path.name, pages
