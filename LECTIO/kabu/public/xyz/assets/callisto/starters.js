/* Callisto starter questions: three quiet example questions under the landing's question box.
 *
 * Self-contained and outside the React tree: one container is appended to <body> and placed
 * under the question box by measuring it. The starters appear once the moon has arrived
 * (stage data-phase="settled"), hide while the box holds any text, and are removed when the
 * landing is gone (a conversation is open). Clicking one puts its text in the box and focuses
 * it; it never sends. If the expected elements never appear, nothing happens.
 */
(function () {
  'use strict';
  if (window.__callistoStarters) {
    return;
  }
  window.__callistoStarters = true;

  var QUESTIONS = [
    "What was Apple's revenue in its latest fiscal year?",
    "How has Nvidia's gross margin changed over five years?",
    'What risks does Tesla list in its latest 10-K?',
  ];
  var FIGURE = 'figure[data-testid="mars-horizon"]';
  var COMPOSER = '[data-testid="composer-surface"]';
  var TEXTAREA = 'textarea#prompt-textarea';
  var INTERACTIVE =
    'a[href],button,input,select,textarea,summary,[contenteditable=""],[contenteditable="true"],' +
    '[role="button"],[role="link"],[role="menuitem"],[role="tab"],[role="option"],[tabindex]:not([tabindex="-1"])';
  var GAP = 18; /* px between the box and the starters */
  var EDGE = 12; /* px the starters keep from the bottom of the window */

  var CSS =
    '#callisto-starters{position:fixed;top:0;left:0;z-index:1;box-sizing:border-box;margin:0;padding:0;' +
    'display:flex;flex-wrap:wrap;justify-content:center;align-items:center;gap:8px;pointer-events:none;' +
    'visibility:hidden;transition:visibility 0s linear 220ms;--cs-ink:244,245,247;' +
    "font-family:Inter,ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;}" +
    'html:not(.dark) #callisto-starters{--cs-ink:14,20,32;}' +
    '#callisto-starters[data-state="shown"]{visibility:visible;transition-delay:0s;}' +
    '#callisto-starters.is-column{flex-direction:column;flex-wrap:nowrap;}' +
    '#callisto-starters .callisto-starter{pointer-events:auto;-webkit-appearance:none;appearance:none;' +
    'box-sizing:border-box;margin:0;max-width:100%;padding:7px 14px;border:1px solid rgba(var(--cs-ink),.12);' +
    'border-radius:999px;background:transparent;color:rgba(var(--cs-ink),.55);font:inherit;font-size:13px;' +
    'font-weight:400;line-height:18px;letter-spacing:0;text-align:center;white-space:normal;cursor:pointer;' +
    'opacity:0;transform:translateY(6px);' +
    'transition:opacity 200ms ease,transform 200ms ease,color 160ms ease,border-color 160ms ease,background-color 160ms ease;}' +
    '#callisto-starters[data-state="shown"] .callisto-starter{opacity:1;transform:none;' +
    'transition:opacity 450ms cubic-bezier(.22,.61,.36,1) calc(var(--i) * 90ms),' +
    'transform 450ms cubic-bezier(.22,.61,.36,1) calc(var(--i) * 90ms),' +
    'color 160ms ease,border-color 160ms ease,background-color 160ms ease;}' +
    '#callisto-starters .callisto-starter:hover,#callisto-starters .callisto-starter:focus-visible{' +
    'color:rgba(var(--cs-ink),.92);border-color:rgba(var(--cs-ink),.3);background-color:rgba(var(--cs-ink),.04);}' +
    '#callisto-starters .callisto-starter:focus{outline:none;}' +
    '#callisto-starters .callisto-starter:focus-visible{outline:2px solid rgba(var(--cs-ink),.75);outline-offset:2px;}' +
    '@media (prefers-reduced-motion:reduce){#callisto-starters{transition:none;}' +
    '#callisto-starters .callisto-starter,#callisto-starters[data-state="shown"] .callisto-starter{' +
    'transform:none;transition:color 160ms ease,border-color 160ms ease,background-color 160ms ease;}}';

  var doc = document;
  var root = null;
  var shown = false;
  var frame = 0;
  var resizer = null;
  var watched = null;

  function overlaps(a, b) {
    return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
  }

  function fill(text) {
    var box = doc.querySelector(TEXTAREA);
    if (!box) {
      return;
    }
    var setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value');
    if (setter && setter.set) {
      setter.set.call(box, text);
    } else {
      box.value = text;
    }
    box.dispatchEvent(new Event('input', { bubbles: true }));
    try {
      box.focus({ preventScroll: true });
      box.setSelectionRange(text.length, text.length);
    } catch (e) {
      /* focus is a nicety */
    }
    schedule();
  }

  function build() {
    root = doc.createElement('div');
    root.id = 'callisto-starters';
    root.setAttribute('role', 'group');
    root.setAttribute('aria-label', 'Example questions');
    root.setAttribute('data-state', 'hidden');
    root.setAttribute('aria-hidden', 'true');
    root.inert = true;
    QUESTIONS.forEach(function (question, i) {
      var button = doc.createElement('button');
      button.type = 'button';
      button.className = 'callisto-starter';
      button.textContent = question;
      button.style.setProperty('--i', String(i));
      button.addEventListener('click', function (event) {
        event.preventDefault();
        fill(question);
      });
      root.appendChild(button);
    });
  }

  function setShown(on) {
    if (on === shown) {
      return;
    }
    shown = on;
    root.setAttribute('data-state', on ? 'shown' : 'hidden');
    root.setAttribute('aria-hidden', on ? 'false' : 'true');
    root.inert = !on;
  }

  function watch(composer) {
    if (watched === composer || typeof ResizeObserver !== 'function') {
      return;
    }
    if (!resizer) {
      resizer = new ResizeObserver(schedule);
      resizer.observe(doc.documentElement);
    }
    if (watched) {
      resizer.unobserve(watched);
    }
    watched = composer;
    resizer.observe(composer);
  }

  function teardown() {
    if (resizer && watched) {
      resizer.unobserve(watched);
    }
    watched = null;
    if (root && root.parentNode) {
      root.parentNode.removeChild(root);
    }
    if (root) {
      shown = true;
      setShown(false);
    }
  }

  /* Places the container under the box; false when it would not fit or would cover anything. */
  function place(composer, figure) {
    var box = composer.getBoundingClientRect();
    if (box.width < 1 || box.height < 1) {
      return false;
    }
    root.classList.toggle('is-column', doc.documentElement.clientWidth <= 640);
    root.style.left = Math.round(box.left) + 'px';
    root.style.width = Math.round(box.width) + 'px';
    root.style.top = Math.round(box.bottom + GAP) + 'px';
    var area = root.getBoundingClientRect();
    if (area.bottom > window.innerHeight - EDGE || overlaps(area, box) || overlaps(area, figure.getBoundingClientRect())) {
      return false;
    }
    /* What lies under each starter must be the plain page around the box: nothing
     * interactive, no drawer or dialog on top. */
    var page = composer.closest('main') || doc.body;
    var buttons = root.children;
    for (var i = 0; i < buttons.length; i++) {
      var r = buttons[i].getBoundingClientRect();
      var points = [
        [r.left + 2, r.top + 2], [r.right - 2, r.top + 2], [r.left + 2, r.bottom - 2],
        [r.right - 2, r.bottom - 2], [(r.left + r.right) / 2, (r.top + r.bottom) / 2],
      ];
      for (var p = 0; p < points.length; p++) {
        var stack = doc.elementsFromPoint(points[p][0], points[p][1]);
        var under = null;
        for (var s = 0; s < stack.length; s++) {
          if (!root.contains(stack[s])) {
            under = stack[s];
            break;
          }
        }
        if (!under || !page.contains(under) || under.closest(INTERACTIVE)) {
          return false;
        }
      }
    }
    return true;
  }

  function update() {
    frame = 0;
    var figure = doc.querySelector(FIGURE);
    var composer = figure ? doc.querySelector(COMPOSER) : null;
    var box = composer ? composer.querySelector(TEXTAREA) || doc.querySelector(TEXTAREA) : null;
    if (!figure || !composer || !box) {
      teardown();
      return;
    }
    if (!root) {
      build();
    }
    if (root.parentNode !== doc.body) {
      doc.body.appendChild(root);
    }
    watch(composer);
    var stage = figure.querySelector('[data-phase]');
    var settled = !!stage && stage.getAttribute('data-phase') === 'settled';
    var fits = place(composer, figure);
    setShown(settled && box.value.length === 0 && fits);
  }

  function schedule() {
    if (!frame) {
      frame = window.requestAnimationFrame(function () {
        try {
          update();
        } catch (e) {
          /* a starter is never worth an error */
        }
      });
    }
  }

  function start() {
    if (!doc.body) {
      return;
    }
    var style = doc.createElement('style');
    style.id = 'callisto-starters-style';
    style.textContent = CSS;
    doc.head.appendChild(style);
    new MutationObserver(schedule).observe(doc.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['data-phase'],
    });
    window.addEventListener('resize', schedule);
    doc.addEventListener('scroll', schedule, { capture: true, passive: true });
    doc.addEventListener('input', schedule, true);
    /* the app may empty the box itself (no input event): a slow look keeps up with that */
    window.setInterval(function () {
      if (!doc.hidden) {
        schedule();
      }
    }, 500);
    schedule();
  }

  try {
    if (doc.readyState === 'loading') {
      doc.addEventListener('DOMContentLoaded', start);
    } else {
      start();
    }
  } catch (e) {
    /* the client works without the starters */
  }
})();
