"""Disposable durable HTTP representations, not workflow authority."""

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from lighthouse.adapters.github.facts import API_VERSION
from lighthouse.adapters.github.transport import MAX_BODY, MEDIA, Held, Scope

_SCHEMA = (
    "CREATE TABLE response (key TEXT PRIMARY KEY NOT NULL, "
    "body BLOB NOT NULL, etag TEXT, next TEXT, digest TEXT NOT NULL) STRICT"
)


@dataclass(frozen=True)
class Page:
    body: bytes
    etag: str | None
    link: str | None

    def digest(self) -> str:
        return sha256(json.dumps((self.etag, self.link)).encode() + b"\0" + self.body).hexdigest()


class Cache:
    """Use only an explicitly selected, disposable cache file."""

    def __init__(self, path: Path) -> None:
        self._path = path
        with closing(sqlite3.connect(path, timeout=2)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            schema = conn.execute("SELECT sql FROM sqlite_schema WHERE sql IS NOT NULL").fetchall()
            version = conn.execute("PRAGMA user_version").fetchone()
            if not schema and version == (0,):
                conn.execute(_SCHEMA)
                conn.execute("PRAGMA user_version=1")
            elif schema != [(_SCHEMA,)] or version != (1,):
                raise Held("cache-invalid")

    @staticmethod
    def _key(scope: Scope, url: str) -> str:
        return json.dumps((scope.repository, scope.read_identity, url, API_VERSION, MEDIA))

    def read(self, scope: Scope, url: str) -> Page | None:
        with closing(sqlite3.connect(self._path, timeout=2)) as conn:
            row = conn.execute("SELECT body,etag,next,digest FROM response WHERE key=?",
                               (self._key(scope, url),)).fetchone()
        if row is None:
            return None
        page = Page(*row[:3])
        if not page.body or len(page.body) > MAX_BODY or page.digest() != row[3]:
            raise Held("cache-invalid")
        return page

    def write(self, scope: Scope, url: str, page: Page) -> None:
        with closing(sqlite3.connect(self._path, timeout=2)) as conn, conn:
            conn.execute("INSERT OR REPLACE INTO response VALUES (?,?,?,?,?)",
                         (self._key(scope, url), page.body, page.etag, page.link, page.digest()))
