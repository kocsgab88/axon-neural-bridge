"""
AXON Sandbox Validator v3.2
OWNER: GABOR KOCSIS | AXON Neural Bridge
────────────────────────────────────────
1. szint: Statikus biztonsági szűrő (tiltott minták)
2. szint: Szemantikai ellenőrzés (unit tesztek)
3. szint: Sandbox futtatás VAGY mock mód

v3.2 Mock bővítés:
  - SQLAlchemy: create_engine, sessionmaker, declarative_base, Column típusok
  - httpx: Client, AsyncClient, get/post, HTTPStatusError
  - aiohttp: ClientSession, async context manager, json()
  - INFRASTRUCTURE_IMPORTS frissítve
v3.1 Windows fix:
  - capture_output=True → stdout=PIPE, stderr=PIPE (Windows encoding mismatch fix)
  - Windows-safe dekódolás: utf-8 → cp1250 fallback
  - Ha combined_err üres → py_compile szintax ellenőrzés fallback
  - Mostantól a hibaüzenet mindig látható a logban
  - _MockConn / _MockCursor → MagicMock-alapú make_mock_conn()
    Véget vet az AttributeError spirálnak: MagicMock bármely
    ismeretlen attribútumot/metódust automatikusan kezel.
  - Logging fix: logging.disable(logging.CRITICAL) a mock prelude-ban
    A generált kód logging.basicConfig-ja többé nem szól bele az AXON logjába.

v2.5 Bugfix (megőrizve):
  - fetchmany, fetchone, __iter__, rowcount, itersize
  - psycopg2 exception alias-ok top-level-en
  - S3b NONE fix
  - stdout+stderr combined hiba logolás
"""

import subprocess
import sys
import os
import re
import tempfile
import logging
from dataclasses import dataclass, field

log = logging.getLogger("AXON.Sandbox")

# ═══════════════════════════════════════════════════════════════
#  STATIKUS BIZTONSÁGI SZŰRŐ
# ═══════════════════════════════════════════════════════════════
FORBIDDEN_PATTERNS = [
    r'\bos\.system\b',
    r'\bshutil\.rmtree\b',
    r'\bsubprocess\.call\s*\(\s*["\']rm\b',
    r'\bsubprocess\.call\s*\(\s*["\']del\b',
    r'open\s*\(\s*__file__',
    r'axon_telegram',
    r'axon_sandbox',
    r'\bctypes\b',
    r'\beval\s*\(',
    r'\bexec\s*\(',
    r'\b__import__\b',
]

RISK_KEYWORDS = [
    "shutil.rmtree", "shutil.rmdir",
    "DROP TABLE", "TRUNCATE", "DELETE FROM",
    "purchase", "payment", "billing",
    "disk format", "wipe", "destroy",
]

# ═══════════════════════════════════════════════════════════════
#  INFRASTRUCTURE IMPORTOK – ezek mock módot triggerelnek
# ═══════════════════════════════════════════════════════════════
INFRASTRUCTURE_IMPORTS = [
    "psycopg2", "psycopg",
    "gspread",
    "google.oauth2", "googleapiclient",
    "boto3", "botocore",
    "pymongo",
    "redis",
    "pymysql", "mysql.connector",
    "smtplib", "imaplib",
    "ftplib",
    "ldap", "ldap3",
    "kafka",
    "celery",
    "airflow",
    "requests",
    "sqlalchemy",
    "httpx",
    "aiohttp",
]

def detect_infrastructure_imports(code: str) -> list:
    found = []
    for lib in INFRASTRUCTURE_IMPORTS:
        base = lib.split(".")[0]
        pattern = r'(?:^|\n)\s*(?:import|from)\s+' + re.escape(base)
        if re.search(pattern, code):
            found.append(base)
    return list(set(found))

# ═══════════════════════════════════════════════════════════════
#  MOCK STUB DEFINÍCIÓK
# ═══════════════════════════════════════════════════════════════

# ── psycopg2 ────────────────────────────────────────────────────
# MagicMock-alapú: bármely ismeretlen attr/metódus automatikusan
# MagicMock-ot ad vissza → nincs több kézzel karbantartott lista.
_MOCK_PSYCOPG2 = """
import logging as _logging_sandbox
_logging_sandbox.disable(_logging_sandbox.CRITICAL)

from unittest.mock import MagicMock as _MagicMock

def _make_mock_cursor(use_dict=False):
    cur = _MagicMock()
    if use_dict:
        _rows = [{"id": 1, "name": "mock_row", "value": 42},
                 {"id": 2, "name": "mock_row_2", "value": 99}]
    else:
        _rows = [(1, "mock_row", 42), (2, "mock_row_2", 99)]
    cur.description = [("id",), ("name",), ("value",)]
    cur.rowcount = 2
    cur.itersize = 1000
    cur.fetchall.return_value = _rows
    cur.fetchone.return_value = _rows[0]
    cur.fetchmany.side_effect = lambda size=100: _rows
    cur.__iter__ = lambda s: iter(_rows)
    cur.__enter__ = lambda s: cur
    cur.__exit__ = _MagicMock(return_value=False)
    return cur

def _make_mock_conn():
    conn = _MagicMock()
    conn.closed = 0
    conn.autocommit = False
    _cur = _make_mock_cursor()
    def _cursor_factory(cursor_factory=None, name=None, **kw):
        return _make_mock_cursor(use_dict=(cursor_factory is not None))
    conn.cursor.side_effect = _cursor_factory
    conn.__enter__ = lambda s: conn
    conn.__exit__ = _MagicMock(return_value=False)
    return conn

# psycopg2.sql mock
class _MockSqlObj:
    def __init__(self, s): self._s = s
    def format(self, **kw):
        result = self._s
        for k, v in kw.items():
            result = result.replace('{' + k + '}', str(v._s if hasattr(v, '_s') else v))
        return self
    def as_string(self, conn=None): return self._s
    def __str__(self): return self._s

class _MockSql:
    @staticmethod
    def SQL(s): return _MockSqlObj(s)
    @staticmethod
    def Identifier(s): return _MockSqlObj(f'"{s}"')
    @staticmethod
    def Literal(s): return _MockSqlObj(repr(s))

class _MockPsycopg2Extras:
    class RealDictCursor: pass
    class DictCursor: pass

class _MockPsycopg2Extensions:
    ISOLATION_LEVEL_AUTOCOMMIT = 0
    ISOLATION_LEVEL_READ_COMMITTED = 1
    ISOLATION_LEVEL_SERIALIZABLE = 2
    STATUS_READY = 1
    STATUS_BEGIN = 2
    class cursor: pass
    class connection: pass

class psycopg2:
    extras = _MockPsycopg2Extras()
    extensions = _MockPsycopg2Extensions()
    sql = _MockSql()
    class Error(Exception): pass
    class OperationalError(Exception): pass
    class InterfaceError(Exception): pass
    class ProgrammingError(Exception): pass
    class DatabaseError(Exception): pass
    @staticmethod
    def connect(*a, **kw): return _make_mock_conn()

# Top-level alias-ok – ha a kód prefix nélkül használja
OperationalError = psycopg2.OperationalError
DatabaseError    = psycopg2.DatabaseError
ProgrammingError = psycopg2.ProgrammingError
InterfaceError   = psycopg2.InterfaceError
pgsql = _MockSql()

class psycopg:
    class Error(Exception): pass
    @staticmethod
    def connect(*a, **kw): return _make_mock_conn()
"""

# ── gspread + Google OAuth2 ──────────────────────────────────────
_MOCK_GSPREAD_AND_GOOGLE = """
import logging as _logging_sandbox
_logging_sandbox.disable(_logging_sandbox.CRITICAL)

import sys as _sys_g, types as _types_g, json as _json_g, os as _os_g

_dummy_sa = {
    "type": "service_account", "project_id": "mock-project",
    "private_key_id": "mock-key-id", "private_key": "mock-private-key",
    "client_email": "mock@mock.iam.gserviceaccount.com",
    "client_id": "123", "token_uri": "https://oauth2.googleapis.com/token"
}
for _sa_name in ["service_account.json", "credentials.json", "creds.json", "google_creds.json"]:
    if not _os_g.path.exists(_sa_name):
        with open(_sa_name, "w") as _f: _json_g.dump(_dummy_sa, _f)

class _MockCredentials: pass

class _MockSheet:
    def get_all_values(self): return [["h1","h2"],["v1","v2"]]
    def get_all_records(self): return [{"h1":"v1","h2":"v2"}]
    def update(self, r, v): pass
    def append_row(self, v): pass
    def clear(self): pass
    @property
    def row_count(self): return 100

class _MockSpreadsheet:
    def worksheet(self, n): return _MockSheet()
    def get_worksheet(self, i): return _MockSheet()
    @property
    def sheet1(self): return _MockSheet()

class _MockGspreadClient:
    def open(self, n): return _MockSpreadsheet()
    def open_by_key(self, k): return _MockSpreadsheet()
    def open_by_url(self, u): return _MockSpreadsheet()

class gspread:
    Client = type('Client', (), {})  # type alias for annotations
    class exceptions:
        class APIError(Exception): pass
        class SpreadsheetNotFound(Exception): pass
    @staticmethod
    def authorize(c): return _MockGspreadClient()
    @staticmethod
    def service_account(f=None, **kw): return _MockGspreadClient()
    @staticmethod
    def service_account_from_dict(d, **kw): return _MockGspreadClient()

class _MockSA:
    class Credentials:
        @staticmethod
        def from_service_account_file(f, **kw): return _MockCredentials()
        @staticmethod
        def from_service_account_info(d, **kw): return _MockCredentials()

_g = _types_g.ModuleType("google")
_o = _types_g.ModuleType("google.oauth2")
_s = _types_g.ModuleType("google.oauth2.service_account")
_s.Credentials = _MockSA.Credentials
_g.oauth2 = _o
_o.service_account = _s
_sys_g.modules.setdefault("google", _g)
_sys_g.modules.setdefault("google.oauth2", _o)
_sys_g.modules.setdefault("google.oauth2.service_account", _s)
Credentials = _MockSA.Credentials
"""

# ── requests ────────────────────────────────────────────────────
_MOCK_REQUESTS = """
import logging as _logging_sandbox
_logging_sandbox.disable(_logging_sandbox.CRITICAL)

class _MockResponse:
    status_code = 200
    ok = True
    text = '{"ok": true}'
    def json(self): return {"ok": True, "result": []}
    def raise_for_status(self): pass

class requests:
    class exceptions:
        class RequestException(Exception): pass
        class ConnectionError(Exception): pass
        class Timeout(Exception): pass
        class HTTPError(Exception): pass
    @staticmethod
    def get(url, **kw): return _MockResponse()
    @staticmethod
    def post(url, **kw): return _MockResponse()
    @staticmethod
    def put(url, **kw): return _MockResponse()
    @staticmethod
    def delete(url, **kw): return _MockResponse()
    @staticmethod
    def patch(url, **kw): return _MockResponse()
"""

# ── boto3 ────────────────────────────────────────────────────────
_MOCK_BOTO3 = """
import logging as _logging_sandbox
_logging_sandbox.disable(_logging_sandbox.CRITICAL)

class _MockS3:
    def upload_file(self, *a, **kw): pass
    def download_file(self, *a, **kw): pass
    def list_objects_v2(self, **kw): return {"Contents": [{"Key": "test.txt"}]}
    def put_object(self, **kw): return {}
    def get_object(self, **kw): return {"Body": type("B", (), {"read": lambda s: b"mock"})()}

class boto3:
    @staticmethod
    def client(s, **kw): return _MockS3()
    @staticmethod
    def resource(s, **kw): return _MockS3()
"""

# ── redis ────────────────────────────────────────────────────────
_MOCK_REDIS = """
import logging as _logging_sandbox
_logging_sandbox.disable(_logging_sandbox.CRITICAL)

class redis:
    class Redis:
        def __init__(self, *a, **kw): pass
        def get(self, k): return b"mock_value"
        def set(self, k, v, **kw): return True
        def delete(self, k): return 1
        def exists(self, k): return 1
        def hget(self, n, k): return b"mock"
        def hset(self, n, k, v): return 1
    class ConnectionError(Exception): pass
    class StrictRedis(Redis): pass
    @staticmethod
    def from_url(url, **kw): return redis.Redis()
"""

# ── smtplib ──────────────────────────────────────────────────────
_MOCK_SMTPLIB = """
import logging as _logging_sandbox
_logging_sandbox.disable(_logging_sandbox.CRITICAL)

class smtplib:
    class SMTP:
        def __init__(self, *a, **kw): pass
        def starttls(self, **kw): pass
        def login(self, u, p): pass
        def sendmail(self, f, t, m): pass
        def send_message(self, m): pass
        def quit(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
    class SMTP_SSL(SMTP): pass
    class SMTPException(Exception): pass
"""

# ── pymongo ──────────────────────────────────────────────────────
_MOCK_PYMONGO = """
import logging as _logging_sandbox
_logging_sandbox.disable(_logging_sandbox.CRITICAL)

class _MockColl:
    def find(self, *a, **kw): return [{"_id": "1", "name": "mock"}]
    def find_one(self, *a, **kw): return {"_id": "1", "name": "mock"}
    def insert_one(self, d): return type("R", (), {"inserted_id": "1"})()
    def update_one(self, *a, **kw): return type("R", (), {"modified_count": 1})()
    def delete_one(self, *a, **kw): return type("R", (), {"deleted_count": 1})()
    def count_documents(self, *a, **kw): return 1

class _MockDB:
    def __getitem__(self, n): return _MockColl()
    def __getattr__(self, n): return _MockColl()

class pymongo:
    class MongoClient:
        def __init__(self, *a, **kw): pass
        def __getitem__(self, n): return _MockDB()
        def __getattr__(self, n): return _MockDB()
    class errors:
        class ConnectionFailure(Exception): pass
"""

# ── sqlalchemy ───────────────────────────────────────────────────
_MOCK_SQLALCHEMY = """
import logging as _logging_sandbox
_logging_sandbox.disable(_logging_sandbox.CRITICAL)

from unittest.mock import MagicMock as _MagicMock

class _MockColumn:
    def __init__(self, *a, **kw): pass

class _MockBase:
    metadata = _MagicMock()
    @staticmethod
    def declarative_base(): return _MockBase

class _MockSession:
    def __init__(self, *a, **kw): pass
    def query(self, *a): return self
    def filter(self, *a): return self
    def filter_by(self, **kw): return self
    def first(self): return None
    def all(self): return []
    def count(self): return 0
    def add(self, obj): pass
    def delete(self, obj): pass
    def commit(self): pass
    def rollback(self): pass
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self, *a): self.close()

class _MockEngine:
    def connect(self): return _MagicMock()
    def dispose(self): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass

class sqlalchemy:
    Column = _MockColumn
    Integer = type('Integer', (), {})
    String = lambda n=None: type('String', (), {})()
    Float = type('Float', (), {})
    Boolean = type('Boolean', (), {})
    DateTime = type('DateTime', (), {})
    Text = type('Text', (), {})
    class exc:
        class SQLAlchemyError(Exception): pass
        class OperationalError(Exception): pass
        class IntegrityError(Exception): pass
    class orm:
        @staticmethod
        def declarative_base(): return _MockBase
        @staticmethod
        def sessionmaker(**kw):
            return lambda: _MockSession()
        Session = _MockSession
    @staticmethod
    def create_engine(url, **kw): return _MockEngine()

# Top-level alias-ok
create_engine = sqlalchemy.create_engine
Column = sqlalchemy.Column
Integer = sqlalchemy.Integer
String = sqlalchemy.String
Float = sqlalchemy.Float
Boolean = sqlalchemy.Boolean
DateTime = sqlalchemy.DateTime
Text = sqlalchemy.Text
Session = sqlalchemy.orm.Session
sessionmaker = sqlalchemy.orm.sessionmaker
declarative_base = sqlalchemy.orm.declarative_base
"""

# ── httpx + aiohttp ──────────────────────────────────────────────
_MOCK_HTTPX = """
import logging as _logging_sandbox
_logging_sandbox.disable(_logging_sandbox.CRITICAL)

from unittest.mock import MagicMock as _MagicMock

class _MockHttpxResponse:
    status_code = 200
    text = '{"ok": true}'
    content = b'{"ok": true}'
    headers = {"content-type": "application/json"}
    def json(self): return {"ok": True, "result": []}
    def raise_for_status(self): pass
    @property
    def is_success(self): return True

class httpx:
    class Client:
        def __init__(self, *a, **kw): pass
        def get(self, url, **kw): return _MockHttpxResponse()
        def post(self, url, **kw): return _MockHttpxResponse()
        def put(self, url, **kw): return _MockHttpxResponse()
        def delete(self, url, **kw): return _MockHttpxResponse()
        def __enter__(self): return self
        def __exit__(self, *a): pass
    class AsyncClient:
        def __init__(self, *a, **kw): pass
        async def get(self, url, **kw): return _MockHttpxResponse()
        async def post(self, url, **kw): return _MockHttpxResponse()
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
    class HTTPStatusError(Exception): pass
    class ConnectError(Exception): pass
    class TimeoutException(Exception): pass
    @staticmethod
    def get(url, **kw): return _MockHttpxResponse()
    @staticmethod
    def post(url, **kw): return _MockHttpxResponse()

class _MockAiohttpResponse:
    status = 200
    async def json(self): return {"ok": True, "result": []}
    async def text(self): return '{"ok": true}'
    async def read(self): return b'{"ok": true}'
    def raise_for_status(self): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): pass

class aiohttp:
    class ClientSession:
        def __init__(self, *a, **kw): pass
        def get(self, url, **kw): return _MockAiohttpResponse()
        def post(self, url, **kw): return _MockAiohttpResponse()
        def put(self, url, **kw): return _MockAiohttpResponse()
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
    class ClientError(Exception): pass
    class ServerConnectionError(Exception): pass
"""


_MOCK_STUBS = {
    "psycopg2": _MOCK_PSYCOPG2,
    "psycopg":  _MOCK_PSYCOPG2,
    "gspread":  _MOCK_GSPREAD_AND_GOOGLE,
    "google":   _MOCK_GSPREAD_AND_GOOGLE,
    "googleapiclient": _MOCK_GSPREAD_AND_GOOGLE,
    "requests": _MOCK_REQUESTS,
    "boto3":    _MOCK_BOTO3,
    "botocore": _MOCK_BOTO3,
    "redis":    _MOCK_REDIS,
    "smtplib":  _MOCK_SMTPLIB,
    "imaplib":  _MOCK_SMTPLIB,
    "pymongo":  _MOCK_PYMONGO,
    "sqlalchemy": _MOCK_SQLALCHEMY,
    "httpx":    _MOCK_HTTPX,
    "aiohttp":  _MOCK_HTTPX,
}

# ═══════════════════════════════════════════════════════════════
#  ENV VÁLTOZÓK MOCK ÉRTÉKEKKEL
# ═══════════════════════════════════════════════════════════════
_MOCK_ENV_PRELUDE = """import os as _os_env
import logging as _logging_sandbox
_logging_sandbox.disable(_logging_sandbox.CRITICAL)

_mock_env = {
    'DATABASE_URL': 'postgresql://mock_user:mock_pass@localhost:5432/mock_db',
    'POSTGRES_URL': 'postgresql://mock_user:mock_pass@localhost:5432/mock_db',
    'POSTGRES_HOST': 'localhost', 'POSTGRES_PORT': '5432',
    'POSTGRES_DB': 'mock_db', 'POSTGRES_USER': 'mock_user',
    'POSTGRES_PASSWORD': 'mock_pass',
    'GOOGLE_SHEETS_ID': 'mock_sheet_id_1234',
    'SPREADSHEET_ID': 'mock_sheet_id_1234',
    'SHEETS_WEBHOOK': 'https://hooks.mock.example.com/sheets',
    'SHEETS_WEBHOOK_URL': 'https://hooks.mock.example.com/sheets',
    'WEBHOOK_URL': 'https://hooks.mock.example.com/webhook',
    'TELEGRAM_BOT_TOKEN': 'mock_telegram_token',
    'TELEGRAM_CHAT_ID': '123456789',
    'TELEGRAM_TOKEN': 'mock_telegram_token',
    'SERVICE_ACCOUNT_FILE': 'service_account.json',
    'CREDENTIALS_FILE': 'service_account.json',
    'GOOGLE_CREDENTIALS': 'service_account.json',
    'TABLE_NAME': 'orders', 'MONITOR_TABLE': 'orders',
    'SYNC_INTERVAL': '1', 'INTERVAL': '1', 'POLL_INTERVAL': '1',
    'AWS_ACCESS_KEY_ID': 'mock_key', 'AWS_SECRET_ACCESS_KEY': 'mock_secret',
    'AWS_DEFAULT_REGION': 'eu-west-1',
    'REDIS_URL': 'redis://localhost:6379/0',
    'MONGO_URI': 'mongodb://localhost:27017/mock_db',
    'SMTP_HOST': 'smtp.mock.com', 'SMTP_PORT': '587',
    'SMTP_USER': 'mock@mock.com', 'SMTP_PASSWORD': 'mock_pass',
}
for _k, _v in _mock_env.items():
    if not _os_env.environ.get(_k):
        _os_env.environ[_k] = _v
"""

def build_mock_prelude(infra_imports: list) -> str:
    parts = ["# === AXON MOCK MÓD – infrastructure stubok ===", _MOCK_ENV_PRELUDE]
    seen = set()
    for lib in infra_imports:
        stub = _MOCK_STUBS.get(lib)
        if stub and stub not in seen:
            parts.append(f"# Mock: {lib}")
            parts.append(stub)
            seen.add(stub)
    parts.append("# === MOCK MÓD VÉGE ===")
    return "\n".join(parts)

def inject_mocks(code: str, infra_imports: list) -> str:
    mock_prelude = build_mock_prelude(infra_imports)

    lines = code.splitlines()
    filtered = []
    extra_aliases = []
    for line in lines:
        skip = False
        for lib in infra_imports:
            if re.match(r'\s*(?:import|from)\s+' + re.escape(lib), line):
                skip = True
                alias_match = re.match(r'\s*import\s+psycopg2\.sql\s+as\s+(\w+)', line)
                if alias_match:
                    extra_aliases.append(f"{alias_match.group(1)} = _MockSql()")
                break
        if not skip and ("gspread" in infra_imports or "google" in infra_imports):
            if re.match(r'\s*(?:import|from)\s+google', line):
                skip = True
        if not skip:
            filtered.append(line)

    clean_code = "\n".join(filtered)

    # Üres try: blokk javítás – import eltávolítás mellékhatása
    fixed = []
    prev_try = False
    for ln in clean_code.split("\n"):
        stripped = ln.strip()
        if prev_try and (stripped.startswith("except") or stripped.startswith("finally")):
            fixed.append("    pass")
        fixed.append(ln)
        prev_try = (stripped == "try:")
    clean_code = "\n".join(fixed)

    alias_block = "\n".join(extra_aliases) + "\n" if extra_aliases else ""
    return mock_prelude + "\n" + alias_block + clean_code

# ═══════════════════════════════════════════════════════════════
#  EREDMÉNY STRUKTÚRA
# ═══════════════════════════════════════════════════════════════
@dataclass
class SandboxResult:
    success: bool
    message: str
    stdout: str = ""
    stderr: str = ""
    attempt: int = 1
    final_code: str = ""
    tests_passed: int = 0
    tests_total: int = 0
    risk_keywords: list = field(default_factory=list)
    mock_mode: bool = False
    mock_libs: list = field(default_factory=list)

# ═══════════════════════════════════════════════════════════════
#  PROMPT SABLONOK
# ═══════════════════════════════════════════════════════════════
UNIT_TEST_PROMPT = """A feladat: {task}

{few_shot_patterns}
Generálj egyszerre:
1. A megoldás Python kódját
2. 2-3 assert alapú unit tesztet ami a KÓD BELSŐ LOGIKÁJÁT ellenőrzi

KÖTELEZŐ FORMÁTUM – PONTOSAN ÍGY:

```python
# === KÓD ===
[itt a megoldás kódja]

# === TESZTEK ===
if __name__ == "__test__":
    [assert teszt1]
    [assert teszt2]
    [assert teszt3 ha szükséges]
    print("TESZTEK OK")
```

TESZTÍRÁSI ELVEK:

TILOS – infrastructure hívások eredményét tesztelni:
  assert conn is not None           (DB kapcsolat – mock mindig True)
  assert send_alert(x) == True      (API hívás – mock mindig True)
  assert sync_data(rows) == True    (webhook – mock mindig True)

HELYES – a függvények LOGIKÁJÁT tesztelni:
  rows = fetch_rows(conn, "test", 0)
  assert len(rows) > 0              (vannak sorok)
  assert rows[-1][0] > 0            (id pozitív)
  result = transform(input_data)
  assert isinstance(result, list)   (helyes típus)
  assert len(result) == len(input_data)  (nincs adatveszteség)
  msg = format_alert(3, "orders")
  assert "3" in msg                 (tartalom ellenőrzés)

__main__ BLOKK SZABÁLY – KRITIKUS:
A sandbox `python script.py`-ként futtatja a kódot – a `if __name__ == "__main__":` blokk
LEFUT a tesztek előtt. Ha ez fájlt nyit vagy sys.argv-t vár, a sandbox elszáll.

TILOS __main__ blokkban:
  - Közvetlen fájl megnyitás: open("input.csv"), pd.read_csv("data.csv")
  - sys.argv feldolgozás argumentum-ellenőrzés nélkül
  - Adatbázis kapcsolat, hálózati hívás

HELYES – ha CLI szkript:
  if __name__ == "__main__":
      import sys
      if len(sys.argv) > 1:
          main(sys.argv[1])
  # vagy hagyd el teljesen a __main__ blokkot

FÁJL-INPUT SZABÁLY – KRITIKUS:
Ha a kód fájlt olvas (open(), csv.reader, pd.read_csv stb.):
  - A tesztek NE nyissanak valódi fájlt (a sandbox könyvtárban nincs input.csv!)
  - HELYES: mock adatot adj át StringIO-val vagy listaként
  - HELYES: a feldolgozó függvényt közvetlen adattal hívd, ne fájlnévvel
  - Példa:
      import io
      mock_csv = io.StringIO("id,name\\n1,test\\n2,foo")
      result = process_rows(mock_csv)
      assert len(result) == 2
  - TILOS: assert os.path.exists("input.csv")  (nem létezik a sandboxban!)
  - TILOS: open("input.csv")  a tesztekben – mindig mock adat!

ÁLTALÁNOS SZABÁLYOK:
- Max 3 assert összesen
- Minden assert MÁS logikai aspektust teszteljen
- NE generálj helper függvényeket a tesztekbe
- Matematikai függvényeknél: assert add(2,3) == 5
- Dinamikus értéknél: assert get_total() > 0  (NE: == 395)"""

FIX_PROMPT = """Ez a Python kód hibás. Javítsd ki!

FELADAT AMIT MEGOLDOTT VOLNA: {task}

HIBA TÍPUSA: {error_type}

TELJES HIBAÜZENET (stderr):
{error}

STDOUT (ha van):
{stdout}

{few_shot_fixes}
EREDETI KÓD (tesztekkel együtt):
```python
{code}
```

FONTOS: Ha AssertionError van, a teszt elvárásait NE változtasd meg – a KÓD logikáját javítsd!
FONTOS: Ha FileNotFoundError van és a traceback __main__ blokkból jön:
  - A `if __name__ == "__main__":` blokk a sandbox indításakor LEFUT
  - A sandbox könyvtárban NINCS input fájl (input.csv, data.txt stb.)
  - Javítás: védd le a __main__ blokkot: `if len(sys.argv) > 1: main(sys.argv[1])`
  - VAGY töröld a __main__ blokkot teljesen – a tesztek úgyis lefutnak __test__ alatt
  - A tesztekben mindig mock adatot használj: io.StringIO, lista, dict
FONTOS: `global` statement CSAK függvény belsejében lehet, soha module szinten!
FONTOS: Ha `global X` szintaktikai hibát kapsz – távolítsd el a module-szintű global-t.
TILOS: unittest.TestCase osztály, class Test...(unittest.TestCase) – SOHA!
TILOS: import unittest – a sandbox nem tud unittest runner-t indítani!
KÖTELEZŐ TESZT FORMÁTUM (csak ez elfogadott):
  # === TESZTEK ===
  if __name__ == "__test__":
      assert valami == elvart_ertek
      print("TESZTEK OK")
Adj vissza CSAK egy javított kódot ```python blokkban, ugyanolyan struktúrával
(# === KÓD === és # === TESZTEK === szekciókkal).
Ne magyarázz, csak a javított kód kell."""

# ═══════════════════════════════════════════════════════════════
#  FŐ SANDBOX OSZTÁLY v3.0
# ═══════════════════════════════════════════════════════════════
class AxonSandbox:
    def __init__(self, max_retries: int = 3, timeout: int = 15):
        self.max_retries = max_retries
        self.timeout = timeout

    def static_check(self, code: str):
        for pattern in FORBIDDEN_PATTERNS:
            if re.search(pattern, code, re.IGNORECASE):
                return False, f"Tiltott minta: `{pattern}`", []
        found_risks = [kw for kw in RISK_KEYWORDS if kw in code.lower()]
        return True, "OK", found_risks

    def inject_test_runner(self, code: str) -> str:
        return code.replace(
            'if __name__ == "__test__":',
            'if __name__ == "__main__":'
        )

    def extract_sections(self, code: str):
        if "# === TESZTEK ===" in code:
            parts = code.split("# === TESZTEK ===")
            main_code = parts[0].replace("# === KÓD ===", "").strip()
            test_code = parts[1].strip() if len(parts) > 1 else ""
            return main_code, test_code
        return code, ""

    def count_asserts(self, test_code: str) -> int:
        return len([l for l in test_code.splitlines() if l.strip().startswith("assert")])

    def _neutralize_blocking(self, code: str) -> str:
        """Mock módban blokkoló konstrukciók semlegesítése."""
        code = re.sub(r'time\.sleep\s*\([^)]*\)', 'time.sleep(0)', code)
        code = re.sub(r'asyncio\.sleep\s*\([^)]*\)', 'asyncio.sleep(0)', code)

        marker = "# === AXON MOCK MÓD"
        if marker in code:
            prelude, user = code.split(marker, 1)
            user = re.sub('while[ \t]*True[ \t]*:', 'for _ in range(1):', user)
            code = prelude + marker + user
        else:
            code = re.sub('while[ \t]*True[ \t]*:', 'for _ in range(1):', code)

        return code

    def run_in_sandbox(self, code: str, attempt: int) -> SandboxResult:
        # 1. Statikus szűrő
        safe, reason, risks = self.static_check(code)
        if not safe:
            return SandboxResult(
                success=False, message=f"Biztonsági hiba: {reason}",
                attempt=attempt, final_code=code, risk_keywords=risks
            )

        # 2. Infrastructure detektálás → mock mód
        infra_libs = detect_infrastructure_imports(code)
        mock_mode = len(infra_libs) > 0

        if mock_mode:
            log.info(f"[SANDBOX] Mock mód – infrastructure: {infra_libs}")
            runnable_code = inject_mocks(code, infra_libs)
        else:
            runnable_code = code

        # 3. Teszt injektálás
        _, test_section = self.extract_sections(code)
        total_tests = self.count_asserts(test_section)
        runnable_code = self.inject_test_runner(runnable_code)

        # 4. Mock módban: blokkoló konstrukciók semlegesítése
        if mock_mode:
            runnable_code = self._neutralize_blocking(runnable_code)

        # 5. Futtatás
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.py', prefix='axon_test_',
                delete=False, encoding='utf-8'
            ) as tmp:
                tmp.write(runnable_code)
                tmp_path = tmp.name

            mode_str = "MOCK" if mock_mode else "LIVE"
            log.info(f"[SANDBOX] Futtatás #{attempt} ({total_tests} teszt) [{mode_str}]")

            sandbox_env = os.environ.copy()
            sandbox_env['SANDBOX_MODE'] = '1'
            sandbox_env['PYTHONIOENCODING'] = 'utf-8'
            sandbox_env['PYTHONUTF8'] = '1'

            effective_timeout = 60 if mock_mode else self.timeout
            proc = subprocess.run(
                [sys.executable, tmp_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=effective_timeout,
                env=sandbox_env,
            )
            # Windows-safe dekódolás: utf-8 → cp1250 fallback
            def _decode(b: bytes) -> str:
                if not b:
                    return ""
                try:
                    return b.decode('utf-8', errors='replace')
                except Exception:
                    return b.decode('cp1250', errors='replace')

            stdout_str = _decode(proc.stdout)
            stderr_str = _decode(proc.stderr)

            if proc.returncode == 0:
                tests_passed = total_tests if "TESZTEK OK" in stdout_str else 0
                log.info(f"[SANDBOX] ✓ #{attempt} – {tests_passed}/{total_tests} OK [{mode_str}]")
                return SandboxResult(
                    success=True,
                    message="Sikeres" + (" (mock mód)" if mock_mode else ""),
                    stdout=stdout_str[:800], stderr=stderr_str[:200],
                    attempt=attempt, final_code=code,
                    tests_passed=tests_passed, tests_total=total_tests,
                    risk_keywords=risks, mock_mode=mock_mode, mock_libs=infra_libs
                )
            else:
                combined_err = stderr_str + stdout_str
                # Ha combined_err üres → py_compile szintax ellenőrzés fallback
                if not combined_err.strip():
                    try:
                        import py_compile, io
                        py_compile.compile(tmp_path, doraise=True)
                    except py_compile.PyCompileError as pce:
                        combined_err = f"[py_compile] {pce}"
                    except Exception as pce2:
                        combined_err = f"[py_compile fallback] {pce2}"
                is_assertion = "AssertionError" in combined_err
                error_type = "szemantikai (assert)" if is_assertion else "szintaktikai"
                log.warning(f"[SANDBOX] ✗ #{attempt} {error_type}: {combined_err[:1500]}")
                return SandboxResult(
                    success=False, message=f"Hiba ({error_type})",
                    stdout=stdout_str[:400], stderr=combined_err[:800],
                    attempt=attempt, final_code=code,
                    tests_passed=0, tests_total=total_tests,
                    risk_keywords=risks, mock_mode=mock_mode, mock_libs=infra_libs
                )

        except subprocess.TimeoutExpired:
            return SandboxResult(
                success=False, message=f"Timeout: {effective_timeout}mp",
                attempt=attempt, final_code=code,
                mock_mode=mock_mode, mock_libs=infra_libs
            )
        except Exception as e:
            return SandboxResult(
                success=False, message=f"Sandbox hiba: {e}",
                attempt=attempt, final_code=code,
                mock_mode=mock_mode, mock_libs=infra_libs
            )
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    async def validate_with_retry(self, code, task, ai_fix_callback, status_callback=None, few_shot_fixes: str = ""):
        for attempt in range(1, self.max_retries + 1):
            if status_callback:
                bar = "▓" * attempt + "░" * (self.max_retries - attempt)
                _, test_code = self.extract_sections(code)
                n_tests = self.count_asserts(test_code)
                infra = detect_infrastructure_imports(code)
                mode_hint = f" 🔌 mock: {', '.join(infra)}" if infra else ""
                await status_callback(
                    f"🔬 *Sandbox #{attempt}/{self.max_retries}* {bar}{mode_hint}\n"
                    f"{'🧪 ' + str(n_tests) + ' unit teszt...' if n_tests else '⚙️ Futtatás...'}"
                )

            result = self.run_in_sandbox(code, attempt)
            if result.success:
                return result

            if attempt < self.max_retries:
                is_assertion = "AssertionError" in result.stderr
                error_type = "szemantikai" if is_assertion else "szintaktikai"

                if status_callback:
                    err_preview = result.stderr.strip()[-200:] if result.stderr else "?"
                    await status_callback(
                        f"⚠️ *Hiba #{attempt}* – {error_type}\n"
                        f"`{err_preview}`\n🔧 Javítás..."
                    )

                fix_prompt = FIX_PROMPT.format(
                    task=task, error_type=error_type,
                    error=result.stderr[:800],
                    stdout=result.stdout[:300] if result.stdout else "(üres)",
                    few_shot_fixes=few_shot_fixes,
                    code=code
                )
                fixed_response = await ai_fix_callback(fix_prompt)
                new_code = extract_code_block(fixed_response)
                if new_code:
                    code = new_code
                    log.info(f"[SANDBOX] Javított kód #{attempt} → újra")
                else:
                    log.error("[SANDBOX] AI nem adott kód blokkot!")
                    break

        return result

# ═══════════════════════════════════════════════════════════════
#  SEGÉDFÜGGVÉNYEK
# ═══════════════════════════════════════════════════════════════
def extract_code_block(text: str):
    match = re.search(r'```python\n(.*?)\n```', text, re.DOTALL)
    return match.group(1) if match else None

def format_sandbox_report(result: SandboxResult) -> str:
    status = "✅ SIKERES" if result.success else "❌ SIKERTELEN"
    if result.success and result.mock_mode:
        status = "✅ SIKERES (mock mód)"
    lines = [f"*Sandbox:* {status} (#{result.attempt}. próba)"]
    if result.mock_mode and result.mock_libs:
        lines.append(f"🔌 *Mock:* `{', '.join(result.mock_libs)}` (infrastructure stub)")
    if result.tests_total > 0:
        lines.append(f"*Unit tesztek:* {result.tests_passed}/{result.tests_total} OK")
    if result.risk_keywords:
        lines.append(f"⚠️ *Kockázatos:* `{', '.join(result.risk_keywords)}`")
    if not result.success and result.stderr:
        first_err = result.stderr.strip().splitlines()[-1][:200]
        lines.append(f"*Utolsó hiba:*\n`{first_err}`")
    return "\n".join(lines)
