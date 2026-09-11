#!/usr/bin/env python3
"""Create a portable installer archive without macOS metadata or local state."""
from pathlib import Path
import tarfile

base = Path(__file__).resolve().parent
out = Path('/private/tmp/picoclaw-projectflow.tar.gz')
files = []
for path in base.iterdir():
    if path.is_file() and path.suffix in ('.py', '.sh', '.md'):
        files.append((path, 'projectflow/' + path.name))
for name in ['templates', 'generation-skills', 'projectbuild', 'demo-preview']:
    root = base / name if (base / name).exists() else base.parent / name
    for path in sorted(root.rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts:
            if path.is_symlink() or any(p.startswith('.') for p in path.relative_to(root).parts):
                raise ValueError('Unexpected hidden file or symlink')
            files.append((path, 'projectflow/' + name + '/' + path.relative_to(root).as_posix()))
with tarfile.open(out, 'w:gz', format=tarfile.USTAR_FORMAT) as archive:
    for path, name in files:
        info = archive.gettarinfo(str(path), arcname=name)
        info.uid = info.gid = 0
        info.uname = info.gname = ''
        info.mtime = 0
        with path.open('rb') as source:
            archive.addfile(info, source)
print(out)
