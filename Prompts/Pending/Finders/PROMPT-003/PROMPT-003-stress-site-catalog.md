# PROMPT-003 — Stress-Test Site Catalog (companion to the main audit spec)

This file is consumed by Audit Phases 5A, 5B, 5C (and referenced by 6/7/8) of `PROMPT-003-capture-detection-audit-and-stress-hardening.md`. It is strictly **additive** to PROMPT-002 Phase 13's original 74-site validation list — do not reuse those sites here; these are new representatives chosen to be broader (Tier A) and harder (Tiers B/C) than anything PROMPT-002 tested.

## Verification protocol (read before running anything)

Bot-protection vendor deployments, page structures, and even whether a site is still live all drift over time. Before treating any site below as a member of the category it's listed under:

1. **Confirm liveness** — the site responds and the page you're about to capture is the one described.
2. **Confirm the category still applies** — a site listed under "Akamai Bot Manager" today may have switched vendors; a quick check of response headers / challenge page fingerprints / a vendor-detection service is enough. If it's drifted to a different category, log that drift and re-file it rather than silently treating the run as invalid.
3. **Public pages only** — every site below should be tested via its public, unauthenticated homepage or an equivalent public page. Do not log in, do not submit forms, do not create accounts. This matches Wardress's own operating model (read-only, low-frequency monitoring of public-facing pages) and keeps testing within reasonable, non-abusive bounds.
4. **Timestamp every verification** — record the date you confirmed category/liveness alongside the result, since a later audit phase (or a future PROMPT-003 re-run per §8.3 of the main file) needs to know how stale the categorization was when you tested.
5. **Repeatability (Rule 18 of the main file)** — every site gets a minimum of three passes, ideally not all in the same hour, with per-pass outcome and variance recorded.
6. **No aggregate close-out (Rule 19 of the main file)** — every failing site gets its own investigated root cause and an explicit Fix-candidate / Accepted-risk disposition, never folded into a bare percentage.

---

## TIER A — Broad Real-World Baseline (Audit Phase 5A)

The user's own curated, currently-live catalog — element-rich, actively-maintained, real-world sites spanning news, entertainment, government, reference, and developer ecosystems. This tier exists to catch surprises at breadth that a smaller, purpose-picked validation set can miss simply by not including enough ordinary, popular, high-traffic sites.

### Top 20 — mixed selection, good starting subset
```
https://quietude-one.vercel.app/
https://www.bbc.co.uk/news
https://www.bbc.com/news
https://hackaday.com/
https://www.aajtak.in/
https://www.ndtv.com/
https://www.thehindu.com/
https://indianexpress.com/
https://www.hindustantimes.com/
https://www.indiatoday.in/
https://www.reuters.com/
https://www.smashingmagazine.com/
https://en.wikipedia.org/wiki/Main_Page
https://www.nasa.gov/
https://www.gov.uk/
https://www.mozilla.org/
https://developer.mozilla.org/
https://www.python.org/
https://www.rust-lang.org/
https://go.dev/
https://stackoverflow.com/
```

### Indian News
```
https://www.aajtak.in/
https://www.ndtv.com/
https://www.thehindu.com/
https://indianexpress.com/
https://www.hindustantimes.com/
https://www.indiatoday.in/
https://www.news18.com/
https://www.abplive.com/
https://www.zeenews.india.com/
https://www.livemint.com/
https://www.moneycontrol.com/
https://www.businesstoday.in/
```

### Indian / Bollywood Entertainment
```
https://www.bollywoodhungama.com/
https://www.filmfare.com/
https://www.indiaforums.com/
https://www.pinkvilla.com/
https://www.koimoi.com/
https://www.hindustantimes.com/entertainment
https://indianexpress.com/section/entertainment/
https://www.ndtv.com/entertainment
https://www.aajtak.in/entertainment
```

### International News (modern, element-rich)
```
https://www.bbc.co.uk/news
https://www.bbc.com/news
https://news.sky.com/
https://www.reuters.com/
https://lite.cnn.com/
https://www.npr.org/
https://www.cbc.ca/
https://www.techdirt.com/
https://hackaday.com/
https://www.theguardian.com/
https://www.aljazeera.com/
```

### Government / Institutional
```
https://www.gov.uk/
https://www.nhs.uk/
https://www.usa.gov/
https://www.whitehouse.gov/
https://www.nasa.gov/
https://www.noaa.gov/
https://www.cdc.gov/
https://www.who.int/
https://www.un.org/
https://www.europa.eu/
```

### Reference & Knowledge
```
https://en.wikipedia.org/
https://www.wikidata.org/
https://commons.wikimedia.org/
https://www.gutenberg.org/
https://www.archive.org/
https://arxiv.org/
```

### Tech / Developer (modern looking)
```
https://www.mozilla.org/
https://developer.mozilla.org/
https://www.w3.org/
https://www.python.org/
https://www.rust-lang.org/
https://go.dev/
https://nodejs.org/
https://www.php.net/
https://stackoverflow.com/
https://github.com/
https://gitlab.com/
https://www.ietf.org/
https://tools.ietf.org/
https://www.rfc-editor.org/
https://www.smashingmagazine.com/
```

### Other solid general sites
```
https://duckduckgo.com/
https://www.imdb.com/
https://www.goodreads.com/
https://www.openstreetmap.org/
```

**Note:** `www.rfc-editor.org` was already in PROMPT-002 Phase 13's static-site set (logged there as "correctly-detected block"). If it recurs here, treat the earlier disposition as a prior data point to compare against, not a reason to skip re-testing it.

---

## TIER B — Advanced Bot-Protection & Hard Categories (Audit Phase 5B)

These target the exact three categories PROMPT-002 Phase 13 left below its 90% bar (Cloudflare, Lazy-load, E-commerce) with *harder* representatives, plus bot-protection vendors Phase 13 never attempted at all. **Verify each site's current vendor before testing (see Verification protocol above) — this list reflects vendor-detection research current as of this audit's authoring and will drift.**

### Akamai Bot Manager (not attempted by PROMPT-002 at all)
Sites independently identified as Akamai Bot Manager customers/traffic:
```
https://www.microsoft.com/
https://www.ibm.com/
https://www.ebay.com/
https://www.washingtonpost.com/
https://www.usps.com/
https://weather.com/
https://www.dell.com/
https://www.bestbuy.com/
https://www.nbcnews.com/
https://www.accuweather.com/
https://www.airbnb.com/
https://www.godaddy.com/
```

### DataDome
DataDome's public customer base skews toward e-commerce, travel, and classifieds and is harder to pin to specific always-current homepages than Akamai's — treat every entry here as **higher-uncertainty, verify-before-use**:
```
https://www.leboncoin.fr/
https://www.sncf-connect.com/
https://www.footlocker.com/
```

### PerimeterX / HUMAN Defense Platform
Historically associated with retail/marketplace bot defense (verify current vendor before use):
```
https://www.zillow.com/
https://stockx.com/
https://www.yelp.com/
```

### AWS WAF (challenge-action / CAPTCHA-capable)
Large AWS-hosted retail/media/finance properties commonly sit behind AWS WAF with bot-control managed rules and challenge actions (verify current configuration before use):
```
https://www.target.com/
https://www.chase.com/
https://www.hulu.com/
```

### Cloudflare Enterprise / Turnstile (beyond the free JS-challenge tier PROMPT-002 already tested)
PROMPT-002 Phase 13 tested Cloudflare's free-tier auto-solving JS challenge (5/6, discord.com excluded for an unrelated 10MB HTML guard). This sub-tier specifically targets **Turnstile / enterprise-tier Cloudflare**, which does not always auto-solve the way the free tier does:
```
https://www.kraken.com/
https://www.npmjs.com/
https://dash.cloudflare.com/
```

### Harder e-commerce (large catalog, aggressive WAF, geofencing-aware)
```
https://www.walmart.com/
https://www.etsy.com/
https://www.ebay.co.uk/
https://www.aliexpress.com/
```

### Harder lazy-load (multiple libraries, infinite API-gated scroll, not just image lazy-load)
```
https://unsplash.com/
https://www.pexels.com/
https://500px.com/
```

---

## TIER C — Exotic & Edge Categories (Audit Phase 5C)

Categories PROMPT-002 never attempted at all — chosen specifically to pressure-test assumptions the capture pipeline makes about "settled," "loaded," and "stable" content.

### WebSocket / live-push driven content (settle is inherently fuzzy — content never truly stops changing)
```
https://www.tradingview.com/chart/
https://www.espn.com/nba/scoreboard
https://flightaware.com/live/
```

### PWA / Service-Worker sites (may serve cached content on repeat visits)
```
https://open.spotify.com/
https://www.pinterest.com/
https://web.whatsapp.com/
```

### Extremely large pages (multi-megabyte DOM, thousands of images, very tall archives)
```
https://en.wikipedia.org/wiki/List_of_largest_selling_pharmaceutical_products
https://www.nasa.gov/image-of-the-day/
https://apnews.com/hub/ap-top-news
```

### Slow / high-latency origins (pressure-test timeout budgets against real-world latency, not local-network conditions)
```
https://www.india.gov.in/
https://www.gutenberg.org/browse/scores/top
```

### Auth-adjacent / soft-blocked pages (full 200-status "please verify"/paywall pages, not a clean 403 — must not be silently treated as meaningful content)
```
https://www.nytimes.com/
https://www.wsj.com/
```

### Infinite-scroll feeds (new content appended on scroll, not just lazy-loaded images below the fold)
```
https://www.reddit.com/
https://www.instagram.com/nasa/
```

### Heavy client-side hydration frameworks (skeleton-then-replace-nearly-the-entire-DOM patterns)
```
https://linear.app/
https://vercel.com/
https://www.notion.so/
```

### Deep RTL / mixed-script (beyond PROMPT-002's 7/7 already-passing non-Latin set)
```
https://www.aljazeera.net/
https://www.bbc.com/arabic
https://www.haaretz.co.il/
```

---

## How to extend this catalog

If Audit Phase 5A/5B/5C finds a category is thin, under-represented, or a listed site has drifted out of its category, **add to this file, don't just note it in the log** — this catalog is meant to accumulate across audit cycles (including any future re-run of PROMPT-003 per its §8.3), the same way PROMPT-002's own site list was a living artifact of that effort. Append new entries under the correct tier/category heading, keep the verification-protocol discipline, and note the date added.
