"""CPU runtimes used only inside the bounded PDF worker."""
import json
from pathlib import Path


def create_predictor(options):
    if options.get('engine', 'paddleocr') == 'paddleocr':
        from paddleocr import PaddleOCR

        engine = PaddleOCR(
            device='cpu', text_detection_model_name=options['detection_model'],
            text_recognition_model_name=options['recognition_model'],
            use_doc_orientation_classify=False, use_doc_unwarping=False,
            use_textline_orientation=False, cpu_threads=options['cpu_threads'], enable_mkldnn=False,
        )

        def predict(image):
            for result in engine.predict(image):
                value = result.json
                value = json.loads(value) if isinstance(value, str) else value
                value = value.get('res', value)
                yield from zip(value.get('rec_texts', []), value.get('rec_scores', []), value.get('rec_boxes', []))
    elif options['engine'] == 'rapidocr':
        from rapidocr import ModelType, OCRVersion, RapidOCR

        # Pin v5 explicitly: RapidOCR >=3.9 defaults to different v6 models.
        params = {
            'Global.use_cls': False,
            'Global.model_root_dir': str(Path.home() / '.cache' / 'rapidocr'),
            'EngineConfig.onnxruntime.intra_op_num_threads': options['cpu_threads'],
            'EngineConfig.onnxruntime.inter_op_num_threads': 1,
            'EngineConfig.onnxruntime.use_cuda': False,
        }
        for task, model in [('Det', options['detection_model']), ('Rec', options['recognition_model'])]:
            params[task + '.ocr_version'] = OCRVersion.PPOCRV5
            params[task + '.model_type'] = ModelType.SERVER if '_server_' in model else ModelType.MOBILE
        engine = RapidOCR(params=params)

        def predict(image):
            result = engine(image)
            if result.boxes is None:
                return
            for text, score, polygon in zip(result.txts, result.scores, result.boxes):
                yield text, score, [polygon[:, 0].min(), polygon[:, 1].min(),
                                    polygon[:, 0].max(), polygon[:, 1].max()]
    else:
        raise ValueError('Unknown OCR engine')
    return predict
