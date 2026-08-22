"""Fusion Arc Part A — synthetic training-dataset builder for layer 9 fusion.

Every feature vector in the dataset is MEASURED, not authored: each sample
procedurally crafts a (baseline, current) page pair, executes the production
pipeline (`run_detection`) over it, and stores the resulting layer1-8 vector
plus generative ground truth (label 1 = hostile mutation, 0 = benign drift).
This replaces the hand-authored `_SEED_ROWS` fiction whose class/churn
confounding produced sign-inverted coefficients (audit finding 5.1).

Methodology (anti-bias controls, protocol §4.2):
- Procedural content only: nonce brand/crew/domain names from syllable
  composition; benign multilingual text from faker's localized lorem
  providers (dev dependency); attack payloads sampled MECHANICALLY from the
  production signature/semantics regexes themselves via a small regex-string
  sampler, so coverage tracks the detector definitions instead of hand-typed
  literals.
- One leet axis spans the full substitution algebra (every substitutable
  character independently transformed with seeded probability), so forms the
  current layer 5 matches (h4ck3d) and forms it misses (h@ck3d, pwn3d, 0wned)
  appear at their natural generated rate; labels stay generative regardless
  of today's emission gaps.
- Exact class balance by construction (320 attack / 320 benign + 6 sanity);
  axis x language stratification; train/val/test split (~70/15/15) with zero
  leakage: every sample's inputs are globally unique (fingerprint-checked)
  and splits are disjoint; sanity rows live in train only.
- Deterministic: fixed seed, no wall-clock values anywhere in the artifact.

Usage (from backend/):
    .venv\\Scripts\\python.exe -m tools.build_fusion_dataset             # full
    .venv\\Scripts\\python.exe -m tools.build_fusion_dataset --scale smoke
"""

from __future__ import annotations

import argparse
import colorsys
import hashlib
import io
import json
import os
import random
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("HF_HUB_OFFLINE", "1")  # generation must stay offline

from faker import Faker  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from worker.detection.fusion import FEATURE_KEYS, build_feature_vector  # noqa: E402
from worker.detection.pipeline import run_detection  # noqa: E402
from worker.detection.semantics import _AGGRESSION, _TOPICS  # noqa: E402
from worker.detection.signatures import (  # noqa: E402
    _MEDIUM,
    _PROF,
    _STRONG,
    _WEAK,
    extract_visible_text,
)
from worker.detection.types import PageData, ScanPageData, UAVariant  # noqa: E402
from worker.hashing import content_sha256  # noqa: E402

SEED = 20260822
LANGS = ("en", "ar", "ru", "zh")
FAKER_LOCALES = {"en": "en_US", "ar": "ar", "ru": "ru_RU", "zh": "zh_CN"}
SCHEMA_VERSION = 1
ARTIFACT_PATH = BACKEND_DIR / "worker" / "detection" / "training" / "fusion_dataset.json"

ATTACK_AXES: dict[str, int] = {
    "sig_strong_banner": 16,
    "sig_leet": 24,
    "sig_medium_weak": 12,
    "script_new_domain": 20,
    "iframe_new_domain": 14,
    "form_action_swap": 12,
    "hidden_spam_inline": 20,
    "hidden_spam_stealth": 16,
    "seo_spam_early": 14,
    "seo_spam_beyond_cap": 10,
    "profanity_burst": 8,
    "cloaking_heavy": 14,
    "cloaking_partial": 14,
    "nonnative_full_rewrite": 16,
    "nonnative_partial_inject": 16,
    "visual_banner_deface": 18,
    "visual_hue_recolor": 12,
    "combined_subthreshold": 20,
    "laundering_padded": 26,
    "multi_vector_screamer": 18,
}
BENIGN_AXES: dict[str, int] = {
    "identical_rescan": 28,
    "rotating_ad": 24,
    "timestamp_counter": 24,
    "ab_test_variant": 22,
    "minor_css_churn": 22,
    "cache_busting_refs": 18,
    "vendor_script_added": 26,
    "site_redesign": 30,
    "cert_header_rotation": 28,
    "editorial_update": 24,
    "theme_hue_refresh": 14,
    "benign_ua_variation": 14,
    "nonnative_editorial": 22,
    "mixed_noise_combo": 24,
}
SANITY_AXES: dict[str, int] = {
    "sanity_attack_takeover": 3,
    "sanity_benign_identical": 2,
    "sanity_benign_quiet": 1,
}

# --- procedural content primitives -------------------------------------------

_SYL_A = ("zen", "vel", "quo", "mor", "kel", "dra", "sol", "tar", "nyx", "hal", "bre", "or")
_SYL_B = (
    "trix",
    "vant",
    "peak",
    "gate",
    "via",
    "mark",
    "line",
    "core",
    "dex",
    "wave",
    "lun",
    "thos",
)
_COLLECTIVES = ("Crew", "Team", "Squad", "Army", "Section", "Unit", "Cell")

_LEET_ALIASES = {"a": "4@", "e": "3", "o": "0", "i": "1!", "s": "5$", "t": "7+", "l": "1", "g": "9"}

_WORDCHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_DIGITS = "0123456789"
_FILLER_CHARS = "abcdefghijklmnopqrstuvwxyz    "

SPAM_ADJ = ("cheap", "best", "top", "premium", "instant", "free", "exclusive", "hot")
SPAM_NOUN = ("casino", "pills", "loans", "essays", "followers", "tickets", "watches", "keys")
SPAM_TAIL = (
    "online now",
    "with fast delivery",
    "no signup needed",
    "in your area",
    "click here",
    "limited offer today",
    "while stocks last",
)

NAV_LABELS = {
    "en": ("Home", "Products", "Services", "About", "Blog", "Docs", "Contact"),
    "ar": ("الرئيسية", "المنتجات", "خدماتنا", "من نحن", "المدونة", "الدليل", "اتصل بنا"),
    "ru": ("Главная", "Продукты", "Услуги", "О нас", "Блог", "Документация", "Контакты"),
    "zh": ("首页", "产品", "服务", "关于我们", "博客", "文档", "联系我们"),
}
TAGLINES = {
    "en": "Reliable solutions for modern teams",
    "ar": "حلول موثوقة للفرق الحديثة",
    "ru": "Надёжные решения для современных команд",
    "zh": "为现代团队提供可靠的解决方案",
}
MANIFESTO = {
    "ar": (
        "تم اختراق موقعكم بالكامل",
        "نحن قادمون ولن نتوقف",
        "لا أحد في أمان",
        "هذه بداية الحساب",
        "انتظروا المزيد قريبا",
    ),
    "ru": (
        "Ваш сайт взломан полностью",
        "Мы ещё вернёмся",
        "Никто не в безопасности",
        "Это только начало",
        "Ждите новых операций",
    ),
    "zh": (
        "你们的网站已被完全攻陷",
        "我们还会回来",
        "没有人是安全的",
        "这只是开始",
        "请期待下一次行动",
    ),
}

BASE_HEADERS = {
    "content-security-policy": "default-src 'self'",
    "strict-transport-security": "max-age=63072000",
    "x-frame-options": "DENY",
    "content-type": "text/html",
}
ROBOTS_TXT = "User-agent: *\nAllow: /\n"

_FAKERS: dict[str, Faker] = {}


def get_faker(lang: str) -> Faker:
    if lang not in _FAKERS:
        _FAKERS[lang] = Faker(FAKER_LOCALES[lang])
        _FAKERS[lang].seed_instance(SEED)
    return _FAKERS[lang]


def lorem(lang: str, count: int) -> list[str]:
    return [get_faker(lang).sentence() for _ in range(count)]


def nonce_word(rng: random.Random, parts: int = 2) -> str:
    syls = [_SYL_A, _SYL_B]
    return "".join(rng.choice(syls[k % 2]) for k in range(parts)).capitalize()


def crew_name(rng: random.Random) -> str:
    name = nonce_word(rng)
    if rng.random() < 0.7:
        name += " " + rng.choice(_COLLECTIVES)
    return name


def evil_domain(rng: random.Random) -> str:
    return f"{nonce_word(rng).lower()}-{rng.randint(100, 999)}.example"


def spam_sentence(rng: random.Random) -> str:
    return f"{rng.choice(SPAM_ADJ)} {rng.choice(SPAM_NOUN)} {rng.choice(SPAM_TAIL)}"


def spam_paragraph(rng: random.Random, sentences: int = 3) -> str:
    return " ".join(spam_sentence(rng) for _ in range(sentences))


# --- regex-string sampler (derives payloads from the production patterns) -----

_QUANT_RE = re.compile(r"\{(\d+)(,(\d*))?\}")


def _read_quant(pat: str, i: int) -> tuple[str, int]:
    if i < len(pat) and pat[i] in "?*+":
        return pat[i], i + 1
    if i < len(pat) and pat[i] == "{":
        m = _QUANT_RE.match(pat, i)
        if m:
            return m.group(0), m.end()
    return "", i


def _q_reps(q: str, rng: random.Random) -> int:
    if q == "?":
        return 1 if rng.random() < 0.5 else 0
    if q == "+":
        return rng.randint(1, 3)
    if q == "*":
        return rng.randint(0, 2)
    if q.startswith("{"):
        lo_s, _, hi_s = q[1:-1].partition(",")
        lo = int(lo_s or 0)
        hi = min(int(hi_s), lo + 8) if hi_s else lo
        return rng.randint(lo, max(lo, hi))
    return 1


def _split_alternation(text: str) -> list[str]:
    branches: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "|" and depth == 0:
            branches.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    branches.append("".join(cur))
    return branches


def sample_pattern(pat: str, rng: random.Random) -> str:
    """Sample one concrete string matching `pat` (supports every construct
    used by signatures.py / semantics.py patterns: literals, \\b, \\s, \\w,
    \\. escapes, [...] classes, (...) alternation with optional groups,
    ? * + {m,n} quantifiers, .{m,n} filler)."""
    out: list[str] = []
    i, n = 0, len(pat)
    while i < n:
        c = pat[i]
        if c == "\\":
            esc = pat[i + 1]
            if esc == "b":
                i += 2
                continue
            if esc == "s":
                q, j = _read_quant(pat, i + 2)
                out.append(" " * _q_reps(q, rng))
                i = j
                continue
            pool = {"w": _WORDCHARS, "d": _DIGITS}.get(esc)
            if pool is not None:
                q, j = _read_quant(pat, i + 2)
                out.append("".join(rng.choice(pool) for _ in range(_q_reps(q, rng))))
                i = j
                continue
            q, j = _read_quant(pat, i + 2)
            out.append(esc * _q_reps(q, rng))
            i = j
            continue
        if c == "[":
            j = pat.index("]", i + 1)
            members: list[str] = []
            k = i + 1
            while k < j:
                if pat[k] == "\\":
                    members.extend({"w": _WORDCHARS, "d": _DIGITS}.get(pat[k + 1], pat[k + 1]))
                    k += 2
                    continue
                if k + 2 < j and pat[k + 1] == "-":
                    members.extend(chr(x) for x in range(ord(pat[k]), ord(pat[k + 2]) + 1))
                    k += 3
                    continue
                members.append(pat[k])
                k += 1
            q, i2 = _read_quant(pat, j + 1)
            out.append("".join(rng.choice(members) for _ in range(_q_reps(q, rng))))
            i = i2
            continue
        if c == "(":
            depth, j = 1, i + 1
            while depth:
                if pat[j] == "(":
                    depth += 1
                elif pat[j] == ")":
                    depth -= 1
                j += 1
            inner = pat[i + 1 : j - 1]
            if inner.startswith("?:"):
                inner = inner[2:]
            branches = _split_alternation(inner)
            q, i2 = _read_quant(pat, j)
            reps = _q_reps(q, rng)
            out.append("".join(sample_pattern(rng.choice(branches), rng) for _ in range(reps)))
            i = i2
            continue
        if c == ".":
            q, j = _read_quant(pat, i + 1)
            reps = _q_reps(q, rng) if q else 1
            # `.{m,n}` spans in these patterns sit between \b anchors on BOTH
            # sides, so the emitted filler must start AND end on non-word
            # characters; a zero-width span becomes one space ({0,N} with
            # N>=1 matches a single space).
            inner = max(0, min(reps, 14) - 2)
            out.append(" " + "".join(rng.choice(_FILLER_CHARS) for _ in range(inner)) + " ")
            i = j
            continue
        j = i
        run: list[str] = []
        while j < n and pat[j] not in "\\[](|).*?+{}":
            run.append(pat[j])
            j += 1
        text = "".join(run)
        if not text:
            out.append(c)
            i += 1
            continue
        q, j2 = _read_quant(pat, j)
        if q:
            head, last = text[:-1], text[-1]
            out.append(head + last * _q_reps(q, rng))
            i = j2
        else:
            out.append(text)
            i = j
    # No strip(): trailing/leading spaces are real \s+ emissions and inner
    # recursive renders would lose them if stripped at every nesting level.
    return "".join(out)


def leetify(text: str, rng: random.Random, prob: float) -> str:
    chars = []
    for ch in text:
        aliases = _LEET_ALIASES.get(ch.lower())
        if aliases and rng.random() < prob:
            chars.append(rng.choice(aliases))
        else:
            chars.append(ch)
    return "".join(chars)


def aggression_sentence(rng: random.Random) -> str:
    return sample_pattern(rng.choice(_AGGRESSION)[0].pattern, rng)


def topic_line(rng: random.Random) -> str:
    topic = rng.choice(sorted(_TOPICS))
    return sample_pattern(rng.choice(_TOPICS[topic]).pattern, rng)


def signature_line(tier_rng: random.Random) -> tuple[str, str]:
    tier = tier_rng.choice(("strong", "medium", "weak"))
    table = {"strong": _STRONG, "medium": _MEDIUM, "weak": _WEAK}[tier]
    compiled, _weight = tier_rng.choice(table)
    return sample_pattern(compiled.pattern, tier_rng), tier


# --- page construction --------------------------------------------------------

SHOT_W, SHOT_H = 683, 480


@dataclass
class Identity:
    brand: str
    slug: str
    domain: str
    hue: int
    archetype: str
    lang: str


@dataclass
class Outcome:
    html: str
    params: dict = field(default_factory=dict)
    ua_overrides: dict[str, str] = field(default_factory=dict)
    tls_current: dict | None = None
    headers_current: dict | None = None
    robots_current: str | None = None
    shot_banner: bool = False
    shot_hue_shift_deg: float = 0.0
    shot_extra_lines: int = 0
    shot_jitter: bool = False


def make_identity(rng: random.Random, lang: str, ordinal: int) -> Identity:
    brand = nonce_word(rng)
    slug = f"{brand.lower()}{ordinal:04d}"
    return Identity(
        brand=brand,
        slug=slug,
        domain=f"{slug}.example",
        hue=rng.randrange(360),
        archetype=rng.choice(("corporate", "blog", "shop", "docs")),
        lang=lang,
    )


def base_page_html(rng: random.Random, ident: Identity) -> str:
    nav_pool = NAV_LABELS[ident.lang]
    picked = rng.sample(list(nav_pool), rng.randint(4, len(nav_pool)))
    nav_html = "".join(f'<a href="/nav{k}/">{label}</a>' for k, label in enumerate(picked))
    sections = []
    for s in range(rng.randint(2, 5)):
        heading = lorem(ident.lang, 1)[0].rstrip(".")
        paras = "".join(f"<p>{p}</p>" for p in lorem(ident.lang, rng.randint(1, 2)))
        bullets = ""
        if rng.random() < 0.5:
            bullets = (
                "<ul>"
                + "".join(f"<li>{p}</li>" for p in lorem(ident.lang, rng.randint(2, 5)))
                + "</ul>"
            )
        sections.append(f'<section id="sec{s}"><h2>{heading}</h2>{paras}{bullets}</section>')
    partners = "".join(
        '<li><a href="https://www.{host}/">{text}</a></li>'.format(
            host=nonce_word(rng).lower() + "01.example", text=lorem(ident.lang, 1)[0][:30]
        )
        for _ in range(rng.randint(1, 3))
    )
    clock = (
        f"2026-08-{rng.randint(1, 28):02d} {rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:00 UTC"
    )
    visitors = rng.randint(1200, 98000)
    hero_head = lorem(ident.lang, 1)[0].rstrip(".")
    hero_sub = lorem(ident.lang, 1)[0]
    ad_text = lorem(ident.lang, 2)[0]
    footer_text = lorem(ident.lang, 1)[0]
    return (
        '<!doctype html>\n<html lang="{lang}">\n<head>\n<meta charset="utf-8">\n'
        "<title>{brand} — {tag}</title>\n"
        '<link rel="stylesheet" href="/assets/{slug}.css?v=1">\n'
        '<script src="/assets/{slug}.js?v=1"></script>\n'
        "</head>\n<body>\n"
        '<header><div class="logo">{brand}</div><nav>{nav}</nav></header>\n'
        '<section class="hero"><h1>{hero_head}</h1><p>{hero_sub}</p>'
        '<img src="/assets/banner-{slug}.png?v=1" alt="banner">'
        '<a class="cta" href="/signup">{cta}</a></section>\n'
        '<div class="ad" data-slot="sidebar">{ad_text}</div>\n'
        "<main>{sections}</main>\n"
        "<aside><h2>Partners</h2><ul>{partners}</ul></aside>\n"
        '<form action="/login" method="post"><input name="user">'
        '<input type="password" name="pw"><button>Sign in</button></form>\n'
        "<footer><p>{footer_text}</p>"
        '<span id="clock">{clock}</span> <span id="visitors">{visitors} visitors</span></footer>\n'
        "<script>window.cfg={{v:1}};</script>\n"
        "</body>\n</html>"
    ).format(
        lang=ident.lang,
        brand=ident.brand,
        tag=TAGLINES[ident.lang],
        slug=ident.slug,
        nav=nav_html,
        hero_head=hero_head,
        hero_sub=hero_sub,
        cta=lorem(ident.lang, 1)[0][:18],
        ad_text=ad_text,
        sections="".join(sections),
        partners=partners,
        footer_text=footer_text,
        clock=clock,
        visitors=visitors,
    )


def hue_rgb(hue_deg: float, light: float, sat: float = 0.45) -> tuple[int, int, int]:
    r, g, b = colorsys.hls_to_rgb((hue_deg % 360) / 360.0, light, sat)
    return (int(r * 255), int(g * 255), int(b * 255))


def shift_hue_rgb(rgb: tuple[int, int, int], delta_deg: float) -> tuple[int, int, int]:
    r, g, b = (v / 255.0 for v in rgb)
    h, light, sat = colorsys.rgb_to_hls(r, g, b)
    r2, g2, b2 = colorsys.hls_to_rgb((h + delta_deg / 360.0) % 1.0, light, sat)
    return (int(r2 * 255), int(g2 * 255), int(b2 * 255))


def render_png(
    ident: Identity,
    *,
    seed_key: str,
    banner_dark: bool = False,
    hue_shift_deg: float = 0.0,
    extra_lines: int = 0,
    jitter: bool = False,
) -> bytes:
    """Deterministic pseudo-render of a page: geometry only (bands, text
    bars), optionally recolored/dark-bannered/noised. Luminance is preserved
    under hue shifts so recolor scenarios exercise chroma-only change."""
    shot_rng = random.Random(seed_key)

    def col(light: float, sat: float = 0.45) -> tuple[int, int, int]:
        base = hue_rgb(ident.hue, light, sat)
        return shift_hue_rgb(base, hue_shift_deg) if hue_shift_deg else base

    img = Image.new("RGB", (SHOT_W, SHOT_H), (245, 245, 247))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, SHOT_W, 54], fill=col(0.32))
    draw.rectangle([14, 14, 150, 40], fill=col(0.85))
    for k in range(len(NAV_LABELS[ident.lang])):
        x = 170 + k * 72
        draw.rectangle([x, 22, x + 52, 34], fill=col(0.75))
    if banner_dark:
        draw.rectangle([0, 54, SHOT_W, int(SHOT_H * 0.38)], fill=(17, 17, 21))
        for row in range(4):
            y = 80 + row * 36
            x = 30 + shot_rng.randrange(0, 40)
            while x < SHOT_W - 60:
                w = shot_rng.randint(14, 46)
                draw.rectangle([x, y, x + w, y + 20], fill=(210, 208, 214))
                x += w + shot_rng.randint(10, 26)
        draw.rectangle([0, int(SHOT_H * 0.38) - 6, SHOT_W, int(SHOT_H * 0.38)], fill=(180, 30, 30))
    else:
        draw.rectangle([0, 54, SHOT_W, 146], fill=col(0.66))
        draw.rectangle([30, 76, 380, 96], fill=col(0.22))
        draw.rectangle([30, 108, 300, 122], fill=col(0.30))
    lines = 13 + extra_lines
    top = 166 if not banner_dark else 200
    for k in range(lines):
        y = top + k * 20
        if y > SHOT_H - 70:
            break
        w = int(SHOT_W * (0.45 + 0.5 * shot_rng.random()))
        draw.rectangle([30, y, 30 + w, y + 8], fill=(203, 203, 207))
    draw.rectangle([SHOT_W - 160, top, SHOT_W - 20, top + 120], fill=col(0.88, 0.25))
    for k in range(4):
        yy = top + 12 + k * 26
        draw.rectangle([SHOT_W - 150, yy, SHOT_W - 40, yy + 8], fill=(190, 190, 195))
    draw.rectangle([0, SHOT_H - 42, SHOT_W, SHOT_H], fill=col(0.30))
    if jitter:
        for _ in range(2600):
            x = shot_rng.randrange(SHOT_W)
            y = shot_rng.randrange(SHOT_H)
            d = shot_rng.randint(-3, 3)
            r0, g0, b0 = img.getpixel((x, y))
            draw.point(
                (x, y),
                fill=(max(0, min(255, r0 + d)), max(0, min(255, g0 + d)), max(0, min(255, b0 + d))),
            )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# --- HTML edit helpers ---------------------------------------------------------

_HERO_RE = re.compile(r'<section class="hero">.*?</section>', re.DOTALL)
_AD_RE = re.compile(r'<div class="ad"[^>]*>.*?</div>', re.DOTALL)
_MAIN_RE = re.compile(r"<main>.*?</main>", re.DOTALL)
_CLOCK_RE = re.compile(r'<span id="clock">[^<]*</span>')
_VISITORS_RE = re.compile(r'<span id="visitors">[^<]*</span>')
_PARTNER_HREF_RE = re.compile(r'href="(https://www\.[^"]+)"')


def insert_before_end(html: str, snippet: str) -> str:
    return html.replace("</body>", snippet + "\n</body>")


def hidden_divs(rng: random.Random, count: int, style: str, domains: list[str]) -> str:
    divs = []
    for k in range(count):
        href = f"https://{rng.choice(domains)}/{k}"
        divs.append(f'<div style="{style}"><a href="{href}">{spam_sentence(rng)}</a></div>')
    return "".join(divs)


def spam_section(rng: random.Random, ident: Identity, paragraphs: int, heading: bool = True) -> str:
    body = "".join(f"<p>{spam_paragraph(rng)}</p>" for _ in range(paragraphs))
    h = f"<h2>{spam_paragraph(rng, 1)}</h2>" if heading else ""
    return f'<section id="promo">{h}{body}</section>'


def ensure_long_page(rng: random.Random, ident: Identity, html: str, min_chars: int) -> str:
    while len(extract_visible_text(html)) < min_chars:
        html = insert_before_end(
            html, f'<section id="pad"><p>{lorem(ident.lang, 3)[0]}</p></section>'
        )
    return html


# --- attack mutations -----------------------------------------------------------


def mut_sig_strong_banner(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    compiled = rng.choice(_STRONG)
    line = sample_pattern(compiled[0].pattern, rng)
    crew = crew_name(rng)
    headline = f"{line.upper()} — {crew}"
    sub = lorem(ident.lang, 1)[0]
    if rng.random() < 0.5:
        sub += " " + aggression_sentence(rng)
    new_hero = f'<section class="hero"><h1>{headline}</h1><p>{sub}</p></section>'
    return Outcome(_HERO_RE.sub(new_hero, html), {"headline": headline[:90]})


def mut_sig_leet(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    verb = rng.choice(("HACKED BY", "OWNED BY", "PWNED BY", "DEFACED BY", "ROOTED BY"))
    prob = round(rng.uniform(0.25, 0.95), 2)
    headline = leetify(f"{verb} {crew_name(rng)}", rng, prob)
    sub = lorem(ident.lang, 1)[0]
    new_hero = f'<section class="hero"><h1>{headline}</h1><p>{sub}</p></section>'
    params = {"verb": verb, "leet_prob": prob, "headline": headline[:90]}
    if rng.random() < 0.5:
        params["greetz"] = True
        new_hero = new_hero.replace("</section>", f"<p>Greetz to {crew_name(rng)}</p></section>")
    return Outcome(_HERO_RE.sub(new_hero, html), params)


def mut_sig_medium_weak(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    line, tier = signature_line(rng)
    para = f"<p>{line.capitalize()}. {lorem(ident.lang, 1)[0]}</p>"
    return Outcome(insert_before_end(html, para), {"line": line[:90], "tier": tier})


def _attack_snippet_core(rng: random.Random, ident: Identity, html: str) -> Outcome:
    kind = rng.choice(("strong", "leet", "script"))
    if kind == "strong":
        return mut_sig_strong_banner(rng, ident, html, 0)
    if kind == "leet":
        return mut_sig_leet(rng, ident, html, 0)
    doms = [evil_domain(rng) for _ in range(rng.randint(1, 2))]
    snips = "".join(f'<script src="https://{d}/x.js"></script>' for d in doms)
    return Outcome(insert_before_end(html, snips), {"new_domains": doms})


def mut_script_new_domain(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    doms = [evil_domain(rng) for _ in range(rng.randint(1, 3))]
    snips = "".join(f'<script src="https://{d}/x.js"></script>' for d in doms)
    return Outcome(insert_before_end(html, snips), {"new_domains": doms})


def mut_iframe_new_domain(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    dom = evil_domain(rng)
    if rng.random() < 0.5:
        snip = f'<iframe src="https://{dom}/frame" width="320" height="240"></iframe>'
    else:
        snip = f'<iframe src="https://{dom}/frame" style="display:none"></iframe>'
    return Outcome(insert_before_end(html, snip), {"domain": dom})


def mut_form_action_swap(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    dom = evil_domain(rng)
    swapped = html.replace('action="/login"', f'action="https://{dom}/login"')
    return Outcome(swapped, {"domain": dom})


def mut_hidden_spam_inline(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    count = rng.randint(5, 40)
    doms = [evil_domain(rng) for _ in range(rng.randint(1, 3))]
    return Outcome(
        insert_before_end(html, hidden_divs(rng, count, "display:none", doms)),
        {"count": count, "domains": doms},
    )


def mut_hidden_spam_stealth(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    technique = rng.choice(("opacity", "font-size", "offscreen", "stylesheet"))
    styles = {
        "opacity": "opacity:0",
        "font-size": "font-size:0",
        "offscreen": "position:absolute;left:-9999px",
        "stylesheet": "",
    }
    count = rng.randint(4, 20)
    doms = [evil_domain(rng) for _ in range(rng.randint(1, 2))]
    snippet = hidden_divs(rng, count, styles[technique], doms)
    if technique == "stylesheet":
        cls = f"srx{idx % 97}"
        snippet = snippet.replace("<div ", f'<div class="{cls}" ')
        snippet += f"<style>.{cls}{{display:none}}</style>"
    return Outcome(
        insert_before_end(html, snippet),
        {"technique": technique, "count": count},
    )


def mut_seo_spam_early(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    block = spam_section(rng, ident, rng.randint(1, 3))
    return Outcome(_HERO_RE.sub(lambda m: m.group(0) + block, html), {})


def mut_seo_spam_beyond_cap(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    long_html = ensure_long_page(rng, ident, html, 5500)
    block = spam_section(rng, ident, rng.randint(2, 4))
    return Outcome(
        insert_before_end(long_html, block),
        {"baseline_visible_chars": len(extract_visible_text(long_html))},
    )


def mut_profanity_burst(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    words = " ".join(
        sample_pattern(p.pattern, rng) for p in rng.choices(_PROF, k=rng.randint(3, 8))
    )
    return Outcome(insert_before_end(html, f"<p>{words}</p>"), {"hits": words.count(" ") + 1})


def mut_cloaking_heavy(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    spam_html = (
        "<html><body><h1>"
        + spam_paragraph(rng, 1)
        + "</h1>"
        + "".join(f"<p>{spam_paragraph(rng)}</p>" for _ in range(rng.randint(2, 5)))
        + "</body></html>"
    )
    return Outcome(html, {"target": "googlebot"}, ua_overrides={"googlebot": spam_html})


def mut_cloaking_partial(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    t = round(rng.uniform(0.15, 0.85), 2)
    ref_words = len(extract_visible_text(html).split())
    spam_tokens = max(1, int(ref_words * t / max(0.05, (1 - t))))
    # Distinct nonce tokens so the token-SET divergence tracks the target
    # (repeated real words would collapse under set-based Jaccard).
    tokens = " ".join(f"{nonce_word(rng, 1).lower()}{k}" for k in range(spam_tokens))
    injected = html.replace("</main>", f'<section id="crawler"><p>{tokens}</p></section></main>')
    return Outcome(
        html,
        {"divergence_target": t, "spam_tokens": spam_tokens},
        ua_overrides={"googlebot": injected},
    )


def _manifesto_paragraph(rng: random.Random, target_lang: str) -> str:
    if target_lang == "en":
        parts = [aggression_sentence(rng) for _ in range(rng.randint(2, 4))]
        if rng.random() < 0.6:
            parts.append(topic_line(rng))
        return ". ".join(parts) + "."
    return ". ".join(rng.choice(MANIFESTO[target_lang]) for _ in range(rng.randint(2, 4))) + "."


def _manifesto_headline(rng: random.Random, target_lang: str) -> str:
    if target_lang == "en":
        return aggression_sentence(rng).upper()
    return MANIFESTO[target_lang][0]


def mut_nonnative_full_rewrite(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    others = [lang for lang in LANGS if lang != ident.lang]
    target = rng.choice(others)
    paras = "".join(f"<p>{_manifesto_paragraph(rng, target)}</p>" for _ in range(rng.randint(4, 8)))
    new_main = (
        f'<main><section id="msg"><h1>{_manifesto_headline(rng, target)}</h1>'
        f"{paras}</section></main>"
    )
    rewritten = _MAIN_RE.sub(new_main, html)
    return Outcome(rewritten, {"target_script": target})


def mut_nonnative_partial_inject(
    rng: random.Random, ident: Identity, html: str, idx: int
) -> Outcome:
    others = [lang for lang in LANGS if lang != ident.lang]
    target = rng.choice(others)
    banner = (
        f'<section id="notice"><h2>{_manifesto_headline(rng, target)}</h2>'
        f"<p>{_manifesto_paragraph(rng, target)}</p></section>"
    )
    return Outcome(insert_before_end(html, banner), {"target_script": target})


def mut_visual_banner_deface(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    if rng.random() < 0.5:
        # pure server-side asset swap: DOM serialization untouched
        return Outcome(html, {"dom_change": False}, shot_banner=True)
    ad_swap = _AD_RE.sub(
        '<div class="ad" data-slot="sidebar">' + lorem(ident.lang, 1)[0] + "</div>", html
    )
    return Outcome(ad_swap, {"dom_change": True}, shot_banner=True)


def mut_visual_hue_recolor(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    shift = rng.choice((-1, 1)) * round(rng.uniform(80, 160), 1)
    marker = f'<p id="seasonal">{lorem(ident.lang, 1)[0]}</p>'
    return Outcome(
        insert_before_end(html, marker),
        {"hue_shift_deg": shift},
        shot_hue_shift_deg=shift,
    )


def mut_combined_subthreshold(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    chosen = rng.sample(
        ("tiny_hidden", "greetz", "small_spam", "extra_links", "tiny_visual", "mild_recolor"),
        k=rng.randint(2, 3),
    )
    out = Outcome(html, {"components": sorted(chosen)})
    if "tiny_hidden" in chosen:
        doms = [evil_domain(rng)]
        out.html = insert_before_end(
            out.html, hidden_divs(rng, rng.randint(1, 3), "display:none", doms)
        )
    if "greetz" in chosen:
        line, tier = signature_line(random.Random(f"{SEED}|combo|sig|{idx}"))
        out.html = insert_before_end(out.html, f"<p>{line}.</p>")
        out.params["sig_tier"] = tier
    if "small_spam" in chosen:
        out.html = insert_before_end(out.html, f"<p>{spam_paragraph(rng, 1)}</p>")
    if "extra_links" in chosen:
        links = "".join(
            f'<a href="/offer{k}/">{spam_sentence(rng)}</a>' for k in range(rng.randint(2, 3))
        )
        out.html = insert_before_end(out.html, links)
    if "tiny_visual" in chosen:
        out.shot_extra_lines = rng.randint(1, 2)
    if "mild_recolor" in chosen:
        out.shot_hue_shift_deg = rng.choice((-1, 1)) * round(rng.uniform(30, 60), 1)
    return out


def mut_laundering_padded(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    core = _attack_snippet_core(rng, ident, html)
    pad_count = rng.choice((2, 4, 8, 16, 32, 60))
    doms = [f"partner-{nonce_word(rng).lower()}.example"]
    padding = hidden_divs(rng, pad_count, "display:none", doms)
    padded = insert_before_end(core.html, padding)
    extras = []
    if rng.random() < 0.5:
        extras.append("csp_tightened")
        core.headers_current = dict(
            BASE_HEADERS, **{"content-security-policy": "default-src 'self'; script-src 'self'"}
        )
        core.tls_current = {
            "fingerprint_sha256": hashlib.sha256(f"{ident.slug}-re".encode()).hexdigest(),
            "not_after": "2027-03-15T00:00:00+00:00",
            "expired": False,
            "subject": f"CN={ident.domain}",
            "issuer": "CN=Let's Encrypt R11,O=Let's Encrypt,C=US",
        }
    core.params.update({"padding_hidden_divs": pad_count, "extras": extras})
    return Outcome(
        padded, core.params, tls_current=core.tls_current, headers_current=core.headers_current
    )


def mut_multi_vector_screamer(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    out = mut_sig_strong_banner(rng, ident, html, idx)
    out.html = insert_before_end(
        out.html,
        f"<p>{aggression_sentence(rng)}. {topic_line(rng)}</p>"
        + f'<script src="https://{evil_domain(rng)}/x.js"></script>'
        + f'<iframe src="https://{evil_domain(rng)}/f" width="10" height="10"></iframe>'
        + hidden_divs(rng, rng.randint(8, 25), "display:none", [evil_domain(rng)]),
    )
    out.shot_banner = True
    spam_html = (
        "<html><body>"
        + "".join(f"<p>{spam_paragraph(rng)}</p>" for _ in range(4))
        + "</body></html>"
    )
    out.ua_overrides["googlebot"] = spam_html
    out.params["screamer"] = True
    return out


ATTACK_MUTATIONS = {
    "sig_strong_banner": mut_sig_strong_banner,
    "sig_leet": mut_sig_leet,
    "sig_medium_weak": mut_sig_medium_weak,
    "script_new_domain": mut_script_new_domain,
    "iframe_new_domain": mut_iframe_new_domain,
    "form_action_swap": mut_form_action_swap,
    "hidden_spam_inline": mut_hidden_spam_inline,
    "hidden_spam_stealth": mut_hidden_spam_stealth,
    "seo_spam_beyond_cap": mut_seo_spam_beyond_cap,
    "seo_spam_early": mut_seo_spam_early,
    "profanity_burst": mut_profanity_burst,
    "cloaking_heavy": mut_cloaking_heavy,
    "cloaking_partial": mut_cloaking_partial,
    "nonnative_full_rewrite": mut_nonnative_full_rewrite,
    "nonnative_partial_inject": mut_nonnative_partial_inject,
    "visual_banner_deface": mut_visual_banner_deface,
    "visual_hue_recolor": mut_visual_hue_recolor,
    "combined_subthreshold": mut_combined_subthreshold,
    "laundering_padded": mut_laundering_padded,
    "multi_vector_screamer": mut_multi_vector_screamer,
}


# --- benign mutations -----------------------------------------------------------


def _benign_noop(html: str) -> Outcome:
    return Outcome(html)


def mut_rotating_ad(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    new_ad = _AD_RE.sub(
        '<div class="ad" data-slot="sidebar">' + lorem(ident.lang, 2)[0] + "</div>", html
    )
    return Outcome(new_ad, {})


def mut_timestamp_counter(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    clock = _CLOCK_RE.sub(
        f'<span id="clock">2026-08-{rng.randint(1, 28):02d} '
        f"{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d} UTC</span>",
        html,
    )
    visitors = _VISITORS_RE.sub(
        f'<span id="visitors">{rng.randint(1200, 99000)} visitors</span>', clock
    )
    return Outcome(visitors, {})


def mut_ab_test_variant(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    alt_hero = (
        '<section class="hero"><h1>'
        + lorem(ident.lang, 1)[0].rstrip(".")
        + "</h1><p>"
        + lorem(ident.lang, 1)[0]
        + '</p><img src="/assets/banner-'
        + ident.slug
        + '.png?v=1" alt="banner">'
        '<a class="cta" href="/signup">' + lorem(ident.lang, 1)[0][:18] + "</a></section>"
    )
    return Outcome(_HERO_RE.sub(alt_hero, html), {})


def mut_minor_css_churn(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    nodes = "".join(
        rng.choice(("<span>", "</em>", "<em>", "</span>", "<b>", "</b>", "<br>"))
        for _ in range(rng.randint(2, 6))
    )
    churned = insert_before_end(html, nodes)
    churned = churned.replace('id="sec0"', 'id="sec0a"', 1)
    return Outcome(churned, {})


def mut_cache_busting_refs(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    v = rng.randint(2, 99)
    busted = html.replace("?v=1", f"?v={v}")
    return Outcome(busted, {"version": v})


def mut_vendor_script_added(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    doms = [evil_domain(rng) for _ in range(rng.randint(1, 3))]
    tags = "".join(f'<script src="https://cdn.{d}/t.js" async></script>' for d in doms)
    return Outcome(insert_before_end(html, tags), {"vendor_domains": doms})


def mut_site_redesign(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    sections = []
    for s in range(rng.randint(2, 6)):
        heading = lorem(ident.lang, 1)[0].rstrip(".")
        paras = "".join(f"<p>{p}</p>" for p in lorem(ident.lang, rng.randint(1, 3)))
        sections.append(f'<section id="rs{s}"><h2>{heading}</h2>{paras}</section>')
    redesigned = _MAIN_RE.sub("<main>" + "".join(sections) + "</main>", html)
    if rng.random() < 0.4:
        redesigned = _AD_RE.sub("", redesigned)
    return Outcome(redesigned, {})


def mut_cert_header_rotation(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    variants = rng.sample(
        ("reissue", "csp_changed", "hsts_changed", "robots_edit"), k=rng.randint(1, 3)
    )
    out = Outcome(html, {"variants": variants})
    if "reissue" in variants:
        out.tls_current = {
            "fingerprint_sha256": hashlib.sha256(f"{ident.slug}-rotated".encode()).hexdigest(),
            "not_after": "2027-09-01T00:00:00+00:00",
            "expired": False,
            "subject": f"CN={ident.domain}",
            "issuer": "CN=Let's Encrypt R11,O=Let's Encrypt,C=US",
        }
    if "csp_changed" in variants:
        out.headers_current = dict(
            BASE_HEADERS,
            **{"content-security-policy": "default-src 'self'; script-src 'self' 'unsafe-inline'"},
        )
    if "hsts_changed" in variants:
        out.headers_current = dict(
            out.headers_current or BASE_HEADERS, **{"strict-transport-security": "max-age=31536000"}
        )
    if "robots_edit" in variants:
        out.robots_current = ROBOTS_TXT + f"Sitemap: https://{ident.domain}/sitemap.xml\n"
    return out


def mut_editorial_update(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    partner = _PARTNER_HREF_RE.search(html)
    link = partner.group(1) if partner else f"https://www.{ident.domain}/"
    post = (
        f"<article><h2>{lorem(ident.lang, 1)[0].rstrip('.')}</h2>"
        + "".join(f"<p>{p}</p>" for p in lorem(ident.lang, rng.randint(1, 3)))
        + f'<p><a href="/archive/">Archive</a> · <a href="{link}">Partner</a></p></article>'
    )
    return Outcome(insert_before_end(html, post), {})


def mut_theme_hue_refresh(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    shift = rng.choice((-1, 1)) * round(rng.uniform(80, 160), 1)
    return Outcome(html, {"hue_shift_deg": shift}, shot_hue_shift_deg=shift)


def mut_benign_ua_variation(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    # Small server-side variation for one UA (collapsed partner list): must
    # stay below layer 7's 0.5 knee, so only a small token mass may differ.
    mobile = re.sub(r"<aside>.*?</aside>", "<aside></aside>", html, flags=re.DOTALL)
    return Outcome(html, {}, ua_overrides={"mobile_safari": mobile})


def mut_nonnative_editorial(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    return mut_editorial_update(rng, ident, html, idx)


def mut_mixed_noise_combo(rng: random.Random, ident: Identity, html: str, idx: int) -> Outcome:
    out = mut_rotating_ad(rng, ident, html, idx)
    out = Outcome(mut_timestamp_counter(rng, ident, out.html, idx).html, {})
    v = rng.randint(2, 99)
    out.html = out.html.replace("?v=1", f"?v={v}")
    if rng.random() < 0.5:
        out.html = insert_before_end(
            out.html, "".join("<em>t</em>" for _ in range(rng.randint(1, 3)))
        )
    return out


BENIGN_MUTATIONS = {
    "identical_rescan": lambda rng, ident, html, idx: Outcome(html, {}, shot_jitter=True),
    "rotating_ad": mut_rotating_ad,
    "timestamp_counter": mut_timestamp_counter,
    "ab_test_variant": mut_ab_test_variant,
    "minor_css_churn": mut_minor_css_churn,
    "cache_busting_refs": mut_cache_busting_refs,
    "vendor_script_added": mut_vendor_script_added,
    "site_redesign": mut_site_redesign,
    "cert_header_rotation": mut_cert_header_rotation,
    "editorial_update": mut_editorial_update,
    "theme_hue_refresh": mut_theme_hue_refresh,
    "benign_ua_variation": mut_benign_ua_variation,
    "nonnative_editorial": mut_nonnative_editorial,
    "mixed_noise_combo": mut_mixed_noise_combo,
}


MUTATIONS: dict[str, object] = {**ATTACK_MUTATIONS, **BENIGN_MUTATIONS}


# --- measurement -----------------------------------------------------------------


def _tls_for(ident: Identity, fingerprint_seed: str = "") -> dict:
    fp_source = f"{ident.slug}{fingerprint_seed}"
    return {
        "fingerprint_sha256": hashlib.sha256(fp_source.encode()).hexdigest(),
        "not_after": "2027-03-15T00:00:00+00:00",
        "expired": False,
        "subject": f"CN={ident.domain}",
        "issuer": "CN=Let's Encrypt R11,O=Let's Encrypt,C=US",
    }


def measure_pair(
    axis: str, label: int, idx: int, lang: str, baseline: PageData, current: ScanPageData
) -> dict:
    results = run_detection(baseline, current)
    feats = [round(float(v), 4) for v in build_feature_vector(results)[0]]
    skipped = sorted(k for k in FEATURE_KEYS if results.get(k, {}).get("skipped"))
    fp_payload = json.dumps(
        [
            baseline.html,
            current.html,
            [u.html for u in current.ua_variants],
            hashlib.sha256(baseline.screenshot).hexdigest(),
            hashlib.sha256(current.screenshot).hexdigest(),
        ],
        ensure_ascii=False,
    )
    fingerprint = hashlib.sha256(fp_payload.encode("utf-8")).hexdigest()
    return {
        "id": f"{axis}-{idx:04d}",
        "label": label,
        "axis": axis,
        "language": lang,
        "sanity": axis.startswith("sanity_"),
        "split": "",
        "features": feats,
        "layers_skipped": skipped,
        "params": {},
        "input_sha256": fingerprint,
    }


def measure_sample(
    axis: str, label: int, idx: int, lang: str, scale_counts: dict | None = None
) -> dict:
    rng = random.Random(f"{SEED}|{axis}|{idx}")
    ident = make_identity(rng, lang, idx)
    base_html = base_page_html(rng, ident)
    outcome = MUTATIONS[axis](rng, ident, base_html, idx)
    cur_html = outcome.html
    # Both captures share one render seed: the procedural renderer is the
    # stand-in for a deterministic page, so pixel differences must come only
    # from the mutation's visual deltas (banner/hue/extra content) or explicit
    # rendering-noise jitter — never from unrelated layout redraws.
    shot_seed = f"{SEED}|shot|{axis}|{idx}"
    b_shot = render_png(ident, seed_key=shot_seed)
    c_shot = render_png(
        ident,
        seed_key=shot_seed,
        banner_dark=outcome.shot_banner,
        hue_shift_deg=outcome.shot_hue_shift_deg,
        extra_lines=outcome.shot_extra_lines,
        jitter=outcome.shot_jitter,
    )

    def variant(key: str, html: str) -> UAVariant:
        return UAVariant(
            ua_key=key,
            html=html,
            http_status=200,
            final_url=f"https://{ident.domain}/",
            content_hash=content_sha256(html) if html else "",
        )

    ua_variants = [
        variant("desktop_chrome", cur_html),
        variant("googlebot", outcome.ua_overrides.get("googlebot", cur_html)),
        variant("mobile_safari", outcome.ua_overrides.get("mobile_safari", cur_html)),
    ]
    baseline = PageData(
        html=base_html,
        screenshot=b_shot,
        final_url=f"https://{ident.domain}/",
        http_status=200,
        headers=dict(BASE_HEADERS),
        tls=_tls_for(ident),
        robots_txt=ROBOTS_TXT,
        content_hash=content_sha256(base_html),
    )
    current = ScanPageData(
        html=cur_html,
        screenshot=c_shot,
        final_url=f"https://{ident.domain}/",
        http_status=200,
        headers=outcome.headers_current or dict(BASE_HEADERS),
        tls=outcome.tls_current or _tls_for(ident),
        robots_txt=outcome.robots_current or ROBOTS_TXT,
        content_hash=content_sha256(cur_html),
        ua_variants=ua_variants,
    )
    sample = measure_pair(axis, label, idx, lang, baseline, current)
    sample["params"] = outcome.params
    return sample


def build_sanity_takeover(idx: int) -> dict:
    rng = random.Random(f"{SEED}|sanity_attack|{idx}")
    ident = make_identity(rng, "en", 9000 + idx)
    base_html = base_page_html(rng, ident)
    out = mut_multi_vector_screamer(rng, ident, base_html, idx)
    out.shot_banner = True
    takeover = insert_before_end(
        out.html,
        "".join(f"<p>{sample_pattern(p.pattern, rng)}</p>" for p in rng.choices(_PROF, k=4)),
    )
    spam_html = (
        "<html><body>"
        + "".join(f"<p>{spam_paragraph(rng)}</p>" for _ in range(6))
        + "</body></html>"
    )
    baseline = PageData(
        html=base_html,
        screenshot=render_png(ident, seed_key=f"{SEED}|sanb|{idx}"),
        final_url=f"https://{ident.domain}/",
        http_status=200,
        headers=dict(BASE_HEADERS),
        tls=_tls_for(ident),
        robots_txt=ROBOTS_TXT,
        content_hash=content_sha256(base_html),
    )
    cur_html = takeover
    current = ScanPageData(
        html=cur_html,
        screenshot=render_png(ident, seed_key=f"{SEED}|sanc|{idx}", banner_dark=True),
        final_url=f"https://{ident.domain}/",
        http_status=200,
        headers=dict(BASE_HEADERS),
        tls=_tls_for(ident),
        robots_txt=ROBOTS_TXT,
        content_hash=content_sha256(cur_html),
        ua_variants=[
            UAVariant(
                "desktop_chrome",
                cur_html,
                200,
                f"https://{ident.domain}/",
                None,
                content_sha256(cur_html),
            ),
            UAVariant(
                "googlebot",
                spam_html,
                200,
                f"https://{ident.domain}/",
                None,
                content_sha256(spam_html),
            ),
            UAVariant(
                "mobile_safari",
                cur_html,
                200,
                f"https://{ident.domain}/",
                None,
                content_sha256(cur_html),
            ),
        ],
    )
    sample = measure_pair("sanity_attack_takeover", 1, idx, "en", baseline, current)
    sample["params"] = {"classic_total_takeover": True}
    return sample


def build_sanity_identical(idx: int) -> dict:
    rng = random.Random(f"{SEED}|sanity_ident|{idx}")
    ident = make_identity(rng, "en", 9100 + idx)
    html = base_page_html(rng, ident)
    shot_a = render_png(ident, seed_key=f"{SEED}|sanib|{idx}")
    shot_b = render_png(ident, seed_key=f"{SEED}|sanib|{idx}", jitter=True)
    baseline = PageData(
        html=html,
        screenshot=shot_a,
        final_url=f"https://{ident.domain}/",
        http_status=200,
        headers=dict(BASE_HEADERS),
        tls=_tls_for(ident),
        robots_txt=ROBOTS_TXT,
        content_hash=content_sha256(html),
    )
    current = ScanPageData(
        html=html,
        screenshot=shot_b,
        final_url=f"https://{ident.domain}/",
        http_status=200,
        headers=dict(BASE_HEADERS),
        tls=_tls_for(ident),
        robots_txt=ROBOTS_TXT,
        content_hash=content_sha256(html),
        ua_variants=[
            UAVariant(
                "desktop_chrome", html, 200, f"https://{ident.domain}/", None, content_sha256(html)
            ),
            UAVariant(
                "googlebot", html, 200, f"https://{ident.domain}/", None, content_sha256(html)
            ),
            UAVariant(
                "mobile_safari", html, 200, f"https://{ident.domain}/", None, content_sha256(html)
            ),
        ],
    )
    sample = measure_pair("sanity_benign_identical", 0, idx, "en", baseline, current)
    sample["params"] = {"rendering_noise_only": True}
    return sample


def build_sanity_quiet(idx: int) -> dict:
    rng = random.Random(f"{SEED}|sanity_quiet|{idx}")
    ident = make_identity(rng, "en", 9200 + idx)
    html = base_page_html(rng, ident)
    quiet = _VISITORS_RE.sub('<span id="visitors">987654 visitors</span>', html)
    baseline = PageData(
        html=html,
        screenshot=render_png(ident, seed_key=f"{SEED}|sanqb|{idx}"),
        final_url=f"https://{ident.domain}/",
        http_status=200,
        headers=dict(BASE_HEADERS),
        tls=_tls_for(ident),
        robots_txt=ROBOTS_TXT,
        content_hash=content_sha256(html),
    )
    current = ScanPageData(
        html=quiet,
        screenshot=render_png(ident, seed_key=f"{SEED}|sanqc|{idx}"),
        final_url=f"https://{ident.domain}/",
        http_status=200,
        headers=dict(BASE_HEADERS),
        tls=_tls_for(ident),
        robots_txt=ROBOTS_TXT,
        content_hash=content_sha256(quiet),
        ua_variants=[
            UAVariant(
                "desktop_chrome",
                quiet,
                200,
                f"https://{ident.domain}/",
                None,
                content_sha256(quiet),
            ),
            UAVariant(
                "googlebot", quiet, 200, f"https://{ident.domain}/", None, content_sha256(quiet)
            ),
            UAVariant(
                "mobile_safari", quiet, 200, f"https://{ident.domain}/", None, content_sha256(quiet)
            ),
        ],
    )
    sample = measure_pair("sanity_benign_quiet", 0, idx, "en", baseline, current)
    sample["params"] = {"counter_bump_only": True}
    return sample


# --- splits, validation, assembly -------------------------------------------------


def assign_splits(samples: list[dict]) -> None:
    """Budgeted stratified split: each label gets its own ~15% val/test
    budget, consumed as (label, axis) groups are walked in deterministic
    order with seeded shuffles. Per-split class balance is therefore
    structural at every scale, not emergent from per-axis luck; train always
    retains at least half of any group."""
    groups: dict[tuple[int, str], list[int]] = {}
    for pos, sample in enumerate(samples):
        if sample["sanity"]:
            sample["split"] = "train"
            continue
        groups.setdefault((sample["label"], sample["axis"]), []).append(pos)

    totals = {
        label: sum(len(poss) for (lbl, _), poss in groups.items() if lbl == label)
        for label in (0, 1)
    }
    budgets = {
        label: {"test": round(totals[label] * 0.15), "val": round(totals[label] * 0.15)}
        for label in totals
    }

    for label in (0, 1):
        for axis in sorted(a for (lbl, a) in groups if lbl == label):
            positions = groups[(label, axis)]
            n = len(positions)
            shuffled = list(positions)
            random.Random(f"{SEED}|split|{axis}|{label}").shuffle(shuffled)
            quota = max(1, round(n * 0.15)) if n >= 3 else 0
            cap = (n - 1) // 2
            take_test = min(quota, cap, budgets[label]["test"])
            take_val = min(quota, cap, budgets[label]["val"])
            budgets[label]["test"] -= take_test
            budgets[label]["val"] -= take_val
            test_set = set(shuffled[:take_test])
            val_set = set(shuffled[take_test : take_test + take_val])
            for pos in positions:
                samples[pos]["split"] = (
                    "test" if pos in test_set else "val" if pos in val_set else "train"
                )


def nearest_cross_split_distance(samples: list[dict]) -> tuple[float, str, str]:
    best_dist, best_pair = 1.1, ("", "")
    nonzero = [s for s in samples if any(s["features"])]
    for i, a in enumerate(nonzero):
        for b in nonzero[i + 1 :]:
            if a["split"] == b["split"]:
                continue
            dist = max(abs(x - y) for x, y in zip(a["features"], b["features"], strict=True))
            if dist < best_dist:
                best_dist, best_pair = dist, (a["id"], b["id"])
    return best_dist, best_pair[0], best_pair[1]


def cross_split_feature_duplicates(samples: list[dict]) -> list[tuple[str, str]]:
    seen: dict[tuple[float, ...], str] = {}
    dups: list[tuple[str, str]] = []
    for s in samples:
        key = tuple(s["features"])
        if key == (0.0,) * len(FEATURE_KEYS):
            continue
        if key in seen and seen[key] != s["id"]:
            dups.append((seen[key], s["id"]))
        elif key not in seen:
            seen[key] = s["id"]
    return [(a, b) for a, b in dups]


def validate(samples: list[dict]) -> dict:
    fingerprints = [s["input_sha256"] for s in samples]
    if len(set(fingerprints)) != len(fingerprints):
        raise ValueError("input fingerprint collision — leakage guard tripped")
    ids = [s["id"] for s in samples]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate sample ids")
    for s in samples:
        feats = s["features"]
        if len(feats) != len(FEATURE_KEYS):
            raise ValueError(f"{s['id']}: wrong feature width")
        for v in feats:
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"{s['id']}: feature out of range: {feats}")
    labels = [s["label"] for s in samples]
    n_attack, n_benign = sum(labels), len(labels) - sum(labels)
    if n_attack != n_benign:
        raise ValueError(f"class imbalance: {n_attack} attack vs {n_benign} benign")
    for split in ("train", "val", "test"):
        rows = [s for s in samples if s["split"] == split]
        if not split == "test" and not rows:
            raise ValueError(f"empty split: {split}")
        frac = sum(s["label"] for s in rows) / len(rows) if rows else 0.5
        if len(rows) >= 30:
            # Statistically meaningful size: hold the strict band.
            if not 0.44 <= frac <= 0.56:
                raise ValueError(f"split {split} imbalanced: attack fraction {frac:.3f}")
        elif rows and frac in (0.0, 1.0):
            # Tiny splits (reduced scales quantize per-axis holdouts to one
            # row each): both classes must at least be present.
            raise ValueError(f"split {split} single-class: attack fraction {frac:.3f}")
    sanity = [s for s in samples if s["sanity"]]
    if any(s["split"] != "train" for s in sanity):
        raise ValueError("sanity rows must stay in train")
    for s in sanity:
        # Layer 1 is a pure byte-flip flag (1.0 for ANY change, benign
        # included), so the sanity invariant lives in content layers 2-8:
        # a total takeover must scream there, a quiet bump must not.
        content_peak = max(s["features"][1:])
        if s["label"] == 1 and content_peak < 0.85:
            raise ValueError(f"sanity attack too weak: {s['id']} content-layer peak {content_peak}")
        if s["label"] == 0 and content_peak > 0.35:
            raise ValueError(f"sanity benign too loud: {s['id']} content-layer peak {content_peak}")
    # Distinct inputs may legitimately MEASURE identically: the 8-dim layer
    # space is coarse, so e.g. every single-domain cloaking takeover collapses
    # to [0,...,1.0,0]. That is feature-space physics, not sample duplication
    # (input uniqueness is enforced above via fingerprints) — record it.
    dups = cross_split_feature_duplicates(samples)
    dist, aid, bid = nearest_cross_split_distance(samples)
    langs_by_label = {
        label: {s["language"] for s in samples if s["label"] == label} for label in (0, 1)
    }
    for label, seen_langs in langs_by_label.items():
        missing = set(LANGS) - seen_langs
        if missing:
            raise ValueError(f"label {label} missing languages: {sorted(missing)}")
    evidence = {
        "unique_input_fingerprints": True,
        "cross_split_exact_feature_duplicates": len(dups),
        "cross_split_exact_feature_duplicate_examples": [list(p) for p in dups[:5]],
        "nearest_cross_split_linf_distance": round(dist, 4),
        "nearest_cross_split_pair": [aid, bid],
        "languages_by_label": {str(k): sorted(v) for k, v in langs_by_label.items()},
    }
    return evidence


META_NOTES = [
    "Feature vectors are measured by running the real pipeline (run_detection) over "
    "procedurally crafted page pairs; labels are generative ground truth.",
    "Attack payload strings are sampled mechanically from the production regex tables "
    "(signatures._STRONG/_MEDIUM/_WEAK/_PROF, semantics._AGGRESSION/_TOPICS); benign text "
    "comes from faker localized lorem providers.",
    "sig_leet spans the full substitution algebra at seeded per-character probability, "
    "so both currently-detected and currently-missed leet forms appear naturally.",
    "Class balance is exact by construction; stratification is axis x language; splits are "
    "~70/15/15 within each axis with disjoint membership; sanity rows stay in train.",
    "Input-level uniqueness is hard-enforced (sha256 fingerprints of every page pair); "
    "distinct inputs may still MEASURE identically where the coarse 8-dim feature space "
    "saturates (e.g. any full cloaking takeover -> [0,...,1.0,0]); the count of such "
    "cross-split feature collisions is recorded in leakage_evidence, not treated as leakage.",
    "Regeneration requires the pinned dev dependencies (faker) and the local MiniLM cache; "
    "HF_HUB_OFFLINE=1 is enforced so generation never touches the network.",
]


def build(
    scale: str = "full", out_path: Path = ARTIFACT_PATH, embedder_required: bool = True
) -> Path:
    from worker.detection.semantics import embed_text

    probe = embed_text("wardress fusion dataset embedder probe")
    if probe is None:
        if embedder_required:
            raise RuntimeError(
                "MiniLM embeddings unavailable — refusing to generate a silently-degraded "
                "dataset. Load the sentence-transformers cache first or pass "
                "embedder_required=False for smoke builds."
            )
        embedder_meta = {
            "model": "sentence-transformers/all-MiniLM-L6-v2",
            "mode": "unavailable-stub",
        }
    else:
        embedder_meta = {
            "model": "sentence-transformers/all-MiniLM-L6-v2",
            "mode": "real-local-cache",
        }

    Faker.seed(SEED)
    # Cached per-locale generators keep advancing state between builds;
    # reseed each so repeated builds in one process stay byte-identical.
    for cached in _FAKERS.values():
        cached.seed_instance(SEED)
    shrink = 0.12 if scale == "smoke" else 1.0

    def plan(counts: dict[str, int]) -> dict[str, int]:
        return {axis: max(2, round(n * shrink)) for axis, n in counts.items()}

    attack_plan = plan(ATTACK_AXES)
    benign_plan = plan(BENIGN_AXES)

    def rebalance_to_equal(plan_a: dict[str, int], plan_b: dict[str, int]) -> None:
        """Independent per-axis rounding can break exact class balance at
        reduced scales; grow the smaller class's largest axes (sorted,
        deterministic cycling) until totals match. Full scale is already
        exactly balanced, so this is a no-op there."""
        diff = sum(plan_a.values()) - sum(plan_b.values())
        target, step = (plan_b, 1) if diff > 0 else (plan_a, -1)
        axes_sorted = sorted(target)
        k = 0
        while diff != 0:
            axis = axes_sorted[k % len(axes_sorted)]
            target[axis] += 1
            diff -= step
            k += 1
            if k > 10000:
                raise RuntimeError("rebalance did not converge")

    if sum(attack_plan.values()) != sum(benign_plan.values()):
        rebalance_to_equal(attack_plan, benign_plan)

    samples: list[dict] = []

    def generate(table: dict[str, int], label: int, plan_map: dict[str, int]) -> None:
        nonlocal done
        # Language cycles per axis, staggered by the axis's sorted position:
        # at full scale every axis still covers every allowed language, and
        # at reduced scales coverage persists across axes (per-axis cycling
        # alone would never reach the later languages).
        for axis_pos, axis in enumerate(sorted(table)):
            n = plan_map[axis]
            allowed = LANGS if axis != "nonnative_editorial" else ("ar", "ru", "zh")
            offset = axis_pos % len(allowed)
            for idx in range(n):
                lang = allowed[(idx + offset) % len(allowed)]
                samples.append(measure_sample(axis, label, idx, lang))
                done += 1
                if done % 50 == 0:
                    print(f"  generated {done} samples...", flush=True)

    total = sum(attack_plan.values()) + sum(benign_plan.values()) + sum(SANITY_AXES.values())
    print(f"Generating fusion dataset (scale={scale}, ~{total} samples)...", flush=True)
    done = 0
    generate(ATTACK_AXES, 1, attack_plan)
    generate(BENIGN_AXES, 0, benign_plan)
    for k in range(SANITY_AXES["sanity_attack_takeover"]):
        samples.append(build_sanity_takeover(k))
    for k in range(SANITY_AXES["sanity_benign_identical"]):
        samples.append(build_sanity_identical(k))
    for k in range(SANITY_AXES["sanity_benign_quiet"]):
        samples.append(build_sanity_quiet(k))

    assign_splits(samples)
    leakage_evidence = validate(samples)

    by_axis: dict[str, int] = {}
    by_split_label: dict[str, dict[str, int]] = {}
    by_language: dict[str, int] = {}
    for s in samples:
        by_axis[s["axis"]] = by_axis.get(s["axis"], 0) + 1
        bucket = by_split_label.setdefault(s["split"], {"attack": 0, "benign": 0})
        bucket["attack" if s["label"] == 1 else "benign"] += 1
        by_language[s["language"]] = by_language.get(s["language"], 0) + 1

    artifact = {
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "seed": SEED,
            "scale": scale,
            "feature_keys": list(FEATURE_KEYS),
            "embedder": embedder_meta,
            "counts": {
                "total": len(samples),
                "attack": sum(s["label"] for s in samples),
                "benign": sum(1 for s in samples if s["label"] == 0),
                "sanity": sum(1 for s in samples if s["sanity"]),
                "by_axis": dict(sorted(by_axis.items())),
                "by_split_label": dict(sorted(by_split_label.items())),
                "by_language": dict(sorted(by_language.items())),
            },
            "leakage_evidence": leakage_evidence,
            "notes": META_NOTES,
            "generator": "backend/tools/build_fusion_dataset.py",
        },
        "samples": samples,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp_path, out_path)
    print(f"Wrote {len(samples)} samples -> {out_path}", flush=True)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scale", choices=("smoke", "full"), default="full")
    parser.add_argument("--out", type=Path, default=ARTIFACT_PATH)
    args = parser.parse_args()
    build(scale=args.scale, out_path=args.out, embedder_required=True)


if __name__ == "__main__":
    main()
