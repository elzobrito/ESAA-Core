import hashlib
import os
from pathlib import Path

import pytest
from esaa.binary_payload import stage_binary

pytestmark = pytest.mark.skipif(os.name != "posix", reason="secure POSIX dirfd required")


def stage(tmp_path, relative, data, limit=None, declared=None, digest=None):
    return stage_binary(tmp_path, relative, tmp_path, size=len(data) if declared is None else declared,
                        sha256=digest or hashlib.sha256(data).hexdigest(),
                        limit=len(data) if limit is None else limit)


def test_large_binary_is_staged_identically(tmp_path):
    data = b'\x89PNG\r\n\x1a\n' + bytes(range(256)) * 10000
    (tmp_path / 'source').write_bytes(data)
    result = stage(tmp_path, 'source', data)
    assert result.read_bytes() == data
    assert result.stat().st_mode & 0o777 == 0o600


def test_limit_and_integrity_fail_without_stage(tmp_path):
    data = b'correct'
    (tmp_path / 'source').write_bytes(data)
    for kwargs in ({'limit': 6}, {'declared': 6}, {'digest': '0' * 64}):
        with pytest.raises(ValueError): stage(tmp_path, 'source', data, **kwargs)
        assert not list(tmp_path.glob('binary-*'))


@pytest.mark.parametrize('path', ['/etc/passwd', '../secret', 'sub/../secret', 'a//b', './source', 'x\\y'])
def test_reject_unsafe_path(tmp_path, path):
    with pytest.raises(ValueError): stage(tmp_path, path, b'')


def test_reject_symlinks_and_hardlinks(tmp_path):
    target = tmp_path / 'source'; target.write_bytes(b'x')
    (tmp_path / 'link').symlink_to(target)
    with pytest.raises(OSError): stage(tmp_path, 'link', b'x')
    outside = tmp_path.parent / 'outside'; outside.mkdir(exist_ok=True)
    (tmp_path / 'dirlink').symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError): stage(tmp_path, 'dirlink/file', b'x')
    os.link(target, tmp_path / 'hardlink')
    with pytest.raises(ValueError): stage(tmp_path, 'source', b'x')


def test_reject_invalid_arguments(tmp_path):
    (tmp_path / 'source').write_bytes(b'x')
    with pytest.raises(ValueError): stage_binary(tmp_path, 'source', tmp_path, size=True, sha256='0'*64, limit=3)
    with pytest.raises(ValueError): stage_binary(tmp_path, 'source', tmp_path, size=1, sha256='bad', limit=3)
