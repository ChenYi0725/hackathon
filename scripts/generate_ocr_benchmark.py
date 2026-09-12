"""Generate image-only synthetic tables and independent cell ground truth (no case data)."""
import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


def generate(font_path, output):
    output.mkdir(parents=True, exist_ok=True)
    truth = []
    rows = [
        ['因素', '比準地', '比較標的', '修正率'],
        ['道路寬度', '18', '6', '-12.50%'],
        ['土地深度', '25.5', '100.0', '0%'],
        ['交通距離', '150', '400', '+3.25%'],
        ['環境污染', '無', '輕微', '-2%'],
        ['臨路狀況', '雙面臨路', '單面臨路', '5%'],
        ['合成單價', '123,456', '98,765', '-0.75%'],
        ['日期調整', '1.02', '0.98', '2.00%'],
        ['缺值測試', '0', '未提供', '無'],
    ]
    for name, size, blur in [('clean', 32, 0), ('dense', 24, 0), ('faint', 28, .45)]:
        image = Image.new('RGB', (1488, 2105), 'white')
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(str(font_path), size)
        draw.text((100, 100), '合成資料：估價審查 OCR 測試', font=font, fill='black')
        cells = []
        xs = [100, 470, 790, 1110, 1400]
        top, step = 220, 100 if name != 'dense' else 65
        for row_idx, row in enumerate(rows):
            for col, text in enumerate(row):
                box = [xs[col], top + row_idx * step, xs[col+1], top + (row_idx+1)*step]
                draw.rectangle(box, outline='#777777', width=1)
                draw.text((box[0]+20, box[1]+20), text, font=font, fill='#666666' if name=='faint' else 'black')
                cells.append({'text': text, 'bbox': box, 'numeric': any(c.isdigit() for c in text)})
        if blur:
            image = image.filter(ImageFilter.GaussianBlur(blur))
        image.save(output / f'{name}.pdf', resolution=180)
        image.save(output / f'{name}.png')
        truth.append({'file': f'{name}.pdf', 'width': image.width, 'height': image.height, 'cells': cells})
    (output / 'truth.json').write_text(json.dumps(truth, ensure_ascii=False, indent=2))
    # A held-out ruleset layout exercises the actual coordinate-based compiler.
    image = Image.new('RGB', (2000, 2800), 'white')
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(font_path), 30)
    def label(text, x, y):
        draw.text((x * 2, y * 2), text, font=font, fill='black')
    label('測試市甲區住宅用地影響地價區域因素評價基準明細表', 100, 20)
    for text, x in [('主要項目', 80), ('細項', 210), ('價格修正率', 330), ('備註', 700)]:
        label(text, x, 80)
    for index, char in enumerate('數值因素'):
        label(char, 215, 165 + index * 24)
    for row, values in enumerate([(0, 5, 10), (-5, 0, 5), (-10, -5, 0)]):
        for col, value in enumerate(values):
            label(str(value), 330 + col * 110, 200 + row * 45)
    for row, text in enumerate(['優：80%以上', '普通：60%以上未滿80%', '劣：未滿60%']):
        label(text, 700, 200 + row * 45)
    image.save(output / 'ruleset.pdf', resolution=180)
    image.save(output / 'ruleset.png')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('tests/fixtures/ocr_benchmark'))
    args = parser.parse_args()
    generate(args.font, args.output)
