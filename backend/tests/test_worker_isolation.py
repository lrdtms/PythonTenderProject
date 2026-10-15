"""The worker process must register every module's tables without the API app being imported.

The rest of the suite imports the API first, which hides a missing model import in the worker
(SQLAlchemy then fails to resolve foreign keys at the first flush).
"""

import importlib
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent

CODE = """
import sys
import app.worker.main
import app.worker.handlers
assert 'app.api' not in sys.modules, 'worker imported the API'
from sqlalchemy.orm import configure_mappers
configure_mappers()
from app.db.base import Base
print('TABLES=' + ','.join(sorted(Base.metadata.tables)))
"""


def _expected_tables() -> set[str]:
    from app.db.base import Base

    for models in sorted((BACKEND / "app" / "modules").glob("*/models.py")):
        importlib.import_module(f"app.modules.{models.parent.name}.models")
    return set(Base.metadata.tables)


def test_worker_entry_registers_every_table_without_the_api():
    env = {**os.environ, "PYTHONPATH": str(BACKEND)}
    result = subprocess.run(  # noqa: S603 - fixed interpreter and code string
        [sys.executable, "-I", "-c", CODE],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    line = next(x for x in result.stdout.splitlines() if x.startswith("TABLES="))
    tables = set(line.removeprefix("TABLES=").split(","))
    assert tables == _expected_tables()
    assert len(tables) >= 8
