#!/usr/bin/env python3
"""Create a portable installer archive without macOS metadata or local state."""
from pathlib import Path
import tarfile
from source_files import source_files

def package(base, out):
    files = []
    for path in sorted(base.iterdir()):
        if path.is_file() and path.suffix in ('.py', '.sh', '.md'):
            if path.is_symlink():
                raise ValueError('Unexpected installer symlink')
            files.append((path, 'projectflow/' + path.name))
    for name in ['templates', 'generation-skills', 'projectbuild', 'demo-preview']:
        root = base / name if (base / name).exists() else base.parent / name
        for path in source_files(root):
            files.append((path, 'projectflow/' + name + '/' + path.relative_to(root).as_posix()))
    with tarfile.open(out, 'w:gz', format=tarfile.USTAR_FORMAT) as archive:
        for path, name in files:
            info = archive.gettarinfo(str(path), arcname=name)
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            info.mtime = 0
            with path.open('rb') as source:
                archive.addfile(info, source)
    return out


if __name__ == '__main__':
    print(package(Path(__file__).resolve().parent,
                  Path('/private/tmp/picoclaw-projectflow.tar.gz')))
