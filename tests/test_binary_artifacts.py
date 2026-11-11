import hashlib
import os

import pytest

from esaa.binary_artifacts import restore_blob, store_blob

pytestmark = pytest.mark.skipif(os.name != "posix", reason="requires POSIX staging")


def test_large_blob_deduplicate_restore_and_detect_corruption(tmp_path):
    data = b"\x1aE\xdf\xa3" + bytes(range(256)) * 10000
    src = tmp_path / "src"
    src.mkdir()
    (src / "video").write_bytes(data)
    blobs = tmp_path / "blobs"
    dest = tmp_path / "dest"
    dest.mkdir()
    sha = hashlib.sha256(data).hexdigest()
    blob = store_blob(src, "video", blobs, size=len(data), sha256=sha, limit=len(data))
    assert blob.read_bytes() == data
    assert store_blob(src, "video", blobs, size=len(data), sha256=sha, limit=len(data)) == blob
    restore_blob(blobs, sha, dest / "video", size=len(data), limit=len(data))
    assert (dest / "video").read_bytes() == data
    blob.write_bytes(b"broken")
    with pytest.raises(ValueError):
        restore_blob(blobs, sha, dest / "video", size=len(data), limit=len(data))
    assert (dest / "video").read_bytes() == data
    with pytest.raises(ValueError):
        store_blob(src, "video", blobs, size=len(data), sha256=sha, limit=len(data))


def test_blob_limit_hash_and_symlink_rejected(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "file").write_bytes(b"abc")
    blobs = tmp_path / "blobs"
    sha = hashlib.sha256(b"abc").hexdigest()
    with pytest.raises(ValueError):
        store_blob(src, "file", blobs, size=3, sha256=sha, limit=2)
    with pytest.raises(ValueError):
        store_blob(src, "file", blobs, size=3, sha256="z" * 64, limit=3)
    blobs.mkdir(exist_ok=True)
    (blobs / sha).symlink_to(src / "file")
    with pytest.raises(OSError):
        store_blob(src, "file", blobs, size=3, sha256=sha, limit=3)
