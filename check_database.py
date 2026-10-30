"""Read-only SQLite integrity and row-count check; never create a missing DB."""
import sqlite3
from config import settings


def main():
    path = settings.SQLITE_DATABASE_PATH
    if not path.is_file():
        print("SQLite database does not exist. Initialize it explicitly or perform a search.")
        return 1
    db = None
    try:
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=10)
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Integrity check failed")
        counts = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in ("products", "price_history", "searches")}
    except Exception:
        print("SQLite check failed. Check database path, schema, permissions, and disk space.")
        return 1
    finally:
        if db is not None:
            db.close()
    print("SQLite integrity check passed. Row counts:", counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
