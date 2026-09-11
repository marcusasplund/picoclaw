"""Validate and transfer the exact Solid build artifact; no generated host code."""
import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

LIMIT = 20 * 1024 * 1024
WEBROOT = Path('/var/www/picoclaw-demo-preview')


def checked(files):
    if not isinstance(files, dict) or not 1 <= len(files) <= 5000:
        raise ValueError('Invalid frontend file list')
    decoded = {}
    size = 0
    for name, data in files.items():
        path = PurePosixPath(name)
        if not name or name == '.' or str(path) != name or path.is_absolute() or '..' in path.parts or '\\' in name:
            raise ValueError('Unsafe frontend path')
        if any(part.startswith('.') for part in path.parts):
            raise ValueError('Hidden frontend paths are not supported')
        value = base64.b64decode(data, validate=True)
        size += len(value)
        if size > LIMIT:
            raise ValueError('Frontend too large')
        decoded[name] = value
    if 'index.html' not in decoded:
        raise ValueError('Missing index.html')
    for name in decoded:
        if any(str(parent) in decoded for parent in PurePosixPath(name).parents):
            raise ValueError('Conflicting file paths')
    digest = hashlib.sha256()
    for name, data in sorted(decoded.items()):
        digest.update(json.dumps([name, hashlib.sha256(data).hexdigest()]).encode() + b'\n')
    return digest.hexdigest(), decoded


def unpack(path):
    if path.stat().st_size > LIMIT * 2:
        raise ValueError('Frontend package too large')
    payload = json.loads(path.read_text())
    digest, files = checked(payload['files'])
    if payload['artifact_sha256'] != digest:
        raise ValueError('Frontend hash mismatch')
    return digest, files


def export(report_path, target):
    report = json.loads(report_path.read_text())
    if report.get('status') != 'passed' or ['npm', 'run', 'build'] not in report.get('checks', []):
        raise ValueError('Expected a passed Solid build report')
    root = report_path.parent / 'dist'
    if root.is_symlink():
        raise ValueError('Symlink dist is not supported')
    files = {}
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('Symlink artifact is not supported')
        if path.is_file():
            files[path.relative_to(root).as_posix()] = base64.b64encode(path.read_bytes()).decode()
    digest, _ = checked(files)
    if digest != report.get('artifact_sha256'):
        raise ValueError('Frontend differs from passed build')
    if target.exists():
        existing, _ = unpack(target)
        if existing != digest:
            raise ValueError('Existing export has a different frontend hash')
        return
    with target.open('x') as output:
        json.dump({'artifact_sha256': digest, 'files': files}, output)


def install_frontend(digest, files):
    if not re.fullmatch('[a-f0-9]{64}', digest) or WEBROOT.is_symlink():
        raise ValueError('Unsafe frontend destination')
    WEBROOT.mkdir(mode=0o755, exist_ok=True)
    WEBROOT.chmod(0o755)
    target = WEBROOT / digest
    if target.is_symlink():
        raise ValueError('Unsafe release destination')
    target.mkdir(mode=0o755, exist_ok=True)
    target.chmod(0o755)
    for name, data in files.items():
        path = target / name
        parent = target
        for part in PurePosixPath(name).parts[:-1]:
            parent = parent / part
            if parent.is_symlink():
                raise ValueError('Unsafe directory')
            parent.mkdir(mode=0o755, exist_ok=True)
            parent.chmod(0o755)
        if path.is_symlink():
            raise ValueError('Unsafe file')
        if path.exists():
            if path.read_bytes() != data:
                raise ValueError('Existing artifact has different bytes')
        else:
            with path.open('xb') as output:
                output.write(data)
        path.chmod(0o644)
