#!/usr/bin/env python3
"""Export only the image approved for this preview from its passed report."""
import gzip
import json
from pathlib import Path
import shutil
import subprocess
import sys

from install import IMAGE


def validate(report):
    if report.get('status') != 'passed' or report.get('image_id') != IMAGE:
        raise ValueError('Expected the approved, passed Phoenix release report')
    if not {'production_release_image', 'release_migrations', 'http_health'} <= set(report.get('checks', [])):
        raise ValueError('Release report is missing required checks')


def main():
    if len(sys.argv) != 3:
        raise SystemExit('Usage: export.py REPORT.json NEW-IMAGE.tar.gz')
    validate(json.loads(Path(sys.argv[1]).read_text()))
    target = Path(sys.argv[2]).resolve()
    if target.exists():
        raise ValueError('Output already exists')
    temporary = target.with_suffix(target.suffix + '.partial')
    if temporary.exists():
        raise ValueError('Partial output already exists; inspect it before retrying')
    print('Exporterar den testade imagen; detta kan ta några minuter.', flush=True)
    try:
        with temporary.open('xb') as raw:
            with subprocess.Popen(['docker', 'image', 'save', IMAGE], stdout=subprocess.PIPE) as process:
                with gzip.GzipFile(fileobj=raw, mode='wb') as compressed:
                    shutil.copyfileobj(process.stdout, compressed)
                if process.wait() != 0:
                    raise RuntimeError('docker image save failed')
        temporary.rename(target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    print(str(target), flush=True)


if __name__ == '__main__':
    main()
