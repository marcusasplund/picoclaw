"""Shared source selection for installer archives and frozen generation bundles."""
import os
from pathlib import Path


EXCLUDED = {
    'node_modules', 'dist', 'coverage', '__pycache__', 'deps', '_build',
    '.git', '.cache', '.vite', '.DS_Store', 'erl_crash.dump',
}
ALLOWED_HIDDEN = {'.gitignore', '.oxlintrc.json', '.formatter.exs'}


def source_files(root):
    """Yield ordinary source files, pruning generated trees before reading them."""
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f'Missing or unsafe source directory: {root}')
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(name for name in dirs if name not in EXCLUDED)
        for name in dirs + sorted(names):
            if name in EXCLUDED or name.endswith(('.pyc', '.pyo')):
                continue
            path = Path(directory) / name
            relative = path.relative_to(root)
            if path.is_symlink():
                raise ValueError(f'Unexpected source symlink: {relative}')
            hidden = [part for part in relative.parts if part.startswith('.')]
            live_config = relative.parts[-3:] == ('.impeccable', 'live', 'config.json')
            live_directory = path.is_dir() and (
                relative.parts[-1:] == ('.impeccable',)
                or relative.parts[-2:] == ('.impeccable', 'live'))
            if hidden and not (hidden == [name] and name in ALLOWED_HIDDEN
                               or hidden == ['.impeccable'] and (live_config or live_directory)):
                raise ValueError(f'Unexpected hidden source: {relative}')
            if path.is_dir():
                continue
            if not path.is_file():
                raise ValueError(f'Unexpected special source file: {relative}')
            yield path
