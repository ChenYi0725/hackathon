"""Composition root: wire concrete adapters into application-owned ports."""
from app.application.services import ReviewService
from app.application.rag import RagService
from app.application.agentic_rag import AgenticRagService
from app.infrastructure.bedrock_agent import BedrockAgentModel
from app.infrastructure.public_data import GovernmentDataLookup
from app.infrastructure.retrieval import LocalEvidenceRetriever
from app.infrastructure.aws_rag_runtime import AwsRagRuntime
from app.infrastructure.knowledge_base import BedrockKnowledgeBaseRetriever, S3KnowledgeBasePublisher
from app.infrastructure.bedrock_rag import BedrockEvidenceAnswerer
from app.infrastructure.bedrock import BedrockFieldExtractor
from app.infrastructure.paddle_pdf import LocalPdfReader
from app.infrastructure.persistence import SQLiteReviewRepository
from app.infrastructure.text_pdf import read_pdf
from app.infrastructure.form_exports import TemplateFormRenderer
from app.infrastructure.ruleset_table import PaddleLayoutRulesetExtractor
from app.application.ruleset_extraction import RulesetExtractionService
from app.application.ruleset_imports import RulesetImportService


def build_service(settings, pdf=None, ai=None, retriever=None, answerer=None,
                  agent_model=None, ruleset_extractor=None):
    repository = SQLiteReviewRepository(settings.data_dir)
    repository.initialize()
    pdf_reader = pdf or LocalPdfReader(settings, repository)
    transport = BedrockFieldExtractor(settings, repository)
    runtime = AwsRagRuntime(transport)
    cloud_retrieval = settings.rag_backend == 'bedrock-kb'
    retrieval = retriever or (BedrockKnowledgeBaseRetriever(settings, repository, runtime)
                             if cloud_retrieval else LocalEvidenceRetriever(repository))
    publisher = S3KnowledgeBasePublisher(settings, repository, runtime) if cloud_retrieval else None
    agent = AgenticRagService(repository, retrieval, agent_model or BedrockAgentModel(transport),
                             public_data=GovernmentDataLookup())
    rag = RagService(repository, pdf_reader, retrieval, answerer or BedrockEvidenceAnswerer(transport), agent=agent,
                     publisher=publisher, cloud_retrieval=cloud_retrieval)
    ruleset_import = RulesetImportService(
        repository,
        pdf_reader,
        ruleset_extractor or PaddleLayoutRulesetExtractor(),
    )
    return ReviewService(repository, pdf_reader, ai or transport, rag=rag,
                         renderer=TemplateFormRenderer(settings.form_template_dir),
                         ruleset_import=ruleset_import)


def build_ruleset_extraction_service(settings, pdf=None):
    """Wire OCR output to deterministic structured-ruleset compilation."""
    return RulesetExtractionService(
        pdf or LocalPdfReader(settings),
        PaddleLayoutRulesetExtractor(),
    )


def sample_document(settings):
    path = settings.reference('sample')
    if not path:
        return None
    data = path.read_bytes()
    pages = [dict(page, method='reference-text') for page in read_pdf(data)]
    return data, path.name, pages
