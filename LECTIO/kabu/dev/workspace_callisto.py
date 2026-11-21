"""The Deep Research workspace's landing planet: Jupiter's moon Callisto in place of Mars.

Run after dev/patch_workspace_copy.py, once:

    python3 dev/workspace_callisto.py                      # the edits (texture already in place)
    python3 dev/workspace_callisto.py --source mosaic.tif  # also rebuild the surface map first

The workspace client (public/xyz) draws its planet from one longitude/latitude brightness map and
tints the glyphs in its last drawing pass. This script
  * builds that map for Callisto from the USGS Voyager/Galileo global mosaic (public domain),
  * points the client at it (the request and the page's early fetch),
  * replaces the copper tints with Callisto's: dark brown ground, tan plains, pale pink-white craters,
  * makes the planet assemble itself out of scrambled glyphs, as on the prototype moon pages,
    once the page's opening screen has gone,
  * rewrites the planet's description and the credits page, and removes the Mars maps.
Every edit must match exactly once; the script refuses a copy it does not recognise.
"""
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent / "public" / "xyz"
OLD_MAP, NEW_MAP = "assets/mars/mars-terrain-4k.webp", "assets/callisto/callisto-terrain-4k.webp"

# (what, old, new): the last drawing pass's tints, and the words
JS_EDITS = [
    ("map request", OLD_MAP, NEW_MAP),
    ("ground to plains", "mix(vec3(.30,.055,.015),vec3(.92,.265,.070),smoothstep(.025,.50,tone))",
     "mix(vec3(.20,.135,.105),vec3(.60,.455,.375),smoothstep(.025,.50,tone))"),
    ("plains to ice", "mix(color,vec3(1.0,.47,.18),smoothstep(.46,.92,tone))",
     "mix(color,vec3(.93,.82,.75),smoothstep(.46,.92,tone))"),
    ("crater floors", "mix(color,vec3(1.0,.69,.37),smoothstep(.82,.99,tone)*.18)",
     "mix(color,vec3(1.0,.965,.95),smoothstep(.82,.99,tone)*.6)"),
    ("limb light", "mix(color,vec3(1.0,.80,.48),rim*.82)", "mix(color,vec3(1.0,.93,.87),rim*.82)"),
    ("night ink", "vec3 dark = vec3(.0015,.00065,.0003)*tone;", "vec3 dark = vec3(.0012,.0010,.0009)*tone;"),
    ("description", "com_ui_mars_description:`A detailed, copper-colored ASCII Mars above the message box.`",
     "com_ui_mars_description:`A detailed ASCII rendering of Jupiter's moon Callisto above the message box.`"),
]
HTML_EDITS = [
    ("credits link", '<link rel="license" href="assets/mars/credits.html" />', '<link rel="license" href="assets/callisto/credits.html" />'),
    ("early fetch", "link.href = '%s';" % OLD_MAP, "link.href = '%s';" % NEW_MAP),
]
CREDITS = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Callisto artwork credits</title>
  </head>
  <body>
    <h1>Callisto artwork credits</h1>
    <p>
      Callisto surface map: the Voyager / Galileo SSI global mosaic (1 km) by the
      <a href="https://astrogeology.usgs.gov/">USGS Astrogeology Science Center</a>, public domain.
    </p>
    <p>
      The mosaic was resampled to a 4K brightness map, its no-data gaps were filled with terrain
      from the opposite hemisphere, and its contrast was balanced for print. The renderer maps the
      image onto a rotating sphere, enhances terrain contrast and lighting, and renders it as ASCII
      artwork.
    </p>
    <p><a href="../../">Back</a></p>
  </body>
</html>
"""


# The planet's arrival (owner 2026-11-22: "when I swap between the planets there is a transition
# ... have that transition here ... 1 for 1"): the glyph assembly of the prototype moon pages
# (TEST/moon.js), with its numbers. Each cell settles at 0.1 + 1.05 * (distance from the centre,
# in radii, at most 1.3) + 0.4 * (a per-cell random) seconds, so the moon assembles from the centre
# outwards; until then the cell shows a random character, re-drawn 16 times a second, on 55% of
# the cells, at 0.3-0.7 of its colour; for 0.4 s after settling it carries a white flash of 110/255.
# The whole arrival lasts 2 s (the client's own clock, ARRIVAL_MS).
ARRIVAL_FROM = "  if (uReveal < 1.0) {"
ARRIVAL_TO = "  // Premultiplied color and coverage emerge together"
ARRIVAL = """  if (uReveal < 1.0) {
    // Glyph assembly, as on the prototype moon pages (see dev/workspace_callisto.py).
    float t = uReveal*2.0;
    float h = fract(sin(dot(cell,vec2(127.1,311.7)))*43758.5453);
    float settle = .1+1.05*min(1.3,length(relative))+.4*h;
    if (t < settle) {
      float tick = floor(t*16.0);
      float hs = fract(sin(dot(cell+tick*vec2(17.0,31.0),vec2(269.5,183.3)))*43758.5453);
      if (hs > .45) {
        float scramble = 1.0+floor(fract(hs*9973.0)*94.0);
        printed = shadeInk(atlasInk(scramble,local,atlasDx,atlasDy),tone,relative)*(.3+.4*hs);
      } else {
        printed = vec3(0.0);
      }
    } else {
      printed += vec3(.43)*ink*max(0.0,1.0-(t-settle)/.4);
    }
  }
"""
ARRIVAL_MS_OLD, ARRIVAL_MS = "s,c=4200,l,u=!1,d=!0,f=!1,p=0,m,h=o.matches?c:0", "s,c=2000,l,u=!1,d=!0,f=!1,p=0,m,h=o.matches?c:0"
# The arrival waits until the page's opening screen has gone, so it is seen (the workspace loads
# underneath that screen): the planet's clock stands still while the hold says so.
CLOCK = "let t=!o.matches,r=m===void 0?0:Math.min(64,e-m);o.matches?h=c:"
CLOCK_HELD = "let t=!o.matches,r=m===void 0?0:Math.min(64,e-m);if(h<c&&window.__callistoHeld?.())r=0;o.matches?h=c:"
# The small CALLISTO lettering under an answer (owner 2026-11-22: "should be aligned ... the logo
# [is a] bit too much on the right"): its box was as wide as the landing's lettering, so the word
# sat centred in it, 37 px right of the answer's left edge. The box is now exactly as wide as the
# word at that height (16 px tall, 719:64), so the word starts on the answer's left edge.
FIT = """    <style id="callisto-fit">
      div.h-4.w-28:has(> span > svg[data-testid="indago-logo"]) { width: 180px !important; margin-left: 4px; }
    </style>
"""
HOLD_BEFORE = '    <meta name="theme-color"'
HOLD = """    <script>
      /* The planet's arrival waits while the embedding page still shows its opening screen. */
      window.__callistoHeld = function () {
        try {
          return window.parent !== window && !!window.parent.document.querySelector('.dr2-splash');
        } catch (e) {
          return false;
        }
      };
    </script>
"""


def once(text, old, new, what):
    if text.count(old) != 1:
        sys.exit(f"workspace_callisto: expected exactly one {what!r}, found {text.count(old)}")
    return text.replace(old, new)


def build_map(source):
    """USGS mosaic (any size, longitude 0 or 180 in the centre) -> 4096x2048 brightness map, lon 0 centred."""
    import numpy as np
    from PIL import Image, ImageFilter

    Image.MAX_IMAGE_PIXELS = None
    W, H = 4096, 2048
    raw = Image.open(source).convert("L").resize((W, H), Image.LANCZOS)
    a = np.asarray(raw).astype(np.float32)
    if "--center-180" in sys.argv:                       # bring longitude 0 to the centre
        a = np.roll(a, W // 2, axis=1)
    # no-data gaps (black): real terrain from the opposite hemisphere, feathered in
    donor = np.flipud(np.roll(a, W // 2, axis=1))
    hole = Image.fromarray(((a < 7) * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(18))
    hole = np.clip(np.asarray(hole).astype(np.float32) / 255.0 * 2.2, 0, 1)
    a = a * (1 - hole) + donor * hole
    # tone: the client expects a mid-grey ground (median ~.42) with headroom for the bright craters
    lo, hi = np.percentile(a, 0.8), np.percentile(a, 99.9)
    a = np.clip((a - lo) / (hi - lo), 0, 1)
    gamma = np.log(0.42) / np.log(max(float(np.median(a)), 1e-3))
    a = a ** gamma
    img = Image.fromarray((a * 255).astype(np.uint8)).filter(ImageFilter.UnsharpMask(radius=10, percent=45, threshold=0))
    out = ROOT / NEW_MAP
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.merge("RGB", (img, img, img)).save(out, "WEBP", quality=90, method=6)
    b = np.asarray(img).astype(np.float32) / 255.0
    print("map:", out.name, img.size, "percentiles 1/10/50/90/99:", [round(float(v), 2) for v in np.percentile(b, [1, 10, 50, 90, 99])])


def main():
    if "--source" in sys.argv:
        build_map(sys.argv[sys.argv.index("--source") + 1])
    if not (ROOT / NEW_MAP).exists():
        sys.exit("workspace_callisto: the Callisto map is missing; run with --source <mosaic>")

    main_js = next(p for p in (ROOT / "assets").glob("index.*.js") if "com_ui_mars_description" in p.read_text(errors="ignore"))
    page = ROOT / "index.html"
    js, html = main_js.read_text(), page.read_text()
    done = []

    if NEW_MAP not in js:                                             # Mars -> Callisto
        for what, old, new in JS_EDITS:
            js = once(js, old, new, what)
        for what, old, new in HTML_EDITS:
            html = once(html, old, new, what)
        (ROOT / "assets" / "callisto" / "credits.html").write_text(CREDITS)
        shutil.rmtree(ROOT / "assets" / "mars", ignore_errors=True)
        done.append("Callisto map and tints")

    start, end = js.find(ARRIVAL_FROM), js.find(ARRIVAL_TO)           # the arrival, whatever stood there
    if js.count(ARRIVAL_FROM) != 1 or js.count(ARRIVAL_TO) != 1 or end < start:
        sys.exit("workspace_callisto: the planet's arrival code was not recognised")
    if js[start:end] != ARRIVAL:
        js = js[:start] + ARRIVAL + js[end:]
        done.append("glyph-assembly arrival")

    if ARRIVAL_MS not in js:
        js = once(js, ARRIVAL_MS_OLD, ARRIVAL_MS, "arrival clock")
        done.append("arrival lasts 2 s")

    if "__callistoHeld" not in js:                                     # the arrival waits to be seen
        js = once(js, CLOCK, CLOCK_HELD, "planet clock")
        done.append("arrival hold (client)")
    if "__callistoHeld" not in html:
        html = once(html, HOLD_BEFORE, HOLD + HOLD_BEFORE, "head slot")
        done.append("arrival hold (page)")

    if 'id="callisto-fit"' not in html:
        html = once(html, HOLD_BEFORE, FIT + HOLD_BEFORE, "head slot")
        done.append("answer lettering fits its word")

    main_js.write_text(js)
    page.write_text(html)
    print("workspace_callisto:", ", ".join(done) if done else "nothing to do")


if __name__ == "__main__":
    main()
