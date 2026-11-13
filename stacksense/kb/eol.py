"""End-of-life and retirement table (plan section 6.4) with deterministic lookup helpers.

Every row is ``EolRow(key, product, cycle, label, kind, date, replacement, source, conf, mainstream_end, note)``:

key            unique row id, ``<product>_<cycle>`` (``eol_<product>`` source keys live in kb/sources*.py).
product        canonical product id (see ``PRODUCTS``); ``lookup`` also accepts the aliases in ``ALIASES``.
cycle          version/release line the row covers ("18", "3.10", "2019"); "" for whole-service rows.
               A row covers every version whose dotted numbers start with the cycle ("3.10.4" -> "3.10",
               "2.5.1" -> Spring Boot "2"). The longest matching cycle wins.
kind           what ``date`` means: ``eol`` (end of security/community support), ``extended_end``
               (extended support end), ``retired`` (service switched off), ``end_of_sale`` (closed to new
               customers), ``archived`` (upstream repository archived), ``deprecated`` (superseded
               by the vendor but still runs).
date           ISO date of that milestone. A month-precision source is stored as the first day of the month
               (see ``note``).
mainstream_end ISO date mainstream support ended, or None.
conf           ``verified`` (checked against the cited vendor page or the endoflife.date API on 2026-11-13)
               or ``unverified`` (kept, but could not be confirmed; wording must be hedged).

Dates are judged against ``KB_DATE``, a fixed anchor, never the system clock, so the same input
gives the same verdict next month.  The anchor is the plan's KB date and is printed in ``assumptions``
whenever an EOL judgement is made.

API for ``existing.py``::

    lookup(product, version=None) -> EolRow | None
    status_on(row, anchor=KB_DATE) -> dict   # state: ended | ending_soon | supported
    verdict(product, version=None, anchor=KB_DATE) -> dict | None   # lookup + status_on in one call
"""
from __future__ import annotations

import re
from datetime import date
from typing import NamedTuple

KB_DATE = date(2026, 11, 12)
SOON_DAYS = 365          # an end date within this many days after the anchor is "ending_soon"

V, U = "verified", "unverified"


class EolRow(NamedTuple):
    key: str
    product: str
    cycle: str
    label: str
    kind: str
    date: str
    replacement: str
    source: str
    conf: str = V
    mainstream_end: str | None = None
    note: str = ""


def _r(product, cycle, label, kind, when, repl, source, conf=V, mainstream=None, note=""):
    key = f"{product}_{cycle}".replace(".", "_").replace(" ", "_").rstrip("_")
    return EolRow(key, product, cycle, label, kind, when, repl, source, conf, mainstream, note)


_N24 = "Node.js 24 LTS"
_PY = "Python 3.13 or newer"
_PHP = "PHP 8.4 or newer"
_NET = ".NET 10 (LTS)"
_PG = "PostgreSQL 17"
_SQL = "SQL Server 2022 or Azure SQL"
_WS = "Windows Server 2025"
_EL = "RHEL, AlmaLinux or Rocky Linux 9 or newer"
_AFD = "Azure Front Door Standard/Premium"

ROWS: tuple[EolRow, ...] = (
    # --- runtimes and frameworks
    _r("nodejs", "16", "Node.js 16", "eol", "2023-09-11", _N24, "eol_nodejs"),
    _r("nodejs", "18", "Node.js 18", "eol", "2025-04-30", _N24, "eol_nodejs"),
    _r("nodejs", "20", "Node.js 20", "eol", "2026-04-30", _N24, "eol_nodejs"),
    _r("nodejs", "22", "Node.js 22", "eol", "2027-04-30", "plan an upgrade to Node.js 24 LTS", "eol_nodejs"),
    _r("nodejs", "24", "Node.js 24", "eol", "2028-04-30", "stay on the current LTS line", "eol_nodejs"),
    _r("python", "2.7", "Python 2.7", "eol", "2020-01-01", _PY, "eol_python"),
    _r("python", "3.8", "Python 3.8", "eol", "2024-10-07", _PY, "eol_python"),
    _r("python", "3.9", "Python 3.9", "eol", "2025-10-31", _PY, "eol_python"),
    _r("python", "3.10", "Python 3.10", "eol", "2026-10-01", _PY, "eol_python",
       note="endoflife.date lists 2026-10-01; the CPython schedule says October 2026"),
    _r("python", "3.13", "Python 3.13", "eol", "2029-10-31", "stay on a supported 3.x line", "eol_python"),
    _r("php", "7.4", "PHP 7.4", "eol", "2022-11-28", _PHP, "eol_php"),
    _r("php", "8.0", "PHP 8.0", "eol", "2023-11-26", _PHP, "eol_php"),
    _r("php", "8.1", "PHP 8.1", "eol", "2025-12-31", _PHP, "eol_php"),
    _r("dotnet_framework", "4.5", "the .NET Framework 4.5 line", "eol", "2016-01-12", _NET, "eol_dotnetfx"),
    _r("dotnet_framework", "4.6.1", "the .NET Framework 4.6.1 line (and older)", "eol", "2022-04-26", _NET, "eol_dotnetfx"),
    _r("dotnet_framework", "4.5.2", ".NET Framework 4.5.2", "eol", "2022-04-26", _NET, "eol_dotnetfx"),
    _r("dotnet_framework", "4.6", ".NET Framework 4.6", "eol", "2022-04-26", _NET, "eol_dotnetfx"),
    _r("dotnet", "3.1", ".NET Core 3.1", "eol", "2022-12-13", _NET, "eol_dotnet"),
    _r("dotnet", "5", ".NET 5", "eol", "2022-05-10", _NET, "eol_dotnet"),
    _r("dotnet", "6", ".NET 6", "eol", "2024-11-12", _NET, "eol_dotnet"),
    _r("dotnet", "7", ".NET 7", "eol", "2024-05-14", _NET, "eol_dotnet"),
    _r("dotnet", "8", ".NET 8", "eol", "2026-11-10", _NET, "dotnet_8_9_eos"),
    _r("dotnet", "9", ".NET 9", "eol", "2026-11-10", _NET, "dotnet_8_9_eos"),
    _r("dotnet", "10", ".NET 10", "eol", "2028-11-14", "stay on the current LTS line", "eol_dotnet"),
    _r("java", "8", "Java 8 (Oracle)", "eol", "2022-03-31", "Java 21 or 25 LTS", "eol_java",
       note="Oracle premier support; extended and third-party support exists"),
    _r("spring_boot", "2", "Spring Boot 2.x", "eol", "2023-06-30", "Spring Boot 3.5 or newer", "eol_spring_boot",
       note="open-source support for the 2.7 line, the last 2.x release"),
    _r("spring_boot", "3.5", "Spring Boot 3.5", "eol", "2026-06-30", "Spring Boot 4", "eol_spring_boot"),
    _r("django", "3.2", "Django 3.2 LTS", "eol", "2024-04-01", "Django 5.2 LTS", "eol_django"),
    _r("django", "4.2", "Django 4.2 LTS", "eol", "2026-04-07", "Django 5.2 LTS", "eol_django"),
    _r("rails", "6.1", "Ruby on Rails 6.1", "eol", "2024-10-01", "Rails 8", "eol_rails"),
    _r("openssl", "1.1.1", "OpenSSL 1.1.1", "eol", "2023-09-11", "OpenSSL 3.x", "eol_openssl"),
    # --- databases
    _r("postgresql", "11", "PostgreSQL 11", "eol", "2023-11-09", _PG, "eol_postgresql"),
    _r("postgresql", "12", "PostgreSQL 12", "eol", "2024-11-21", _PG, "eol_postgresql"),
    _r("postgresql", "13", "PostgreSQL 13", "eol", "2025-11-13", _PG, "pg_versioning"),
    _r("postgresql", "14", "PostgreSQL 14", "eol", "2026-11-12", _PG, "pg_versioning"),
    _r("postgresql", "15", "PostgreSQL 15", "eol", "2027-11-11", "plan an upgrade to PostgreSQL 17", "pg_versioning"),
    _r("postgresql", "16", "PostgreSQL 16", "eol", "2028-11-09", "stay on a supported major", "pg_versioning"),
    _r("postgresql", "17", "PostgreSQL 17", "eol", "2029-11-08", "stay on a supported major", "pg_versioning"),
    _r("postgresql", "18", "PostgreSQL 18", "eol", "2030-11-14", "stay on a supported major", "pg_versioning"),
    _r("mysql", "5.7", "MySQL 5.7", "eol", "2023-10-31", "MySQL 8.4 LTS", "eol_mysql"),
    _r("mysql", "8.0", "MySQL 8.0", "eol", "2026-04-30", "MySQL 8.4 LTS", "eol_mysql",
       note="community end of life; managed services run their own extended schedules"),
    _r("sqlserver", "2012", "SQL Server 2012", "extended_end", "2022-07-12", _SQL, "eol_mssql"),
    _r("sqlserver", "2014", "SQL Server 2014", "extended_end", "2024-07-09", _SQL, "eol_mssql"),
    _r("sqlserver", "2016", "SQL Server 2016", "extended_end", "2026-07-14", _SQL, "eol_mssql"),
    _r("sqlserver", "2017", "SQL Server 2017", "extended_end", "2027-10-12", _SQL, "eol_mssql", mainstream="2022-10-11"),
    _r("sqlserver", "2019", "SQL Server 2019", "extended_end", "2030-01-08", _SQL, "ms_sql2019_lifecycle",
       mainstream="2025-02-28"),
    _r("mongodb", "4.4", "MongoDB 4.4", "eol", "2024-02-29", "MongoDB 8.0", "eol_mongodb"),
    _r("mongodb", "5.0", "MongoDB 5.0", "eol", "2024-10-31", "MongoDB 8.0", "eol_mongodb"),
    _r("mongodb", "6.0", "MongoDB 6.0", "eol", "2025-07-31", "MongoDB 8.0", "eol_mongodb"),
    _r("elasticsearch", "7", "Elasticsearch 7.x", "eol", "2026-01-15", "Elasticsearch 9 or OpenSearch 3", "eol_elasticsearch"),
    # --- operating systems and platforms
    _r("windows_server", "2012", "Windows Server 2012 / 2012 R2", "eol", "2023-10-10", _WS, "eol_windows_server"),
    _r("windows_server", "2016", "Windows Server 2016", "extended_end", "2027-01-12", _WS, "eol_windows_server",
       mainstream="2022-01-11"),
    _r("centos", "7", "CentOS 7", "eol", "2024-06-30", _EL, "eol_centos"),
    _r("centos", "8", "CentOS 8", "eol", "2021-12-31", _EL, "eol_centos"),
    _r("ubuntu", "18.04", "Ubuntu 18.04 LTS", "eol", "2023-05-31", "Ubuntu 24.04 LTS", "eol_ubuntu",
       note="standard support; paid Ubuntu Pro extends it"),
    _r("ubuntu", "20.04", "Ubuntu 20.04 LTS", "eol", "2025-05-31", "Ubuntu 24.04 LTS", "eol_ubuntu",
       note="standard support; paid Ubuntu Pro extends it"),
    _r("rhel", "7", "RHEL 7", "eol", "2024-06-30", "RHEL 9 or newer", "eol_rhel",
       note="end of maintenance support; paid Extended Life Support exists"),
    # --- front-end and mobile tooling
    _r("angularjs", "1", "AngularJS 1.x", "eol", "2021-12-31", "Angular (current)", "eol_angularjs"),
    _r("vue", "2", "Vue 2", "eol", "2023-12-31", "Vue 3", "eol_vue"),
    _r("create_react_app", "", "Create React App", "deprecated", "2025-02-14", "Vite or Next.js", "eol_create_react_app"),
    _r("xamarin", "", "Xamarin", "eol", "2024-05-01", ".NET MAUI", "eol_xamarin"),
    _r("internet_explorer", "11", "Internet Explorer 11", "retired", "2022-06-15", "Microsoft Edge", "eol_ie11"),
    _r("app_center", "", "Microsoft App Center", "retired", "2025-03-31",
       "EAS Build, fastlane or Firebase App Distribution", "eol_app_center"),
    _r("docker_compose_v1", "", "Docker Compose v1 (docker-compose, Python)", "eol", "2023-07-01",
       "Docker Compose v2 plugin", "eol_docker_compose_v1", note="Docker states July 2023 (month precision)"),
    # --- cloud services
    _r("gcp_iot_core", "", "Google Cloud IoT Core", "retired", "2023-08-16",
       "EMQX, AWS IoT Core or Azure IoT Hub", "gcp_iot_retired"),
    _r("firebase_dynamic_links", "", "Firebase Dynamic Links", "retired", "2025-08-25",
       "App Links and Universal Links", "firebase_dynamic_links"),
    _r("azure_ad_b2c", "", "Azure AD B2C", "end_of_sale", "2025-05-01", "Microsoft Entra External ID", "entra_external_id",
       note="closed to new customers; existing tenants keep running (support commitment runs to at least 2030)"),
    _r("azure_cache_redis", "", "Azure Cache for Redis (Basic, Standard, Premium)", "retired", "2028-09-30",
       "Azure Managed Redis", "azure_redis_retirement"),
    _r("azure_cache_redis", "enterprise", "Azure Cache for Redis Enterprise", "retired", "2027-03-31",
       "Azure Managed Redis", "azure_redis_retirement"),
    _r("azure_cdn_classic", "", "Azure CDN Standard from Microsoft (classic)", "retired", "2027-09-30", _AFD,
       "azure_cdn_classic_retirement"),
    _r("azure_cdn_edgio", "", "Azure CDN from Edgio", "retired", "2025-01-15", _AFD, "azure_cdn_comparison"),
    _r("azure_front_door_classic", "", "Azure Front Door (classic)", "retired", "2027-03-31", _AFD, "afd_tier_migration"),
    _r("azure_media_services", "", "Azure Media Services", "retired", "2024-06-30", "Mux or Cloudflare Stream",
       "eol_ams_retirement"),
    _r("adal", "", "Azure Active Directory Authentication Library (ADAL)", "eol", "2023-06-30", "MSAL",
       "eol_adal"),
    _r("azure_ad_graph", "", "Azure AD Graph API", "retired", "2025-08-31", "Microsoft Graph", "eol_azure_ad_graph"),
    _r("qldb", "", "Amazon QLDB", "retired", "2025-07-31", "Aurora PostgreSQL with ledger tables", "eol_qldb"),
    _r("fauna", "", "Fauna", "retired", "2025-05-30", "PostgreSQL or DynamoDB", "eol_fauna"),
    _r("minio", "", "MinIO community edition", "archived", "2026-04-25", "Ceph RGW or SeaweedFS", "minio_status",
       note="GitHub repository archived read-only on 2026-04-25 and marked no longer maintained"),
)

ROWS_BY_KEY: dict[str, EolRow] = {r.key: r for r in ROWS}
PRODUCTS: tuple[str, ...] = tuple(sorted({r.product for r in ROWS}))

ALIASES: dict[str, str] = {
    "node": "nodejs", "node.js": "nodejs", "nodejs": "nodejs",
    "py": "python", "python3": "python", "python2": "python",
    ".net": "dotnet", "dotnet": "dotnet", "dotnet core": "dotnet", ".net core": "dotnet",
    ".net framework": "dotnet_framework", "dotnetfx": "dotnet_framework", "dotnet framework": "dotnet_framework",
    "asp.net": "dotnet_framework",
    "jdk": "java", "oracle jdk": "java", "spring": "spring_boot", "spring boot": "spring_boot",
    "postgres": "postgresql", "pg": "postgresql", "psql": "postgresql",
    "mssql": "sqlserver", "sql server": "sqlserver", "microsoft sql server": "sqlserver",
    "mongo": "mongodb", "elastic": "elasticsearch",
    "windows server": "windows_server", "ie": "internet_explorer", "ie11": "internet_explorer",
    "cra": "create_react_app", "angular js": "angularjs", "vuejs": "vue", "vue.js": "vue",
    "ruby on rails": "rails", "docker-compose": "docker_compose_v1", "compose v1": "docker_compose_v1",
    "azure ad b2c": "azure_ad_b2c", "b2c": "azure_ad_b2c", "azure redis": "azure_cache_redis",
    "redis cache": "azure_cache_redis", "iot core": "gcp_iot_core", "dynamic links": "firebase_dynamic_links",
    "red hat": "rhel", "redhat": "rhel",
}

_NUMS = re.compile(r"\d+")


def _product_id(product: str) -> str:
    p = " ".join(str(product).strip().lower().replace("_", " ").split())
    if p in ALIASES:
        return ALIASES[p]
    return p.replace(" ", "_")


def _tokens(text: str | None) -> tuple[int, ...]:
    return tuple(int(n) for n in _NUMS.findall(str(text))) if text else ()


def lookup(product: str, version: str | None = None) -> EolRow | None:
    """Best row for ``product`` at ``version``, or None.

    A row matches when its cycle numbers are a prefix of the version's numbers; the longest cycle wins,
    ties go to the earlier ROWS position.  Whole-service rows (cycle "") match with or without a version.
    With no version, only whole-service rows match (an unversioned "SQL Server" gets no verdict).
    "Azure Cache for Redis Enterprise" style cycles are matched by the lower-cased word cycles too.
    """
    pid = _product_id(product)
    ver = str(version).strip().lower() if version is not None else ""
    vt = _tokens(ver)
    best: tuple[int, int] | None = None
    best_row: EolRow | None = None
    for idx, row in enumerate(ROWS):
        if row.product != pid:
            continue
        if row.cycle == "":
            score = 0
        elif row.cycle.isalpha():
            if row.cycle not in ver:
                continue
            score = 50
        else:
            ct = _tokens(row.cycle)
            if not vt or vt[:len(ct)] != ct:
                continue
            score = len(ct)
        cand = (score, -idx)
        if best is None or cand > best:
            best, best_row = cand, row
    return best_row


def status_on(row: EolRow, anchor: date = KB_DATE) -> dict:
    """Judge ``row`` on ``anchor`` (default the fixed KB date).

    ``state``: ``ended`` (date <= anchor), ``ending_soon`` (within SOON_DAYS after it) or ``supported``.
    ``days`` is end date minus anchor (negative once past).  ``mainstream_ended`` is None when the
    vendor has no separate mainstream phase.
    """
    end = date.fromisoformat(row.date)
    days = (end - anchor).days
    state = "ended" if days <= 0 else "ending_soon" if days <= SOON_DAYS else "supported"
    ms = None if row.mainstream_end is None else date.fromisoformat(row.mainstream_end) <= anchor
    return {"state": state, "kind": row.kind, "label": row.label, "date": row.date, "days": days,
            "mainstream_ended": ms, "mainstream_end": row.mainstream_end, "replacement": row.replacement,
            "source": row.source, "conf": row.conf, "note": row.note, "anchor": anchor.isoformat(),
            "key": row.key}


def verdict(product: str, version: str | None = None, anchor: date = KB_DATE) -> dict | None:
    """``lookup`` then ``status_on``; None when the product/version is not in the table."""
    row = lookup(product, version)
    return None if row is None else status_on(row, anchor)
