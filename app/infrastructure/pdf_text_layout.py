"""Extract visible digital text with the same pixel geometry as OCR.

Conservative page eligibility: images, transformed forms, annotations, hidden text,
unsupported page transforms or unusable character maps require normal OCR.
No valuation rules or document-specific repairs belong here.
"""
import math
import unicodedata


def read_text_lines(page, dpi):
    from pypdfium2 import raw

    width, height = page.get_size()
    if page.get_rotation() or any(abs(a - b) > .01 for a, b in zip(
        page.get_bbox(), (0, 0, width, height)
    )) or raw.FPDFPage_GetAnnotCount(page):
        return None
    textpage = page.get_textpage()
    try:
        if not 30 <= textpage.count_chars() <= 100000:
            return None
        lines = []
        for index, obj in enumerate(page.get_objects(textpage=textpage)):
            if index >= 50000 or obj.type == raw.FPDF_PAGEOBJ_IMAGE:
                return None
            if obj.type == raw.FPDF_PAGEOBJ_FORM:
                a, b, c, d, _, _ = obj.get_matrix().get()
                if (a, b, c, d) != (1, 0, 0, 1) or obj.level >= 14:
                    return None
                continue
            if obj.type != raw.FPDF_PAGEOBJ_TEXT:
                continue
            # An invisible OCR overlay is not evidence that the visible page is digital text.
            if raw.FPDFTextObj_GetTextRenderMode(obj) not in (
                raw.FPDF_TEXTRENDERMODE_FILL, raw.FPDF_TEXTRENDERMODE_STROKE,
                raw.FPDF_TEXTRENDERMODE_FILL_STROKE,
            ):
                return None
            text = obj.extract().strip()
            if not text:
                continue
            if any(unicodedata.category(c) in {'Cc', 'Cs', 'Co', 'Cn'} or c == '\ufffd' for c in text):
                return None
            left, bottom, right, top = obj.get_bounds()
            container = obj.container
            while container is not None:
                _, _, _, _, dx, dy = container.get_matrix().get()
                left, right, bottom, top = left + dx, right + dx, bottom + dy, top + dy
                container = container.container
            if not (0 <= (left + right) / 2 <= width and 0 <= (bottom + top) / 2 <= height):
                continue
            box = [left, height - top, right, height - bottom]
            if not all(math.isfinite(value) for value in box):
                return None
            if right <= left or top <= bottom or min(box) < 0 or right > width or top > height:
                return None
            lines.append({'text': text, 'confidence': 1.0, 'bbox': box})
        if sum(len(line['text']) for line in lines) < 30:
            return None
        lines = _join_vertical_runs(lines)
        scale = dpi / 72
        for line in lines:
            left, top, right, bottom = line['bbox']
            line['bbox'] = [math.floor(left * scale), math.floor(top * scale),
                            math.ceil(right * scale), math.ceil(bottom * scale)]
        return lines
    finally:
        textpage.close()


def _join_vertical_runs(lines):
    """Join consecutive vertical glyph objects, retaining their union bounds.

    PDF producers often store each upright CJK character in a separate object.
    Source order and proximity prevent joining unrelated columns or cells.
    """
    result = []
    index = 0
    while index < len(lines):
        run = [lines[index]]
        index += 1
        while index < len(lines):
            previous, current = run[-1], lines[index]
            if not all(len(line['text']) == 1 and '\u3000' <= line['text'] <= '\u9fff'
                       for line in (previous, current)):
                break
            x1, y1, x2, y2 = previous['bbox']
            left, top, right, bottom = current['bbox']
            if (abs((x1 + x2 - left - right) / 2) > max(x2 - x1, right - left) * .5
                or not 0 < top - y2 < max(y2 - y1, bottom - top) * 1.8):
                break
            run.append(current)
            index += 1
        if len(run) < 3:
            result.extend(run)
        else:
            result.append({'text': ''.join(line['text'] for line in run), 'confidence': 1.0,
                           'bbox': [min(line['bbox'][0] for line in run),
                                    min(line['bbox'][1] for line in run),
                                    max(line['bbox'][2] for line in run),
                                    max(line['bbox'][3] for line in run)]})
    return result
