"""Exercise real PaddleOCR on OCR_DEVICE and, optionally, Bedrock using synthetic data."""
import argparse
import json
import tempfile
import time
from pathlib import Path
from fastapi.testclient import TestClient
from app.infrastructure.settings import Settings, ROOT
from app.interfaces.http import create_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bedrock', action='store_true', help='Send synthetic OCR text to Bedrock')
    parser.add_argument('--profile', default=None, help='Optional AWS CLI profile name')
    parser.add_argument('--report', type=Path, default=ROOT / '.analysis' / 'integration-smoke.json')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='landwise-smoke-') as temp:
        settings = Settings(data_dir=Path(temp), reference_dir=Path(temp), aws_profile=args.profile,
                            ai_enabled=args.bedrock, ocr_timeout=900)
        app = create_app(settings)
        with TestClient(app) as client:
            started = time.monotonic()
            response = client.post('/api/documents?name=synthetic-scanned.pdf',
                                   content=(ROOT / 'tests/fixtures/synthetic-scanned.pdf').read_bytes())
            response.raise_for_status()
            case = response.json()['case']
            pages = client.get('/api/documents/' + case['document_id']).json()['pages']
            assert pages[0]['method'] == 'paddleocr' and '寬度' in pages[0]['text']
            assert all(p['device'] == settings.ocr_device for p in pages)
            report = {'ocr': {'provider': 'paddleocr', 'device': settings.ocr_device, 'pages': len(pages), 'line_count': sum(len(p['lines']) for p in pages),
                              'elapsed_seconds': round(time.monotonic() - started, 2)},
                      'data': 'synthetic fixture only; no source cases sent to AWS'}
            if args.bedrock:
                started = time.monotonic()
                url = '/api/cases/' + case['id'] + '/ai'
                response = client.post(url, json={'revision': case['revision'], 'cloud_data_approved': True})
                if response.status_code != 200:
                    raise RuntimeError('Bedrock smoke test: ' + response.text)
                response.raise_for_status()
                factors = response.json()['factors']
                assert factors and all(not f['confirmed'] for f in factors)
                values = {f['id']: (f['subject'], f['comparable']) for f in factors}
                assert values.get('width') == ('5', '7'), values
                assert values.get('road_width') == ('18', '6'), values
                assert client.get('/api/cases/' + case['id']).json()['case'] == case
                report['bedrock'] = {'model': settings.model_id, 'region': settings.region,
                                     'factor_ids': [f['id'] for f in factors],
                                     'values': values,
                                     'elapsed_seconds': round(time.monotonic() - started, 2),
                                     'usage': app.state.service.ai.last_usage, 'case_unchanged': True}
                # The second preview must reuse the verified cached result.
                cached = client.post(url, json={'revision': case['revision'], 'cloud_data_approved': True})
                assert cached.json() == response.json()
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
