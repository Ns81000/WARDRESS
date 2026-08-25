"""Cross-check the locked torch version(s) against OSV advisories.

pip-audit resolves packages against PyPI advisory data and silently skips
torch's CPU-index builds: their local version labels (`2.13.0+cpu`) have no
PyPI presence, so the heaviest dependency in the lockfile has zero automated
advisory coverage ("The dependency-audit gate cannot see torch"). This tool
closes that gap deterministically: it reads every locked torch version
straight from ``uv.lock``, strips local labels (advisories are keyed to
upstream release versions), and queries the OSV API for each.

Exit codes:
    0 — no known advisories for any audited version
    1 — at least one known advisory: triage before merging
    2 — could not verify (unreadable lockfile, or the OSV API stayed
        unreachable after retries). Failing closed is deliberate: a green
        gate that skipped verification when the network hiccupped would
        quietly reopen exactly the blind spot this check exists to close;
        a spurious red from an outage is resolved by re-running.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_LOCK_PATH = Path(__file__).resolve().parent.parent / "uv.lock"
OSV_QUERY_URL = "https://api.osv.dev/v1/query"
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2.0


def locked_torch_versions(lock_path: Path) -> list[str]:
    """Every distinct torch version declared by a ``[[package]]`` entry."""
    with open(lock_path, "rb") as fh:
        data = tomllib.load(fh)
    return sorted(
        {
            pkg["version"]
            for pkg in data.get("package", [])
            if pkg.get("name") == "torch" and pkg.get("version")
        }
    )


def strip_local_label(version: str) -> str:
    """``2.13.0+cpu`` -> ``2.13.0`` — OSV keys advisories to upstream versions."""
    return version.split("+", 1)[0]


def build_query(version: str) -> bytes:
    return json.dumps(
        {"package": {"name": "torch", "ecosystem": "PyPI"}, "version": version}
    ).encode()


def query_osv(payload: bytes, url: str = OSV_QUERY_URL) -> dict:
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


def query_osv_with_retry(
    payload: bytes,
    attempts: int = RETRY_ATTEMPTS,
    backoff_seconds: float = RETRY_BACKOFF_SECONDS,
) -> dict:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return query_osv(payload)
        except (urllib.error.URLError, OSError) as exc:
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(backoff_seconds * (attempt + 1))
    raise ConnectionError(
        f"OSV API unreachable after {attempts} attempts: {last_error}"
    ) from last_error


def summarize_advisory(vuln: dict) -> str:
    vuln_id = vuln.get("id", "?")
    aliases = ",".join(vuln.get("aliases", []))
    detail = vuln.get("summary") or vuln.get("details") or ""
    first_line = detail.splitlines()[0][:160] if detail else ""
    suffix = f" ({aliases})" if aliases else ""
    return f"{vuln_id}{suffix}: {first_line}".rstrip(": ")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--lock",
        type=Path,
        default=DEFAULT_LOCK_PATH,
        help="path to the uv.lock to audit (default: the repo's own)",
    )
    args = parser.parse_args(argv)

    try:
        versions = locked_torch_versions(args.lock)
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
        print(f"could not read torch versions from {args.lock}: {exc}", file=sys.stderr)
        return 2
    if not versions:
        # No torch in the lockfile means nothing is unaudited — that is a
        # pass, not a skip (the blind spot only exists while torch does).
        print("no torch entry in the lockfile — nothing to cross-check")
        return 0

    upstream_versions = sorted({strip_local_label(v) for v in versions})
    print(
        "auditing locked torch "
        f"({', '.join(versions)}; upstream versions {', '.join(upstream_versions)})"
    )

    try:
        advisory_found = False
        for version in upstream_versions:
            result = query_osv_with_retry(build_query(version))
            vulns = result.get("vulns") or []
            if not vulns:
                print(f"torch {version}: no known advisories")
                continue
            advisory_found = True
            print(f"torch {version}: {len(vulns)} known advisory/advisories")
            for vuln in vulns:
                print(f"  - {summarize_advisory(vuln)}")
    except ConnectionError as exc:
        print(f"could not verify torch advisories — {exc}", file=sys.stderr)
        return 2

    return 1 if advisory_found else 0


if __name__ == "__main__":
    raise SystemExit(main())
