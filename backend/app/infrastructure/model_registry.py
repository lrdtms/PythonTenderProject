"""Import every module's ORM models so all tables are registered on ``Base.metadata``.

SQLAlchemy resolves foreign keys by table name, so a process that touches the database must have
every model loaded, not only the ones it uses directly. Entry points (API, worker, migrations)
call ``import_all_models()``; a new module with a ``models.py`` needs no further edit.
"""

import importlib
import pkgutil

import app.modules


def import_all_models() -> None:
    for info in pkgutil.iter_modules(app.modules.__path__):
        if not info.ispkg:
            continue
        name = f"app.modules.{info.name}.models"
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name != name:  # a real missing dependency inside models.py
                raise
