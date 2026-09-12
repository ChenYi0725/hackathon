"""HTTP boundary: validation, status codes and representation only."""
import mimetypes
import os
from contextlib import asynccontextmanager
from urllib.parse import quote
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, StrictBool, Field
from starlette.concurrency import run_in_threadpool
from app.application.ports import ExtractionUnavailable, RevisionConflict
from app.bootstrap import build_service, sample_document
from app.domain.models import Case
from app.infrastructure.persistence import now
from app.infrastructure.settings import ROOT, Settings
from app.interfaces.exports import export_case
from app.application.export_contracts import ExportUnavailable


mimetypes.add_type('text/javascript', '.js')


class RevisionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int


class AiRequest(RevisionRequest):
    cloud_data_approved: StrictBool = False


class AgentRequest(AiRequest):
    question: str = Field(min_length=1, max_length=1000)


class RagRequest(AiRequest):
    question: str = Field(min_length=1, max_length=1000)
    generate: StrictBool = False
    rule_ids: list[str] = Field(default_factory=list, max_length=100)


class RulesetConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    document_id: str = Field(min_length=1, max_length=100)
    candidate: dict
    valid_from: str = Field(min_length=10, max_length=10)
    valid_to: str = Field(min_length=10, max_length=10)
    matrix_direction: str
    confirmed: StrictBool = False


def create_app(settings=None, *, pdf=None, ai=None, retriever=None, answerer=None,
               agent_model=None, ruleset_extractor=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.settings = settings or Settings()
        app.state.service = build_service(
            app.state.settings,
            pdf=pdf,
            ai=ai,
            retriever=retriever,
            answerer=answerer,
            agent_model=agent_model,
            ruleset_extractor=ruleset_extractor,
        )
        if os.getenv('SEED_EXAMPLES', 'true').lower() == 'true':
            app.state.service.seed_examples(sample_document(app.state.settings))
        yield

    app = FastAPI(title='地衡 · 估價審查工作台', version='1.1.0', lifespan=lifespan)

    def service():
        return app.state.service

    @app.middleware('http')
    async def local_mutations(request, call_next):
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('origin')
            if origin and origin != f'{request.url.scheme}://{request.headers.get("host")}':
                return Response('Cross-origin mutation is not permitted', status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        return response

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return Response('找不到案件、文件或基準。', status_code=404)

    @app.exception_handler(RevisionConflict)
    async def conflict(request, exc):
        return Response(str(exc), status_code=409)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return Response(str(exc), status_code=400)

    @app.exception_handler(ExtractionUnavailable)
    async def unavailable(request, exc):
        return Response(str(exc), status_code=503)

    @app.get('/api/health')
    def health():
        config = app.state.settings
        return dict(status='ok', version='1.1.0', ocr_provider='paddleocr', ai_provider='bedrock',
                    ai_configured=config.ai_enabled and bool(config.model_id), ai_model=config.model_id, ai_region=config.region)

    @app.get('/api/cases')
    def list_cases():
        return service().list_cases()

    @app.post('/api/cases')
    def create_case(case: Case):
        return service().save_case(case, new=True)

    @app.post('/api/samples/{kind}')
    def create_sample(kind: str):
        return service().create_sample(kind, sample_document(app.state.settings))

    @app.get('/api/cases/{cid}')
    def get_case(cid: str):
        return service().get_case(cid)

    @app.put('/api/cases/{cid}')
    def update_case(cid: str, case: Case):
        if case.id != cid:
            raise ValueError('案件 ID 不符。')
        return service().save_case(case)

    @app.post('/api/cases/{cid}/copy')
    def copy_case(cid: str, body: RevisionRequest):
        return service().copy_case(cid, body.revision)

    @app.post('/api/cases/{cid}/fix/{check_id}')
    def fix(cid: str, check_id: str, body: RevisionRequest):
        return service().fix(cid, check_id, body.revision)

    @app.get('/api/cases/{cid}/audit')
    def audit(cid: str):
        return service().repository.audit(cid)

    @app.get('/api/cases/{cid}/audit/{aid}')
    def snapshot(cid: str, aid: int):
        return service().repository.snapshot(cid, aid)

    @app.post('/api/documents')
    async def upload(request: Request, name: str = '案件.pdf', ruleset_id: str = 'jinshan-commercial-v1'):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 20 * 1024 * 1024:
                raise HTTPException(413, 'PDF 上限 20 MB。')
        try:
            return await run_in_threadpool(service().upload, bytes(data), name, ruleset_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post('/api/ruleset-imports')
    async def import_ruleset(
        request: Request,
        expected_locality: str,
        name: str = '評價基準明細表.pdf',
    ):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 20 * 1024 * 1024:
                raise HTTPException(413, 'PDF 上限 20 MB。')
        try:
            return await run_in_threadpool(
                service().ruleset_import.extract,
                bytes(data),
                name,
                expected_locality,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post('/api/ruleset-imports/confirm')
    def confirm_ruleset(body: RulesetConfirmationRequest):
        return service().ruleset_import.confirm(**body.model_dump())

    @app.get('/api/documents/{docid}')
    def document(docid: str):
        doc = service().repository.get_document(docid)
        return dict(id=docid, name=doc['name'], pages=doc['pages'])

    @app.get('/api/documents/{docid}/file')
    def file(docid: str):
        doc = service().repository.get_document(docid)
        return FileResponse(doc['path'], media_type='application/pdf', headers={'Content-Disposition': "inline; filename*=UTF-8''" + quote(doc['name'])})

    @app.get('/api/reference/{kind}')
    def reference(kind: str):
        if kind not in ('rules', 'manual', 'brief'):
            raise KeyError(kind)
        path = app.state.settings.reference(kind)
        if not path:
            raise KeyError(kind)
        return FileResponse(path, media_type='application/pdf')

    @app.post('/api/cases/{cid}/ai')
    def extract_ai(cid: str, body: AiRequest):
        return service().extract_ai(cid, body.revision, body.cloud_data_approved)

    @app.post('/api/cases/{cid}/evidence')
    def evidence(cid: str, body: RagRequest):
        return service().rag.query(cid, body.revision, body.question, generate=body.generate,
                                   cloud_data_approved=body.cloud_data_approved, rule_ids=body.rule_ids)

    @app.post('/api/cases/{cid}/agent-evidence')
    def agent_evidence(cid: str, body: AgentRequest):
        return service().rag.agent.query(cid, body.revision, body.question, body.cloud_data_approved)

    @app.get('/api/rulesets/{rid}/evidence-documents')
    def evidence_documents(rid: str):
        return service().repository.list_evidence_documents(rid)

    @app.post('/api/rulesets/{rid}/evidence-documents')
    async def upload_evidence(rid: str, request: Request, valid_from: str, valid_to: str, name: str = '基準.pdf'):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 20 * 1024 * 1024:
                raise HTTPException(413, 'PDF 上限 20 MB。')
        try:
            return await run_in_threadpool(service().rag.upload_source, rid, bytes(data), name, valid_from, valid_to)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.get('/api/rulesets')
    def rulesets():
        return service().repository.list_rules()

    @app.post('/api/rulesets')
    def create_ruleset(body: dict):
        return service().create_ruleset(body)

    @app.get('/api/cases/{cid}/export/{kind}')
    def export(cid: str, kind: str, revision: int | None = None):
        if kind in {'review-xlsx', 'table3-xlsx', 'table4-xlsx', 'table5-xlsx'}:
            if revision is None:
                raise HTTPException(422, '請提供案件 revision，確保匯出版本一致。')
            try:
                artifact = service().export_document(cid, kind, revision, now())
            except ExportUnavailable as error:
                raise HTTPException(503, str(error)) from error
            return Response(artifact.data, media_type=artifact.media_type, headers={
                'Content-Disposition': "attachment; filename*=UTF-8''" + quote(artifact.filename),
                'X-Case-Revision': str(artifact.revision), 'Cache-Control': 'no-store'})
        result = service().get_case(cid)
        case = Case.model_validate(result['case'])
        return export_case(case, result['review'], service().repository.get_rules(case.ruleset_id), kind, now())

    app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')

    @app.get('/')
    def index():
        return FileResponse(ROOT / 'static' / 'index.html')

    return app
