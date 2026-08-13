from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_revision_chain_is_valid():
    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert heads == ["a1b2c3d4e5f6"]

    revisions = {rev.revision: rev for rev in script.walk_revisions()}
    assert "34b6d855017a" in revisions
    assert revisions["a1b2c3d4e5f6"].down_revision == "34b6d855017a"
