"""The Callisto workspace without Deep Research (owner 2026-11-22: "take off the deep research
[and] everything connected to it").

Run after dev/patch_workspace_copy.py and dev/workspace_callisto.py; safe to run again:

    python3 dev/workspace_query_only.py

What goes, in the workspace client (public/xyz):
  * the Deep Research switch in the question box, with its tooltip (also its waiting and read-only
    forms), and its keyboard shortcut (Cmd/Ctrl+Shift+D goes back to the browser)
  * the Deep Research side panel and its tab (search research, recent research, saved reports): the
    side bar opens on the chat history instead
  * the Tools menu in the question box (every row was a research setting), the /deep and /deep!
    commands, and a research model named in the address; no request can ask for the research model
  * the shortcut's row in the keyboard shortcuts list
  * the words: the page title and description say Callisto only; the question box's hint is "Ask Callisto"
  * a research model left selected by an earlier visit: the page starts in the ordinary mode
The research code itself stays in the bundle, unreachable; nothing else is changed.
Every edit must match exactly once; the script refuses a copy it does not recognise.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent / "public" / "xyz"
MARK = "callisto-query-only"

JS_EDITS = [
    ("side panel list",
     "r=h?[{title:`com_ui_indago_panel_title`,label:``,icon:hn,id:mN,Component:SN,indicator:g?`live`:null},n]:[n];",
     "r=[n];/*%s*/" % MARK),
    ("shortcut row", "children:p&&(0,$.jsx)(gV,{disabled:!c})", "children:null"),
]
# The question box's hint is two words (owner 2026-11-22: "make the bar say like ChatGPT but
# instead Ask Callisto"); HINTS_BEFORE are the wordings it replaces.
HINTS_BEFORE = ["com_ui_indago_placeholder_query:`Ask about a US listed company: filings, financials, prices, news`",
                "com_ui_indago_placeholder_query:``"]
NEW_HINT = "com_ui_indago_placeholder_query:`Ask Callisto`"
# The /deep and /deep! commands are ordinary words now: the client no longer reads them as a
# request for research (one chunk routes the message, the same chunk draws the "Deep Research"
# badge on it).
SLASH_EDITS = [
    ("research badge", "y4=/^\\/(deep!|deep|quick|query)(?=\\s|$)\\s*/i", "y4=/^\\/(quick|query)(?=\\s|$)\\s*/i"),
    ("/deep! command", "XF=/^\\/deep!/i,ZF=RegExp(`^/deep${qF}+!`,`i`),QF=RegExp(`^/(deep|quick|query)(?=${qF}|$)`,`i`)",
     "XF=/^(?!)/i,ZF=RegExp(`^(?!)`,`i`),QF=RegExp(`^/(quick|query)(?=${qF}|$)`,`i`)"),
]
HTML_EDITS = [
    ("title", "<title>Callisto — Deep Research</title>", "<title>Callisto</title>"),
    ("description", 'content="Callisto Deep Research"', 'content="Callisto: answers about US listed companies from their filings"'),
]
HEAD = """    <style id="%(m)s">
      /* this build has no Deep Research: its switch (and the switch's waiting and read-only forms,
         and the description read to screen readers) is gone, and so is the Tools menu, whose rows
         were all research settings (the research switch, run depth, sources, claim tracking) */
      [data-research-toggle], [data-research-toggle] + .sr-only, [data-testid^="deep-research-"],
      [data-testid="indago-tools-button"], [data-testid="tools-menu-deep-research"] { display: none !important; }
    </style>
    <script id="%(m)s-guard">
      /* No Deep Research in this build. Its shortcut goes back to the browser; a research model
       * remembered from an earlier visit, or named in the address, is forgotten before the app
       * reads it; and no request can leave the page asking for the research model. */
      (function () {
        var DEEP = 'indago-deep-research', PLAIN = 'indago-query';
        var plain = function (text) { return typeof text === 'string' && text.indexOf(DEEP) !== -1 ? text.split(DEEP).join(PLAIN) : text; };
        window.addEventListener('keydown', function (e) {
          if ((e.metaKey || e.ctrlKey) && e.shiftKey && !e.altKey && (e.key === 'D' || e.key === 'd' || e.code === 'KeyD')) {
            e.stopImmediatePropagation();
          }
        }, true);
        try {
          for (var i = 0; i < localStorage.length; i++) {
            var key = localStorage.key(i), value = localStorage.getItem(key);
            if (value && value.indexOf(DEEP) !== -1) localStorage.setItem(key, plain(value));
          }
        } catch (e) {
          /* storage unavailable: the app starts in the ordinary mode anyway */
        }
        try {
          if (window.location.search.indexOf(DEEP) !== -1) {
            window.history.replaceState(window.history.state, '', window.location.pathname + plain(window.location.search) + window.location.hash);
          }
        } catch (e) {
          /* the address stays; the request guard below still holds */
        }
        try {
          var send = window.fetch;
          window.fetch = function (input, init) {
            if (init && typeof init.body === 'string') init = Object.assign({}, init, { body: plain(init.body) });
            return send.call(this, input, init);
          };
          var xhrSend = XMLHttpRequest.prototype.send;
          XMLHttpRequest.prototype.send = function (body) { return xhrSend.call(this, plain(body)); };
        } catch (e) {
          /* nothing to guard */
        }
      })();
    </script>
""" % {"m": MARK}
HEAD_BEFORE = '    <meta name="theme-color"'


def once(text, old, new, what):
    if text.count(old) != 1:
        sys.exit(f"workspace_query_only: expected exactly one {what!r}, found {text.count(old)}")
    return text.replace(old, new)


def main():
    main_js = next(p for p in (ROOT / "assets").glob("index.*.js") if "com_ui_indago_panel_title" in p.read_text(errors="ignore"))
    page = ROOT / "index.html"
    js, html = main_js.read_text(), page.read_text()
    done = []
    if MARK not in js:
        for what, old, new in JS_EDITS:
            js = once(js, old, new, what)
        main_js.write_text(js)
        done.append(main_js.name)
    if NEW_HINT not in js:
        before = [h for h in HINTS_BEFORE if h in js]
        if len(before) != 1:
            sys.exit("workspace_query_only: the question box hint was not recognised")
        js = once(js, before[0], NEW_HINT, "question box hint")
        main_js.write_text(js)
        done.append("question box hint: Ask Callisto")
    if MARK not in html:
        for what, old, new in HTML_EDITS:
            html = once(html, old, new, what)
        html = once(html, HEAD_BEFORE, HEAD + HEAD_BEFORE, "head slot")
        page.write_text(html)
        done.append(page.name)
    hooks = next(p for p in (ROOT / "assets").glob("hooks.*.js") if "dr2-user-lane" in p.read_text(errors="ignore"))
    text = hooks.read_text()
    if SLASH_EDITS[0][2] not in text:
        for what, old, new in SLASH_EDITS:
            text = once(text, old, new, what)
        hooks.write_text(text)
        done.append("/deep commands are ordinary words")

    html = page.read_text()                                           # the page's rule and guard, current form
    start = html.find('    <style id="%s">' % MARK)
    end = html.find("    </script>\n", html.find('<script id="%s-guard">' % MARK)) + len("    </script>\n")
    if start < 0 or end < start:
        sys.exit("workspace_query_only: the page's rule and guard were not found")
    if html[start:end] != HEAD:
        page.write_text(html[:start] + HEAD + html[end:])
        done.append("page rule and guard")
    print("workspace_query_only:", ", ".join(done) if done else "nothing to do")


if __name__ == "__main__":
    main()
