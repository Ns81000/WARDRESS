"""Bulk site import (§7 /api/sites/bulk-import, Phase 5).

Two sources, one request shape: inline CSV text (the dashboard reads the
chosen file client-side) or a sitemap URL to crawl. Every row is
validated independently and the response carries a per-row outcome —
imports are never all-or-nothing (§11). Each created site gets the same
treatment as single-site create: SSRF policy check up front, baseline
capture enqueued immediately.

CSV format: one site per line, `url` alone or `url,name` (an optional
header line with "url" in the first cell is skipped). Sitemap crawl
accepts a standard <urlset> and one level of <sitemapindex> nesting.
"""

import asyncio
import csv
import io
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.db import get_db
from app.deps import AnalystUser
from app.models import Baseline, BaselineStatus, Site, UserRole
from app.scanning import clamp_interval
from app.schemas import (
    BULK_IMPORT_MAX_ROWS,
    BulkImportRequest,
    BulkImportResult,
    BulkImportRowResult,
)
from app.ssrf import SSRFBlockedError, assert_url_allowed
from app.ssrf_transport import SSRFPinningTransport
from app.tasks import enqueue_baseline_capture

router = APIRouter(prefix="/api/sites", tags=["sites"])

DB = Annotated[AsyncSession, Depends(get_db)]

SITEMAP_TIMEOUT_S = 20.0
SITEMAP_MAX_BYTES = 5 * 1024 * 1024
SITEMAP_MAX_CHILD_SITEMAPS = 5
CSV_FIELD_MAX_CHARS = 128 * 1024

# Site.name is String(200). A CSV-supplied name is untrusted and otherwise
# unbounded: on Postgres an over-length value raises DataError at flush and
# (without per-row isolation) would roll back the whole import. Cap it at
# the column width so a long name degrades to a truncated name, never an
# error — matching _derive_name's own [:200] cap.
SITE_NAME_MAX = 200


def _derive_name(url: str) -> str:
    """Readable default name from a URL: host, plus a path hint."""
    parsed = urlparse(url)
    host = parsed.hostname or url
    path = (parsed.path or "").rstrip("/")
    name = host + (path if path and path != "/" else "")
    return name[:200]


def _parse_csv_rows(text: str) -> list[tuple[int, str, str | None]]:
    """[(line_number, url, name|None)] — blank lines skipped, an optional
    header line recognized by 'url' in the first cell."""
    rows: list[tuple[int, str, str | None]] = []
    old_limit = csv.field_size_limit()
    csv.field_size_limit(CSV_FIELD_MAX_CHARS)
    try:
        reader = csv.reader(io.StringIO(text), quoting=csv.QUOTE_NONE)
        for line_no, row in enumerate(reader, start=1):
            cells = [c.strip() for c in row]
            if not any(cells):
                continue
            first = cells[0]
            if line_no == 1 and first.lower() in ("url", "urls", "website", "address"):
                continue
            name = cells[1] if len(cells) > 1 and cells[1] else None
            rows.append((line_no, first, name))
    except csv.Error as exc:
        raise ValueError(f"CSV could not be parsed: {exc}") from None
    finally:
        csv.field_size_limit(old_limit)
    return rows


def _extract_sitemap_urls(xml_bytes: bytes) -> tuple[list[str], list[str]]:
    """(page_urls, child_sitemap_urls) from a sitemap document. Uses
    lxml's recovering parser — real-world sitemaps are frequently
    imperfect XML. Namespace-agnostic on purpose."""
    from lxml import etree

    parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
    try:
        root = etree.fromstring(xml_bytes, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"sitemap is not parseable XML: {exc}") from None
    if root is None:
        raise ValueError("sitemap is not parseable XML")

    def local(tag) -> str:
        return tag.split("}", 1)[-1] if isinstance(tag, str) else ""

    pages: list[str] = []
    children: list[str] = []
    is_index = local(root.tag) == "sitemapindex"
    for url_el in root.iter():
        if local(url_el.tag) not in ("url", "sitemap"):
            continue
        for loc in url_el:
            if local(loc.tag) == "loc" and loc.text and loc.text.strip():
                target = loc.text.strip()
                if is_index or local(url_el.tag) == "sitemap":
                    children.append(target)
                else:
                    pages.append(target)
    return pages, children


async def _fetch_sitemap_bytes(client: httpx.AsyncClient, url: str) -> bytes:
    async with client.stream("GET", url) as resp:
        if resp.status_code != 200:
            raise ValueError(f"sitemap fetch returned HTTP {resp.status_code}")
        content_length = resp.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > SITEMAP_MAX_BYTES:
                    raise ValueError("sitemap exceeds the configured size limit")
            except ValueError as exc:
                if str(exc) == "sitemap exceeds the configured size limit":
                    raise
                raise ValueError("sitemap has invalid Content-Length") from None

        chunks = bytearray()
        total = 0
        async for chunk in resp.aiter_bytes():
            total += len(chunk)
            if total > SITEMAP_MAX_BYTES:
                raise ValueError("sitemap exceeds the configured size limit")
            chunks.extend(chunk)
        return bytes(chunks)


async def _crawl_sitemap_impl(
    sitemap_url: str, *, allow_private_networks: bool
) -> list[tuple[int, str, str | None]]:
    """Fetch a sitemap (following one level of sitemap-index nesting) and
    return rows shaped like the CSV parser's. Network errors raise
    ValueError with a user-safe message. Every fetched URL (including
    redirect hops) honors the SSRF policy."""
    await asyncio.to_thread(
        assert_url_allowed, sitemap_url, allow_private_networks=allow_private_networks
    )

    async def redirect_guard(response: httpx.Response) -> None:
        if response.next_request is not None:
            await asyncio.to_thread(
                assert_url_allowed,
                str(response.next_request.url),
                allow_private_networks=allow_private_networks,
            )

    rows: list[tuple[int, str, str | None]] = []
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            max_redirects=5,
            timeout=httpx.Timeout(SITEMAP_TIMEOUT_S),
            # DNS-pinning transport (§9): resolve + validate + connect to
            # the same address on every hop. The response hook stays as a
            # secondary guard.
            transport=SSRFPinningTransport(allow_private_networks=allow_private_networks),
            event_hooks={"response": [redirect_guard]},
        ) as client:
            pages, children = _extract_sitemap_urls(await _fetch_sitemap_bytes(client, sitemap_url))
            for child in children[:SITEMAP_MAX_CHILD_SITEMAPS]:
                try:
                    await asyncio.to_thread(
                        assert_url_allowed, child, allow_private_networks=allow_private_networks
                    )
                    child_pages, _ = _extract_sitemap_urls(
                        await _fetch_sitemap_bytes(client, child)
                    )
                    pages.extend(child_pages)
                except (ValueError, SSRFBlockedError, httpx.HTTPError):
                    # One bad child sitemap must not sink the crawl.
                    continue
                if len(pages) >= BULK_IMPORT_MAX_ROWS:
                    break
    except SSRFBlockedError:
        raise
    except httpx.HTTPError as exc:
        raise ValueError(f"sitemap could not be fetched: {type(exc).__name__}") from None

    for i, page_url in enumerate(pages[:BULK_IMPORT_MAX_ROWS], start=1):
        rows.append((i, page_url, None))
    return rows


@router.post("/bulk-import", response_model=BulkImportResult)
async def bulk_import(
    body: BulkImportRequest,
    user: AnalystUser,
    db: DB,
) -> BulkImportResult:
    try:
        body.validate_source()
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None

    # A sitemap crawl with allow_private_networks=true relaxes the SSRF
    # policy for the crawl itself plus every child-sitemap fetch and
    # redirect hop, turning the server into an internal-network fetcher
    # (<loc> text is echoed back). That capability is admin-only. CSV
    # imports never crawl, so the flag there only governs the per-row
    # SSRF check on user-supplied URLs and stays available to analysts.
    if body.sitemap_url is not None and body.allow_private_networks and user.role != UserRole.admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Crawling a sitemap with allow_private_networks enabled requires the admin role",
        )

    if body.csv_text is not None:
        try:
            rows = _parse_csv_rows(body.csv_text)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    else:
        try:
            rows = await _crawl_sitemap_impl(
                str(body.sitemap_url), allow_private_networks=body.allow_private_networks
            )
        except SSRFBlockedError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None

    if not rows:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "No importable rows found (CSV needs one URL per line; sitemap had no <loc> entries)",
        )
    if len(rows) > BULK_IMPORT_MAX_ROWS:
        rows = rows[:BULK_IMPORT_MAX_ROWS]

    existing_urls = {u for (u,) in (await db.execute(select(Site.url))).all()}
    seen_in_batch: set[str] = set()
    results: list[BulkImportRowResult] = []
    created_baselines: list[uuid.UUID] = []
    interval = clamp_interval(body.scan_interval_minutes)

    for row_no, raw_url, name in rows:
        url = raw_url.strip()
        result = BulkImportRowResult(row=row_no, url=url[:2048], name=name, status="error")

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            result.detail = "not an http(s) URL"
            results.append(result)
            continue
        if url in existing_urls:
            result.status = "skipped"
            result.detail = "a site with this URL already exists"
            results.append(result)
            continue
        if url in seen_in_batch:
            result.status = "skipped"
            result.detail = "duplicate of an earlier row in this import"
            results.append(result)
            continue
        try:
            await asyncio.to_thread(
                assert_url_allowed, url, allow_private_networks=body.allow_private_networks
            )
        except SSRFBlockedError as exc:
            result.detail = str(exc)
            results.append(result)
            continue

        # A CSV-supplied name is untrusted; cap it to the column width so an
        # over-length value can't raise DataError at flush. (_derive_name
        # already caps its output.)
        site_name = (name or _derive_name(url))[:SITE_NAME_MAX]

        # Per-row isolation (§11 — imports are never all-or-nothing): each
        # row commits or fails on its own SAVEPOINT, so an IntegrityError or
        # DataError on one row rolls back only that row and the rest survive.
        try:
            async with db.begin_nested():
                site = Site(
                    name=site_name,
                    url=url,
                    created_by=user.id,
                    allow_private_networks=body.allow_private_networks,
                    auto_scan_enabled=body.auto_scan_enabled,
                    scan_interval_minutes=interval,
                )
                db.add(site)
                await db.flush()
                if site.auto_scan_enabled:
                    site.next_scan_at = datetime.now(UTC) + timedelta(minutes=interval)
                baseline = Baseline(
                    site_id=site.id, status=BaselineStatus.pending, is_current=False
                )
                db.add(baseline)
                await db.flush()
        except SQLAlchemyError:
            # The SAVEPOINT is rolled back; this row is an error, prior rows
            # are untouched. Keep the message generic (no DB internals).
            result.detail = "could not be saved (database rejected the row)"
            results.append(result)
            continue

        created_baselines.append(baseline.id)
        seen_in_batch.add(url)
        result.status = "created"
        result.site_id = site.id
        result.name = site.name
        results.append(result)

    created = sum(1 for r in results if r.status == "created")
    skipped = sum(1 for r in results if r.status == "skipped")
    errors = sum(1 for r in results if r.status == "error")
    record_audit(
        db,
        actor=user,
        action="site.bulk_import",
        target_type="site",
        target_label="bulk import",
        after={
            "source": "csv" if body.csv_text is not None else "sitemap",
            "rows": len(results),
            "created": created,
            "skipped": skipped,
            "errors": errors,
        },
    )
    await db.commit()

    # Enqueue captures after the commit; a dead queue leaves pending
    # baseline rows that the stale-row recovery (rebaseline) can restart.
    enqueue_failed = 0
    for baseline_id in created_baselines:
        try:
            enqueue_baseline_capture(baseline_id)
        except HTTPException:
            enqueue_failed += 1
    if enqueue_failed:
        for r in results:
            if r.status == "created":
                r.detail = (
                    "created — baseline capture could not be enqueued "
                    "(task queue unavailable); use Rebaseline once it is back"
                )

    return BulkImportResult(
        total_rows=len(results),
        created=created,
        skipped=skipped,
        errors=errors,
        results=results,
    )
