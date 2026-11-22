"""Where the cold tier's files go (owner amendments D1, D2). The MVP runs on one server, so the archive is a directory
on that machine (COLD_ARCHIVE_DIR; best on another disk or partition); off-server copies are the backups' business.
Code that writes or reads the archive asks `target()` for a `Target` and uses only its methods, so another kind of
target (an object store) can be added later without touching the tiers.

A file appears whole or not at all: it is written beside its final name, flushed to the disk, then renamed."""
import hashlib
import os
import tempfile
from pathlib import Path

from django.conf import settings


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


class Target:
    """The archive's interface: write a file whole, say where to read it, its checksum, whether it is there."""

    def write(self, name, produce):
        raise NotImplementedError

    def path(self, name):
        raise NotImplementedError

    def exists(self, name):
        raise NotImplementedError

    def sha256(self, name):
        raise NotImplementedError

    def scratch(self):
        """A directory for temporary files on the archive's own disk (an export's intermediate file)."""
        raise NotImplementedError


class LocalDirectory(Target):
    def __init__(self, root):
        self.root = Path(root).resolve()

    def path(self, name):
        found = (self.root / name).resolve()
        if self.root not in found.parents:
            raise ValueError(f'{name} is outside the archive directory.')
        return found

    def write(self, name, produce):
        """`produce(path)` writes the file at a temporary path; it is then made durable and renamed to `name`. If
        produce fails, nothing is left behind."""
        final = self.path(name)
        final.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix='.writing-', dir=final.parent)
        os.close(handle)
        try:
            os.unlink(temporary)               # produce writes the file itself (DuckDB refuses an existing one)
            produce(temporary)
            with open(temporary, 'rb+') as stream:
                os.fsync(stream.fileno())
            os.replace(temporary, final)
        except BaseException:
            if os.path.exists(temporary):
                os.unlink(temporary)
            raise
        if hasattr(os, 'O_DIRECTORY'):          # the rename itself survives a power cut (not on Windows)
            folder = os.open(final.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(folder)
            finally:
                os.close(folder)
        return final

    def exists(self, name):
        return self.path(name).is_file()

    def sha256(self, name):
        return sha256_of(self.path(name))

    def scratch(self):
        folder = self.root / '.scratch'
        folder.mkdir(parents=True, exist_ok=True)
        return folder


def target():
    """The configured archive, or None when the cold tier is off (no COLD_ARCHIVE_DIR)."""
    root = getattr(settings, 'COLD_ARCHIVE_DIR', '')
    return LocalDirectory(root) if root else None
