"""CPU or NVIDIA GPU OCR worker; document processing stays on the service host."""
import json
import math
import statistics
import sys
import unicodedata
from pathlib import Path


class GpuUnavailable(RuntimeError):
    """The explicitly requested GPU cannot be used; never fall back to CPU."""


def create_ocr(options):
    import paddle
    from paddleocr import PaddleOCR
    device = options.get('device', 'cpu')
    if device.startswith('gpu:'):
        try:
            if not paddle.is_compiled_with_cuda() or int(device.split(':')[1]) >= paddle.device.cuda.device_count():
                raise GpuUnavailable
            paddle.set_device(device)
        except Exception as exc:
            raise GpuUnavailable from exc
    return PaddleOCR(
        device=device,
        text_detection_model_name=options['detection_model'], text_recognition_model_name=options['recognition_model'],
        use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False,
        cpu_threads=options['cpu_threads'], enable_mkldnn=False,
    )


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
    import numpy as np
    import pypdfium2 as pdfium
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
        ocr = create_ocr(options)
        for index in range(len(document)):
            page = document[index]
            bitmap = page.render(scale=options['dpi'] / 72)
            image = bitmap.to_pil().convert('RGB')
            width, height = image.size
            predictions = list(ocr.predict(np.asarray(image)[:, :, ::-1].copy()))
            lines = []
            for result in predictions:
                value = result.json
                if isinstance(value, str):
                    value = json.loads(value)
                result = value.get('res', value)
                for text, score, box in zip(result.get('rec_texts', []), result.get('rec_scores', []), result.get('rec_boxes', [])):
                    if not text.strip() or not math.isfinite(float(score)):
                        continue
                    lines.append({'text': text, 'confidence': round(float(score), 4), 'bbox': [int(v) for v in box]})
            text = layout_text(lines, width)
            if len(text) > 100000:
                raise ValueError('invalid_pdf')
            pages.append({'page': index + 1, 'text': text, 'method': 'paddleocr',
                          'device': options.get('device', 'cpu'), 'width': width, 'height': height, 'lines': lines})
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
    except GpuUnavailable:
        result = {'error': 'gpu_unavailable'}
        exit_code = 1
    except Exception as exc:
        result = {'error': 'invalid_pdf' if str(exc) == 'invalid_pdf' else 'ocr_failed'}
        exit_code = 1
    Path(output).write_text(json.dumps(result, ensure_ascii=False))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
