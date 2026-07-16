"""Hashing/normalization unit tests (detection layer 1 building block),
including malformed-input handling per the §13 carve-out (in-code tests
only, no live traffic)."""

from worker.hashing import content_sha256, layer1_hash_diff, normalize_content


def test_normalization_is_stable() -> None:
    html = "<html>\n<body>hello</body>\n</html>"
    assert content_sha256(html) == content_sha256(html)


def test_line_endings_do_not_change_hash() -> None:
    unix = "<p>one</p>\n<p>two</p>"
    win = "<p>one</p>\r\n<p>two</p>"
    mac = "<p>one</p>\r<p>two</p>"
    assert content_sha256(unix) == content_sha256(win) == content_sha256(mac)


def test_trailing_whitespace_ignored() -> None:
    assert content_sha256("<p>x</p>   \n<p>y</p>") == content_sha256("<p>x</p>\n<p>y</p>")


def test_leading_trailing_blank_lines_ignored() -> None:
    assert content_sha256("\n\n<p>x</p>\n\n") == content_sha256("<p>x</p>")


def test_content_change_changes_hash() -> None:
    assert content_sha256("<h1>Welcome</h1>") != content_sha256("<h1>HACKED BY ...</h1>")


def test_internal_whitespace_is_content() -> None:
    # Indentation changes ARE flagged — conservative by design.
    assert content_sha256("<p>a</p>\n  <p>b</p>") != content_sha256("<p>a</p>\n<p>b</p>")


def test_non_utf8_representable_content() -> None:
    # Lone surrogates cannot encode to UTF-8; errors=replace must keep this
    # from raising (defense against binary/mangled server responses).
    weird = "<p>ok\udcff</p>"
    assert len(content_sha256(weird)) == 64


def test_empty_and_whitespace_only() -> None:
    assert len(content_sha256("")) == 64
    assert content_sha256("") == content_sha256("   \n  \n")


def test_large_content() -> None:
    big = "<p>row</p>\n" * 500_000  # ~5.5 MB
    assert len(content_sha256(big)) == 64


def test_layer1_identical() -> None:
    h = content_sha256("<p>same</p>")
    result = layer1_hash_diff(h, h)
    assert result["score"] == 0.0
    assert result["evidence"]["identical"] is True


def test_layer1_different() -> None:
    result = layer1_hash_diff(content_sha256("a"), content_sha256("b"))
    assert result["score"] == 1.0
    assert result["evidence"]["identical"] is False
    assert result["evidence"]["baseline_sha256"] != result["evidence"]["current_sha256"]


def test_normalize_content_unicode_kept() -> None:
    # Non-Latin content must survive normalization byte-for-byte.
    text = "<p>Здравствуйте 你好 مرحبا</p>"
    assert normalize_content(text) == text
