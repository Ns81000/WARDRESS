"""Stealth configuration for Playwright captures (PROMPT-002 Phase 1).

Wardress's capture used to announce itself (`Wardress/0.1 SiteMonitor` UA,
stock headless Chromium), which WAFs and bot-detection systems flag
instantly — the capture never saw the site a real visitor sees. This
module centralizes everything the capture does to look like a real
browser:

- `BROWSER_LAUNCH_ARGS` — Chromium launch args (blink automation marker).
- `CAPTURE_USER_AGENT` — a realistic current-Chrome UA for the capture
  context. The probe (worker/probe.py) keeps its own UA rotation; layer 7
  deliberately compares raw-UA responses against the Playwright render,
  so the probe is intentionally NOT stealthed.
- `apply_stealth(context)` — applies `playwright-stealth`'s standard
  evasion set plus supplementary init scripts for gaps the library does
  not cover (ChromeDriver `cdc_*` properties, Permissions.query
  notifications, plugins/mimeTypes normalization when the library patch
  did not land).

Graceful degradation: if `playwright-stealth` is not installed (dev
environments), `apply_stealth` logs a warning and returns — the capture
still works, just unhardened.

SSRF contract (rule 11): stealth patches are init scripts on the browser
context. They never touch network routing; the caller must install the
SSRF route guard (`fetcher._make_ssrf_route_guard`) AFTER stealth so the
guard intercepts every subresource request the (stealthed) page makes.
Nothing here may weaken or bypass `app/ssrf.py`.
"""

import logging

from playwright.async_api import BrowserContext

logger = logging.getLogger(__name__)

try:
    from playwright_stealth import Stealth
except ImportError:  # pragma: no cover - exercised via monkeypatch in tests
    Stealth = None

# --- Browser launch / context shape (shared by every capture) -------------

BROWSER_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
]

# Realistic current-Chrome desktop UA (current stable at time of writing;
# verified against endoflife.date 2026-09). Deliberately NOT branded with
# Wardress — a self-identifying monitor UA is a bot-detection gift.
CAPTURE_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
)

CONTEXT_LOCALE = "en-US"
CONTEXT_TIMEZONE_ID = "America/New_York"
CONTEXT_COLOR_SCHEME = "light"
CONTEXT_VIEWPORT = {"width": 1366, "height": 768}  # standard laptop resolution

# --- Supplementary init script --------------------------------------------
#
# playwright-stealth covers the common vectors (navigator.webdriver,
# chrome.runtime, codecs, WebGL vendor, plugins, languages...). These
# patches close the gaps that remain, each individually guarded so a
# future browser change can only degrade the patch, never the page:
#
# 1. `cdc_*` — ChromeDriver leaks properties matching /$?cdc_/ on window;
#    some detectors probe for exactly that.
# 2. Permissions.query — a stock headless context answers "denied" for
#    notifications in an automation-telltale way; real Chrome answers with
#    the actual permission state (unset = "prompt" for a fresh profile).
# 3. plugins/mimeTypes — normalize ONLY if the array is empty (the shape a
#    bare headless context reports); if playwright-stealth's patch landed,
#    this is a no-op, avoiding any double-definition conflict.
_SUPPLEMENTARY_INIT_JS = """\
(() => {
  // 0. navigator.webdriver: playwright-stealth only flips it to false;
  //    remove it entirely (undefined + not own property), matching real
  //    Chrome and defeating typeof / 'in' probes alike.
  try {
    delete Object.getPrototypeOf(navigator).webdriver;
  } catch (e) { /* non-configurable */ }
  try {
    Object.defineProperty(navigator, 'webdriver', {
      get: () => undefined,
      configurable: true,
    });
  } catch (e) { /* never break the page */ }

  // 1. Strip ChromeDriver's window.cdc_* / $cdc_* properties.
  try {
    for (const key of Object.getOwnPropertyNames(window)) {
      if (/^([a-zA-Z])*cdc_/.test(key)) {
        try { delete window[key]; } catch (e) { /* non-configurable */ }
      }
    }
  } catch (e) { /* never break the page */ }

  // 2. Permissions.query: notifications -> the real permission state
  //    ("prompt" on a fresh profile), matching a normal Chrome profile.
  try {
    if (window.Permissions && window.Permissions.prototype) {
      const originalQuery = window.Permissions.prototype.query;
      window.Permissions.prototype.query = function (parameters) {
        if (parameters && parameters.name === 'notifications') {
          const state = (typeof Notification !== 'undefined')
            ? Notification.permission
            : 'prompt';
          return Promise.resolve({ state: state, onchange: null });
        }
        return originalQuery.call(this, parameters);
      };
    }
  } catch (e) { /* never break the page */ }

  // 3. plugins/mimeTypes: only normalize when still empty (bare headless
  //    shape). A populated array from the stealth library is left alone.
  try {
    if (navigator.plugins && navigator.plugins.length === 0) {
      const mimeType = Object.create(MimeType.prototype, {
        type: { get: () => 'application/pdf' },
        suffixes: { get: () => 'pdf' },
        description: { get: () => 'Portable Document Format' },
      });
      const plugin = Object.create(Plugin.prototype, {
        name: { get: () => 'Chrome PDF Viewer' },
        description: { get: () => 'Portable Document Format' },
        filename: { get: () => 'internal-pdf-viewer' },
        length: { get: () => 1 },
      });
      plugin[0] = mimeType;
      mimeType.enabledPlugin = plugin;
      const pluginArray = Object.create(PluginArray.prototype);
      pluginArray[0] = plugin;
      Object.defineProperty(pluginArray, 'length', { get: () => 1 });
      Object.defineProperty(navigator, 'plugins', {
        get: () => pluginArray,
        configurable: true,
      });
      const mimeTypeArray = Object.create(MimeTypeArray.prototype);
      mimeTypeArray[0] = mimeType;
      Object.defineProperty(mimeTypeArray, 'length', { get: () => 1 });
      Object.defineProperty(navigator, 'mimeTypes', {
        get: () => mimeTypeArray,
        configurable: true,
      });
    }
  } catch (e) { /* never break the page */ }
})();
"""


async def apply_stealth(context: BrowserContext) -> None:
    """Harden a Playwright browser context against naive bot detection.

    Applies playwright-stealth's evasion set (with navigator.languages
    pinned to the capture context's locale) plus the supplementary init
    scripts above. Must be called BEFORE `context.new_page()` and before
    the SSRF route guard is installed — init scripts apply to pages
    created afterwards, and the guard must be the last word on every
    request. Fails open (log + no-op) when playwright-stealth is absent.
    """
    if Stealth is None:
        logger.warning(
            "playwright-stealth is not installed; capture continues "
            "WITHOUT stealth patches (install the 'playwright-stealth' "
            "package for anti-bot hardening)"
        )
        return

    stealth = Stealth(navigator_languages_override=(CONTEXT_LOCALE, "en"))
    await stealth.apply_stealth_async(context)
    await context.add_init_script(_SUPPLEMENTARY_INIT_JS)
    logger.debug("Stealth patches applied to capture context")
