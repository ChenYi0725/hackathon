"""CPU comparison: fixed documents, 2 threads, model downloads excluded from repeats."""
import argparse
import json
import resource
import time
import unicodedata
from pathlib import Path


def normalize(text):
    return ''.join(unicodedata.normalize('NFKC', text).split())


def score(lines, cells):
    matches = []
    for cell in cells:
        x1, y1, x2, y2 = cell['bbox']
        found = [line for line in lines if x1 <= (line['bbox'][0]+line['bbox'][2])/2 < x2
                 and y1 <= (line['bbox'][1]+line['bbox'][3])/2 < y2]
        actual = ''.join(line['text'] for line in sorted(found, key=lambda x: x['bbox'][0]))
        matches.append({'expected': cell['text'], 'actual': actual, 'numeric': cell['numeric'],
                        'exact': normalize(actual) == normalize(cell['text'])})
    return matches


def run(candidate, fixtures, output, repeats):
    start = time.perf_counter()
    import numpy as np
    import pypdfium2 as pdfium
    if candidate.startswith('paddle'):
        from paddleocr import PaddleOCR
        engine = PaddleOCR(device='cpu', text_detection_model_name='PP-OCRv5_mobile_det',
            text_recognition_model_name='PP-OCRv5_mobile_rec' if candidate=='paddle_mobile' else 'PP-OCRv5_server_rec',
            use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False,
            cpu_threads=2, enable_mkldnn=candidate=='paddle_mkldnn')
        def recognize(image):
            lines=[]
            for result in engine.predict(image):
                value=result.json
                value=json.loads(value) if isinstance(value,str) else value
                value=value.get('res',value)
                lines.extend({'text':t,'bbox':[int(v) for v in b],'confidence':float(s)}
                             for t,b,s in zip(value['rec_texts'],value['rec_boxes'],value['rec_scores']))
            return lines
    else:
        from rapidocr import RapidOCR, ModelType, OCRVersion
        params={'Global.use_cls':False, 'EngineConfig.onnxruntime.intra_op_num_threads':2,
                'EngineConfig.onnxruntime.inter_op_num_threads':1}
        for task in ['Det','Rec']:
            params[task+'.ocr_version']=OCRVersion.PPOCRV5
            params[task+'.model_type']=ModelType.SERVER if task=='Rec' and candidate=='rapid_server' else ModelType.MOBILE
        engine=RapidOCR(params=params)
        def recognize(image):
            result=engine(image)
            if result.boxes is None:
                return []
            return [{'text':t,'confidence':float(s),'bbox':[int(b[:,0].min()),int(b[:,1].min()),int(b[:,0].max()),int(b[:,1].max())]}
                    for t,b,s in zip(result.txts,result.boxes,result.scores)]
    load_seconds=time.perf_counter()-start
    truth=json.loads((fixtures/'truth.json').read_text())
    results=[]
    for repeat in range(repeats):
        for document in truth:
            start=time.perf_counter()
            with pdfium.PdfDocument(str(fixtures/document['file'])) as pdf:
                page=pdf[0]
                bitmap=page.render(scale=180/72)
                image=bitmap.to_pil().convert('RGB')
                lines=recognize(np.asarray(image)[:,:,::-1].copy())
                image.close();bitmap.close();page.close()
            results.append({'file':document['file'],'repeat':repeat,'seconds':time.perf_counter()-start,
                            'cells':score(lines,document['cells']),'lines':lines})
            print(candidate, repeat, document['file'], round(results[-1]['seconds'],3),
                  sum(c['exact'] for c in results[-1]['cells']), '/', len(document['cells']), flush=True)
    import importlib.metadata as metadata
    report={'candidate':candidate,'load_seconds':load_seconds,'max_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'versions':{p:metadata.version(p) for p in ['paddleocr','paddlepaddle','rapidocr','onnxruntime','numpy','pypdfium2']},
            'results':results}
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate',choices=['paddle_server','paddle_mobile','paddle_mkldnn','rapid_mobile','rapid_server'])
    parser.add_argument('--fixtures',type=Path,default=Path('tests/fixtures/ocr_benchmark'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--repeats',type=int,default=3)
    args=parser.parse_args()
    run(args.candidate,args.fixtures,args.output,args.repeats)
