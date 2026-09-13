"""Measure existing OCR and ruleset compiler stages without changing adapters.

Explicitly provide an authorized PDF and report directory. This is a diagnostic
runner, not a benchmark that automatically uploads documents or confirms rules.
"""
import argparse
import cProfile
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import pstats
import resource
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.infrastructure import ocr_backends, ocr_worker
from app.infrastructure.settings import Settings
from app.infrastructure.ruleset_table import PaddleLayoutRulesetExtractor
from app.application.ruleset_imports import build_review_candidates


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf',type=Path)
    parser.add_argument('--locality',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--page',type=int,help='Profile one PDF page (1-based); does not compile a partial ruleset.')
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    settings=Settings()
    options=dict(engine=settings.ocr_engine,dpi=settings.ocr_dpi,cpu_threads=settings.ocr_threads,
                 detection_model=settings.detection_model,recognition_model=settings.recognition_model)
    report=dict(options=options,pages=[],started_at=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
                source_name=args.pdf.name,source_sha256=hashlib.sha256(args.pdf.read_bytes()).hexdigest(),versions={})
    for package in ('paddleocr','paddlepaddle','pypdfium2','rapidocr','onnxruntime'):
        try:report['versions'][package]=version(package)
        except PackageNotFoundError:pass
    def emit(event,**data):
        print(json.dumps(dict(event=event,**data),ensure_ascii=False),flush=True)
        (args.output/'timings.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    original=ocr_backends.create_predictor
    profile=cProfile.Profile()
    def timed_predictor(config):
        started=time.perf_counter()
        emit('model_initialization_started')
        predict=original(config)
        report['model_initialization_seconds']=time.perf_counter()-started
        emit('model_initialized',seconds=report['model_initialization_seconds'])
        def timed(image):
            index=len(report['pages'])+1
            emit('page_started',page=index)
            started=time.perf_counter()
            if index==1:profile.enable()
            try:lines=list(predict(image))
            finally:
                if index==1:profile.disable()
            report['pages'].append(dict(page=index,ocr_seconds=time.perf_counter()-started,
                                       text_boxes=len(lines),width=image.shape[1],height=image.shape[0]))
            emit('page_completed',**report['pages'][-1])
            yield from lines
        return timed
    ocr_backends.create_predictor=timed_predictor
    started=time.perf_counter()
    if args.page is not None:
        from pypdf import PdfReader, PdfWriter
        document=PdfReader(args.pdf)
        if not 1 <= args.page <= len(document.pages):raise ValueError('Invalid page number')
        report['source_page']=args.page
        with tempfile.TemporaryDirectory(prefix='landwise-profile-page-') as directory:
            source=Path(directory)/'page.pdf'
            writer=PdfWriter();writer.add_page(document.pages[args.page-1]);writer.write(source)
            pages=ocr_worker.recognize(source,options)
    else:
        pages=ocr_worker.recognize(args.pdf,options)
    report['ocr_total_seconds']=time.perf_counter()-started
    profile.dump_stats(str(args.output/'first-page.prof'))
    with (args.output/'first-page-profile.txt').open('w',encoding='utf-8') as out:
        pstats.Stats(profile,stream=out).strip_dirs().sort_stats('cumulative').print_stats(30)
    emit('ocr_completed',seconds=report['ocr_total_seconds'],page_count=len(pages))
    if args.page is not None:
        report['max_rss_kib']=peak_rss_kib()
        emit('profile_completed',compilation='not run for a partial document')
        return
    started=time.perf_counter()
    try:
        result=PaddleLayoutRulesetExtractor().extract(pages,source_name=args.pdf.name,expected_locality=args.locality)
        candidates=build_review_candidates(result)
        report['compilation']=dict(status='success',candidates=len(candidates),
                                    factors=sum(len(c['rules']) for c in candidates),warnings=list(result.warnings))
    except ValueError as error:
        report['compilation']=dict(status='error',message=str(error))
    report['compilation_seconds']=time.perf_counter()-started
    report['max_rss_kib']=peak_rss_kib()
    emit('compilation_completed',seconds=report['compilation_seconds'],**report['compilation'])


def peak_rss_kib():
    value=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value/1024 if sys.platform=='darwin' else value


if __name__=='__main__':main()
