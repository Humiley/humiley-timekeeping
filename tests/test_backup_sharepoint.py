"""The SharePoint/OneDrive off-box uploader only ever sends ENCRYPTED snapshots.

This is the one property in that script that has to be absolute. The backup directory sits next to
`.backup-key`, and putting the key in the same place as the ciphertext would make the encryption
decorative — one compromised M365 account would hand over payroll, national IDs, bank details and GPS
history in the clear. Plaintext snapshots are equally forbidden: they are exactly the unencrypted PII
dump that backup.sh fail-closes to prevent.

The filter is a suffix allow-list rather than a deny-list, so a new artefact type is excluded by
default instead of leaking until somebody remembers to add a rule.
"""
import importlib.util
import os

_MOD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backup_sharepoint.py")


def _load():
    spec = importlib.util.spec_from_file_location("backup_sharepoint", _MOD)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_only_encrypted_artefacts_are_eligible():
    m = _load()
    allowed = [
        "timekeeping-2026-08-04_020000.db.gz.enc",
        "procurement-2026-08-04_020000.sql.gz.enc",
        "proc-storage-2026-08-04_020000.tgz.enc",
    ]
    forbidden = [
        ".backup-key",                              # THE key — must never travel with the ciphertext
        "backup.key",
        "timekeeping-2026-08-04.db",                # plaintext SQLite
        "timekeeping-2026-08-04.db.gz",             # plaintext, merely compressed
        "procurement-2026-08-04.sql.gz",
        "proc-storage-2026-08-04.tgz",
        ".env",
        "notes.txt",
    ]
    for name in allowed:
        assert name.endswith(m.WANTED), name + " should be uploaded"
    for name in forbidden:
        assert not name.endswith(m.WANTED), name + " MUST NOT leave the server"


def test_the_allow_list_is_exactly_the_three_encrypted_kinds():
    """Pin the tuple itself: widening it is a security decision, not a tidy-up."""
    m = _load()
    assert set(m.WANTED) == {".db.gz.enc", ".sql.gz.enc", ".tgz.enc"}


def test_upload_chunk_size_is_a_multiple_of_320KiB():
    """Graph rejects an upload session whose chunks are not a multiple of 320 KiB — a database
       snapshot is far past the 4 MB single-PUT limit, so this path is the normal one, not an edge."""
    m = _load()
    assert m.CHUNK % (320 * 1024) == 0
    assert m.CHUNK > 4 * 1024 * 1024 or m.CHUNK >= 320 * 1024


def test_env_is_parsed_not_executed(tmp_path, monkeypatch):
    """A backup script must never source a config file — .env is read as key=value only."""
    m = _load()
    env = tmp_path / ".env"
    env.write_text('BACKUP_SP_URL="https://x.sharepoint.com/sites/S/Shared Documents/B"\n'
                   "# a comment\n"
                   "BACKUP_SP_RETAIN=30\n"
                   "$(touch /tmp/pwned)\n", encoding="utf-8")
    monkeypatch.setattr(m, "HERE", str(tmp_path))
    got = m._env()
    assert got["BACKUP_SP_URL"] == "https://x.sharepoint.com/sites/S/Shared Documents/B"
    assert got["BACKUP_SP_RETAIN"] == "30"
    assert not os.path.exists("/tmp/pwned")


def test_sharepoint_folder_url_parsing():
    """Admins paste either the clean folder path or the browser's ?id= view URL."""
    m = _load()
    host, site, rel = m._parse_sp_folder(
        "https://humiley.sharepoint.com/sites/Finance/Shared Documents/Portal Backups")
    assert (host, site, rel) == ("humiley.sharepoint.com", "/sites/Finance", "Portal Backups")

    host, site, rel = m._parse_sp_folder(
        "https://humiley.sharepoint.com/sites/Finance/Shared%20Documents/Forms/AllItems.aspx"
        "?id=%2Fsites%2FFinance%2FShared%20Documents%2FPortal%20Backups&viewid=abc")
    assert (host, site, rel) == ("humiley.sharepoint.com", "/sites/Finance", "Portal Backups")

    for bad in ("not-a-url", "https://humiley.sharepoint.com/", "https://x/notsites/Finance"):
        try:
            m._parse_sp_folder(bad)
            raise AssertionError("should have rejected " + bad)
        except ValueError:
            pass
