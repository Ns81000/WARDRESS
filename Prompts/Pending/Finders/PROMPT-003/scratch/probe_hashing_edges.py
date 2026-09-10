"""AUDIT-3 scratch probe 1 — hashing.py normalization edge cases (Rule 13).

Verifies, empirically, the claims a fresh-eyes read would otherwise make
from the docstring: Unicode trailing-whitespace stripping (NBSP family),
blank-line stripping shape, CR normalization, surrogate replacement
determinism, and hash stability across repeated calls.
"""
import sys

sys.path.insert(0, "backend")

from worker.hashing import content_sha256, normalize_content  # noqa: E402

cases = {
    "crlf_vs_lf": ("<p>a</p>\r\n<p>b</p>", "<p>a</p>\n<p>b</p>"),
    "cr_only": ("<p>a</p>\r<p>b</p>", "<p>a</p>\n<p>b</p>"),
    "trailing_nbsp_stripped": ("<p>a</p>\u00a0", "<p>a</p>"),
    "trailing_narrow_nbsp_stripped": ("<p>a</p>\u202f", "<p>a</p>"),
    "interior_nbsp_is_content": ("<p>a\u00a0b</p>", "<p>a b</p>"),
    "trailing_tab": ("<p>a</p>\t\n<p>b</p>", "<p>a</p>\n<p>b</p>"),
    "form_feed_is_line_sep_via_split": ("<p>a</p>\x0c<p>b</p>", "<p>a</p>\x0c<p>b</p>"),
    "blank_lines_stripped": ("\n\n<p>x</p>\n\n\n", "<p>x</p>"),
    "empty_string": ("", ""),
    "whitespace_only": ("  \n \n  ", ""),
}

print("== normalize_content equality pairs (expect equal) ==")
for name, (a, b) in cases.items():
    if name == "interior_nbsp_is_content":
        eq = normalize_content(a) == normalize_content(b)
        print(f"{name}: equal={eq}  (equal would mean NBSP lost — bad)")
    else:
        print(f"{name}: equal={normalize_content(a) == normalize_content(b)}")

print("\n== representative outputs ==")
for name in ("trailing_nbsp_stripped", "interior_nbsp_is_content", "whitespace_only"):
    a, b = cases[name]
    print(f"{name}: repr(normalized)={normalize_content(a)!r}")

print("\n== surrogate determinism (3 runs must match) ==")
weird = "<p>ok\udcff</p>"
hashes = {content_sha256(weird) for _ in range(3)}
print(f"stable={len(hashes) == 1} hash={hashes.pop()[:16]}...")

print("\n== hash-vs-raw byte round trip: does hash equal sha256 of normalized utf-8? ==")
import hashlib  # noqa: E402

sample = "<html>\r\n<body>x  \n</body>\n\n</html>\n"
expect = hashlib.sha256(normalize_content(sample).encode("utf-8", errors="replace")).hexdigest()
print(f"matches_manual={content_sha256(sample) == expect}")

print("\n== None input (does the pipeline have a latent crash if html can be None?) ==")
try:
    content_sha256(None)  # type: ignore[arg-type]
    print("None accepted (unexpected)")
except AttributeError as exc:
    print(f"None raises AttributeError: {exc}")
