"""Stress-test catalog runner tool for PROMPT-003.

Reads URLs from `PROMPT-003-stress-site-catalog.md` (or command line), executes
the mandatory 3 passes per site (Rule 18) using child-process isolation to prevent
Playwright hangs from wedging the runner, measures latency and variance, and outputs
the exact markdown table ready to paste into `PROMPT-003-IMPLEMENTATION-LOG.md`.
"""

import argparse
import asyncio
import json
import os
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = BACKEND_DIR / "tests"
CAPTURE_CHILD = str(TESTS_DIR / "_capture_child_impl.py")
DEFAULT_CATALOG = (
    BACKEND_DIR.parent
    / "Prompts"
    / "Pending"
    / "Finders"
    / "PROMPT-003"
    / "PROMPT-003-stress-site-catalog.md"
)

SITE_BUDGET_S = 180


def kill_tree(pid: int) -> None:
    """Force-kill a process and its whole descendant tree on Windows."""
    taskkill = os.path.join(
        os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32", "taskkill.exe"
    )
    try:
        subprocess.run(
            [taskkill, "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            check=False,
            timeout=15,
        )
    except Exception:
        pass


async def capture_single(url: str, scratch_dir: Path) -> dict:
    """Run one fetch_page in a child process under SITE_BUDGET_S."""
    url_hash = abs(hash(url))
    out_file = str(scratch_dir / f"{url_hash}_{int(time.time()*1000)}.json")
    env = dict(os.environ)
    env["CAPTURE_CHILD_OUT"] = out_file

    started = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            CAPTURE_CHILD,
            url,
            env=env,
            cwd=str(BACKEND_DIR),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=SITE_BUDGET_S)
        except TimeoutError:
            kill_tree(proc.pid)
            return {
                "ok": False,
                "error": "stalled (timeout budget exceeded)",
                "elapsed": time.monotonic() - started,
            }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"launch_error:{exc.__class__.__name__}",
            "elapsed": time.monotonic() - started,
        }

    elapsed = time.monotonic() - started
    if not os.path.exists(out_file):
        return {"ok": False, "error": "child-crashed", "elapsed": elapsed}

    try:
        with open(out_file, encoding="utf-8", errors="replace") as fh:
            payload = json.load(fh)
    except Exception as exc:
        payload = {"ok": False, "error": f"json_read_error:{exc}", "elapsed": elapsed}
    finally:
        try:
            os.remove(out_file)
        except OSError:
            pass

    payload["elapsed"] = elapsed
    return payload


def parse_catalog(catalog_path: Path, target_tier: str | None = None) -> list[dict]:
    """Parse site URLs and categories from the markdown catalog."""
    if not catalog_path.exists():
        print(f"Catalog file not found: {catalog_path}", file=sys.stderr)
        return []

    content = catalog_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    current_tier = "UNKNOWN"
    current_category = "General"
    in_code_block = False
    sites = []

    for line in lines:
        tier_match = re.match(r"^##\s+TIER\s+([A-Z])", line, re.IGNORECASE)
        if tier_match:
            current_tier = tier_match.group(1).upper()
            continue

        cat_match = re.match(r"^###\s+(.+)", line)
        if cat_match:
            current_category = cat_match.group(1).strip()
            continue

        if line.strip() == "```":
            in_code_block = not in_code_block
            continue

        if in_code_block:
            raw_url = line.strip()
            if raw_url.startswith("http://") or raw_url.startswith("https://"):
                if target_tier is None or current_tier == target_tier.upper():
                    sites.append(
                        {
                            "url": raw_url,
                            "tier": current_tier,
                            "category": current_category,
                        }
                    )

    return sites


async def test_site(site: dict, passes: int, scratch_dir: Path) -> dict:
    """Run `passes` passes for a site and return stats."""
    url = site["url"]
    results = []
    print(f"Testing [{site['tier']}] {site['category']} -> {url} ({passes} passes)...", flush=True)

    for p in range(1, passes + 1):
        res = await capture_single(url, scratch_dir)
        results.append(res)
        status_str = f"Pass {p}: {'PASS' if res.get('ok') else 'FAIL'} ({res['elapsed']:.1f}s)"
        print(f"  {status_str}", flush=True)

    pass_times = [r["elapsed"] for r in results if r.get("ok")]
    all_times = [r["elapsed"] for r in results]
    success_count = sum(1 for r in results if r.get("ok"))

    if success_count > 0:
        times_to_stat = pass_times
    else:
        times_to_stat = all_times

    avg_time = statistics.mean(times_to_stat)
    min_time = min(times_to_stat)
    max_time = max(times_to_stat)
    variance_str = f"{min_time:.1f}s - {max_time:.1f}s (avg {avg_time:.1f}s)"

    pass_summaries = []
    for r in results:
        if r.get("ok"):
            pass_summaries.append(f"Pass ({r['elapsed']:.1f}s)")
        else:
            err = r.get("error", "unknown")[:30]
            pass_summaries.append(f"Fail ({err})")

    status = f"{success_count}/{passes} PASS"
    notes = "Clean capture" if success_count == passes else "Review failure modes"

    # If any error indicates bot protection
    errors = [r.get("error", "") for r in results if not r.get("ok")]
    if any("BOT_PROTECTION" in err or "Cloudflare" in err for err in errors):
        notes = "Bot protection detected"

    return {
        "url": url,
        "category": site["category"],
        "tier": site["tier"],
        "pass_summaries": pass_summaries,
        "variance": variance_str,
        "status": status,
        "notes": notes,
        "raw_results": results,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="PROMPT-003 Stress Catalog Runner")
    parser.add_argument("--tier", choices=["A", "B", "C"], help="Run only sites in this tier")
    parser.add_argument("--url", help="Run a single URL instead of catalog")
    parser.add_argument("--category", default="Custom", help="Category for single URL")
    parser.add_argument("--passes", type=int, default=3, help="Passes per site (default: 3)")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of sites to test")
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG), help="Path to catalog markdown file")

    args = parser.parse_args()

    scratch_dir = BACKEND_DIR / ".scratch_captures"
    scratch_dir.mkdir(parents=True, exist_ok=True)

    if args.url:
        sites = [{"url": args.url, "tier": args.tier or "Single", "category": args.category}]
    else:
        catalog_path = Path(args.catalog)
        sites = parse_catalog(catalog_path, args.tier)
        if args.limit:
            sites = sites[: args.limit]

    if not sites:
        print("No sites found to test.", file=sys.stderr)
        return

    print(f"Loaded {len(sites)} sites to test ({args.passes} passes each).")
    print("=" * 80)

    rows = []
    for site in sites:
        row = await test_site(site, args.passes, scratch_dir)
        rows.append(row)

    print("\n" + "=" * 80)
    print("MARKDOWN TABLE OUTPUT:")
    print("=" * 80 + "\n")

    header = "| URL | Category | Pass 1 | Pass 2 | Pass 3 | Variance | Status | Notes / Disposition |"
    divider = "|---|---|---|---|---|---|---|---|"
    print(header)
    print(divider)

    for r in rows:
        p1 = r["pass_summaries"][0] if len(r["pass_summaries"]) > 0 else "-"
        p2 = r["pass_summaries"][1] if len(r["pass_summaries"]) > 1 else "-"
        p3 = r["pass_summaries"][2] if len(r["pass_summaries"]) > 2 else "-"
        line = f"| {r['url']} | {r['category']} | {p1} | {p2} | {p3} | {r['variance']} | {r['status']} | {r['notes']} |"
        print(line)


if __name__ == "__main__":
    asyncio.run(main())
