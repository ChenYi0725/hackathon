"""Local CPU OCR worker; never calls an external document-processing service."""
import json
import math
import statistics
import sys
import unicodedata
from pathlib import Path


def layout_text(lines, width):
    """Group boxes into rows and preserve horizontal gaps for the legacy form parser."""
    rows = []
    for line in sorted(lines, key=lambda x: ((x['bbox'][1] + x['bbox'][3]) / 2, x['bbox'][0])):
        x1, y1, x2, y2 = line['bbox']
        center = (y1 + y2) / 2
        row = next((r for r in reversed(rows[-3:]) if abs(r['center'] - center) <= min(r['height'], y2 - y1) * .45), None)
        if row is None:
            row = {'center': center, 'height': y2 - y1, 'lines': []}
            rows.append(row)
        row['lines'].append(line)
    def columns(text):
        return sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in text)
    sizes = [(line['bbox'][2] - line['bbox'][0]) / max(1, columns(line['text'])) for line in lines]
    unit = max(3, statistics.median(sizes)) if sizes else max(3, width / 150)
    output = []
    for row in rows:
        text, end = '', 0
        for line in sorted(row['lines'], key=lambda x: x['bbox'][0]):
            start = min(500, round(line['bbox'][0] / unit))
            text += ' ' * max(2 if text else 0, start - end) + line['text']
            end = max(start, end + 2) + columns(line['text'])
        output.append(text.rstrip())
    return '\n'.join(output)


def recognize(path, options):
    import pypdfium2 as pdfium
    from app.infrastructure.ocr_backends import create_predictor
    from app.infrastructure.pdf_text_layout import read_text_lines
    try:
        document = pdfium.PdfDocument(str(path))
        if not 1 <= len(document) <= 200:
            raise ValueError
        # Reject huge pages before rendering or downloading any OCR models.
        for page in document:
            w, h = page.get_size()
            page.close()
            if w <= 0 or h <= 0 or w * h * (options['dpi'] / 72) ** 2 > 14_000_000:
                raise ValueError
    except Exception:
        raise ValueError('invalid_pdf') from None
    pages = []
    try:
        predict = None
        for index in range(len(document)):
            page = document[index]
            if options.get('text_layer', True):
                try:
                    native_lines = read_text_lines(page, options['dpi'])
                except (pdfium.PdfiumError, ValueError):
                    native_lines = None
                if native_lines is not None:
                    w, h = page.get_size()
                    width, height = math.ceil(w * options['dpi'] / 72), math.ceil(h * options['dpi'] / 72)
                    text = layout_text(native_lines, width)
                    if len(text) > 100000:
                        raise ValueError('invalid_pdf')
                    pages.append({'page': index + 1, 'text': text, 'method': 'pdf-text',
                                  'width': width, 'height': height, 'lines': native_lines})
                    page.close()
                    continue
            if predict is None:
                predict = create_predictor(options)
            import numpy as np
            bitmap = page.render(scale=options['dpi'] / 72)
            image = bitmap.to_pil().convert('RGB')
            width, height = image.size
            lines = []
            for text, score, box in predict(np.asarray(image)[:, :, ::-1].copy()):
                if not text.strip() or not math.isfinite(float(score)):
                    continue
                lines.append({'text': text, 'confidence': round(float(score), 4), 'bbox': [int(v) for v in box]})
            text = layout_text(lines, width)
            if len(text) > 100000:
                raise ValueError('invalid_pdf')
            pages.append({'page': index + 1, 'text': text, 'method': options.get('engine', 'paddleocr'), 'width': width, 'height': height, 'lines': lines})
            image.close()
            bitmap.close()
            page.close()
    finally:
        document.close()
    return pages


def main():
    path, output, options = sys.argv[1:]
    try:
        result = {'pages': recognize(Path(path), json.loads(options))}
        exit_code = 0
    except Exception as exc:
        result = {'error': 'invalid_pdf' if str(exc) == 'invalid_pdf' else 'ocr_failed'}
        exit_code = 1
    Path(output).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
