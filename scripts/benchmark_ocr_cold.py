"""Measure full process wall time for a single PDF, with downloaded models present."""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidates', nargs='+')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    measurements = []
    for repeat in range(3):
        # Alternate the order to reduce effects of host activity and CPU credits.
        order = args.candidates if repeat % 2 == 0 else list(reversed(args.candidates))
        for candidate in order:
            output = args.output_dir / f'cold-{candidate}-{repeat}.json'
            started = time.perf_counter()
            subprocess.run([sys.executable, '-m', 'scripts.benchmark_ocr', candidate,
                            '--repeats', '1', '--document', 'clean.pdf', '--output', str(output)],
                           check=True, timeout=300)
            measurements.append({'candidate': candidate, 'repeat': repeat,
                                 'seconds': time.perf_counter() - started})
    (args.output_dir / 'cold-summary.json').write_text(json.dumps(measurements, indent=2))
    print(json.dumps(measurements, indent=2))


if __name__ == '__main__':
    main()
