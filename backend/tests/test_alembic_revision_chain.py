from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_listing_migration_revision_does_not_import_app_modules():
    backend_root = Path(__file__).resolve().parents[1]
    revision_path = (
        backend_root
        / "alembic"
        / "versions"
        / "c3d4e5f6a7b8_listing_versions_and_proposals.py"
    )
    source = revision_path.read_text(encoding="utf-8")
    assert "from app." not in source
    assert "import app." not in source


def test_alembic_revision_chain_is_valid():
    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert heads == ["c3d4e5f6a7b8"]

    revisions = {rev.revision: rev for rev in script.walk_revisions()}
    assert "34b6d855017a" in revisions
    assert revisions["a1b2c3d4e5f6"].down_revision == "34b6d855017a"
    assert revisions["b2c3d4e5f6a7"].down_revision == "a1b2c3d4e5f6"
    assert revisions["c3d4e5f6a7b8"].down_revision == "b2c3d4e5f6a7"
