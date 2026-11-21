"""Adapt the copied Deep Research workspace client (public/xyz) to this build.

public/xyz is a file-for-file copy of the workspace's built client. Run once after copying it:

    python3 dev/patch_workspace_copy.py

It changes only what this build needs and nothing else:
  * the page's base path (/xyz/), no service worker, the Callisto title
  * the name people see: the lettering and every sentence say Callisto
  * the ground: the app's navy (#0e1420) in place of pure black
  * the side panel's links: Home and Reports (this build has no Query or Screener page)
  * US only: the question box's hint, and every sentence that named the Japanese filing system,
    clock or market data
The script refuses to run twice or on a copy it does not recognise (every edit must match exactly).
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent / "public" / "xyz"
NAVY = "14 20 32"

# the CALLISTO lettering, in the construction of the original lettering: filled letters as one
# path, centre-line letters (C, S, O) as one stroked path
FILLED = ("m98.75 113 29-46h9l29 46h-9l-24.5-38-24.5 38z" "M206.75 67h8v38h38v8H206.75z" "M296.75 67h8v38h38v8H296.75z"
          "M386.75 67h8v46h-8z" "M543.25 67h56v8H575.25v38h-8V75H543.25z")
STROKED = ("M57.75 71H12.75q-9 0-9 9v20q0 9 9 9h45" "M495.5 71H452.5q-10 0-10 9.5q0 9.5 10 9.5h33q10 0 10 9.5q0 9.5-10 9.5H442.5"
           "M657 71h33q10 0 10 9v20q0 9-10 9h-33q-10 0-10-9V80q0-9 10-9Z")
LETTERING = [
    ("M58 67h8v46h-8z", FILLED),                                                        # I  -> A L L I T
    ("M110 113V67h8l46 37V67h8v46h-8l-46-37v37z", ""),                                  # N
    ("M216 67h44q14 0 14 13v20q0 13-14 13h-44zm8 7v32h36q7 0 7-7V81q0-7-7-7z", ""),     # D
    ("m315 113 29-46h9l29 46h-9l-24.5-38-24.5 38z", ""),                                # A
    ("M481 71h-45q-9 0-9 9v20q0 9 9 9h33q9 0 9-9v-8h-23", STROKED),                     # G  -> C S O
    ("M540 71h33q10 0 10 9v20q0 9-10 9h-33q-10 0-10-9V80q0-9 10-9Z", ""),               # O
]
VIEWBOX = ("50.375 58 544 64", "-7.625 58 719 64")   # centred on the visible ink, same margins

STYLE = """<style id="callisto-build">
      /* this build: the app's navy ground in place of pure black */
      html:root.dark, html:root.dark.high-contrast {
        --presentation: %(n)s !important; --header-primary: %(n)s !important; --surface-primary: %(n)s !important; --surface-primary-alt: %(n)s !important;
        --surface-primary-contrast: %(n)s !important; --surface-secondary: %(n)s !important; --surface-secondary-alt: %(n)s !important;
        --surface-tertiary: %(n)s !important; --surface-tertiary-alt: %(n)s !important; --surface-dialog: %(n)s !important; --surface-overlay: %(n)s !important;
        --surface-chat: %(n)s !important; --surface-code: %(n)s !important; --chart-widget-surface: %(n)s !important; --status-success-subtle: %(n)s !important;
        --status-info-subtle: %(n)s !important; --status-warning-subtle: %(n)s !important; --status-error-subtle: %(n)s !important;
        --status-neutral-subtle: %(n)s !important;
      }
      html:root.dark, html:root.dark body { background-color: #0e1420 !important; }
      /* the longer word keeps the original letter height: 544 -> 719 units wide */
      div:has(> span > svg[data-testid="indago-logo"]) { width: 233px !important; }
      @media (min-width: 640px) { div:has(> span > svg[data-testid="indago-logo"]) { width: 254px !important; } }
      @media (max-height: 600px) { div:has(> span > svg[data-testid="indago-logo"]) { width: 169px !important; } }
      /* the planet's night side melts into the navy ground, as it did into black */
      figure[data-testid="mars-horizon"] { mix-blend-mode: lighten; }
      /* this build has no Screener page */
      a[href="/#/ScreenerMode"] { display: none !important; }
    </style>
  </head>""" % {"n": NAVY}


def once(text, old, new, what):
    if text.count(old) != 1:
        sys.exit(f"patch_workspace_copy: expected exactly one {what!r}, found {text.count(old)}")
    return text.replace(old, new)

# US only: what the sentences call the filing system, the clock and the market data
US_SENTENCES = [
    ("Japanese quotes located verbatim in the filing", "Quotes located verbatim in the filing"),
    ("Annual securities report filed on EDINET (Japan's 10-K)", "Annual report filed with the SEC (Form 10-K)"),
    ("Company & market data · JPX", "Company & market data"),
    ("com_ui_indago_trace_kind_jquants:`JPX`", "com_ui_indago_trace_kind_jquants:`Market data`"),
    ("com_ui_indago_trace_kind_tdnet:`TDnet`", "com_ui_indago_trace_kind_tdnet:`Press release`"),
]
US_WORDS = [(r"\bEDINET\b", "SEC EDGAR"), (r"\bJST\b", "ET")]
JAPAN_WORDS = r"Japan|Tokyo|TSE\b|EDINET|J-Quants|JPX|TDnet|\byen\b|¥|\bJST\b|TOPIX|Nikkei"


def us_only(js):
    """Rewrite the texts table's sentences for US listed companies; returns (js, how many changed)."""
    for old, new in US_SENTENCES:
        js = once(js, old, new, "US sentence")
    changed = 0
    def sentence(match):
        nonlocal changed
        key, value = match.group(1), match.group(2)
        fixed = value
        for pattern, word in US_WORDS:
            fixed = re.sub(pattern, word, fixed)
        if fixed != value:
            changed += 1
        return f"{key}:{fixed}"
    js = re.sub(r"(com_[a-z0-9_]+):(`(?:[^`\\]|\\.)*`)", sentence, js)
    left = [m.group(1) for m in re.finditer(r"(com_[a-z0-9_]+):(`(?:[^`\\]|\\.)*`)", js) if re.search(JAPAN_WORDS, m.group(2))]
    if left:
        sys.exit(f"patch_workspace_copy: sentences still Japan-specific: {left[:5]}")
    return js, changed


def main():
    page = ROOT / "index.html"
    html = page.read_text()
    if 'id="callisto-build"' in html:
        sys.exit("patch_workspace_copy: this copy is already adapted")
    if '<base href="/" />' in html:                                   # a fresh copy
        html = once(html, '<base href="/" />', '<base href="/xyz/" />', "base")
        html, n = re.subn(r'<link rel="manifest"[^>]*>', "", html)
        html, m = re.subn(r'<script id="vite-plugin-pwa:register-sw"[^>]*></script>', "", html)
        if (n, m) != (1, 1):
            sys.exit("patch_workspace_copy: service worker tags not found")
        html = once(html, "<title>Indago — Deep Research</title>", "<title>Callisto — Deep Research</title>", "title")
        html = once(html, 'content="Indago Deep Research: verified, multi-source research reports on Japanese listed companies"',
                    'content="Callisto Deep Research"', "description")
    html = once(html, "if (theme === 'high-contrast-dark') {\n        backgroundColor = '#000000';",
                "if (theme === 'high-contrast-dark') {\n        backgroundColor = '#0e1420';", "loading ground")
    html = once(html, "} else if (theme === 'dark') {\n        backgroundColor = '#0d0d0d';",
                "} else if (theme === 'dark') {\n        backgroundColor = '#0e1420';", "loading ground (dark)")
    html = once(html, "</head>", STYLE.split("\n", 1)[0] + "\n" + STYLE.split("\n", 1)[1], "head end")
    page.write_text(html)

    main_js = next(p for p in (ROOT / "assets").glob("index.*.js") if "com_ui_indago_panel_search" in p.read_text(errors="ignore"))
    js = main_js.read_text()
    for old, new in LETTERING:
        js = once(js, old, new, "lettering path")
    if js.count(VIEWBOX[0]) != 2:
        sys.exit("patch_workspace_copy: lettering view box not found twice")
    js = js.replace(VIEWBOX[0], VIEWBOX[1])
    js = once(js, "t(`com_ui_logo`,{0:`Indago`})", "t(`com_ui_logo`,{0:`Callisto`})", "logo label")
    # sentences only: the texts table's values. The endpoint's own id (`Indago`) is code and stays.
    renamed = 0
    def sentence(match):
        nonlocal renamed
        key, value = match.group(1), match.group(2)
        if "Indago" in value:
            renamed += 1
            value = value.replace("Indago", "Callisto")
        return f"{key}:{value}"
    js = re.sub(r"(com_[a-z0-9_]+):(`(?:[^`\\]|\\.)*`)", sentence, js)
    if renamed < 30:
        sys.exit(f"patch_workspace_copy: only {renamed} sentences renamed")
    js = once(js, "com_ui_indago_panel_nav_query:`Query`", "com_ui_indago_panel_nav_query:`Reports`", "side link label")
    js = once(js, "com_ui_indago_placeholder_query:`Ask about a Japanese listed company: filings, financials, prices, news`",
              "com_ui_indago_placeholder_query:`Ask about a US listed company: filings, financials, prices, news`", "question box hint")
    js, us_changed = us_only(js)
    main_js.write_text(js)

    panel = next((ROOT / "assets").glob("DeepResearchPanel.*.js"))
    text = panel.read_text()
    text = once(text, "query:`/#/Query`", "query:`/#/Reports`", "side link address")
    panel.write_text(text)
    print(f"adapted: {page.name}, {main_js.name} ({renamed} sentences), {panel.name}")


if __name__ == "__main__":
    main()
