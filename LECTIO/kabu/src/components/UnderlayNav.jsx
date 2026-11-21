import React, { useEffect, useRef } from "react";
import gsap from "gsap";
import { CustomEase } from "gsap/CustomEase";
import { useLocation } from "react-router-dom";
import { acquireBodyScrollLock } from "@/lib/bodyScrollLock";
import { menuItems } from "./navItems.js";
import { prefetchMenuRoutes, prefetchRoute } from "../lib/routePrefetch.js";
import { letteringWord } from "./indagoLettering.js";
import LogoPlanet from "./LogoPlanet.jsx";
import { OPEN_INDAGO_NAVIGATION, menuEntryFocus } from "@/lib/navigationEvents.js";

/* The Dashboard: Osmo Supply "Fixed Underlay Navigation", copied 1:1.
 *
 *   Markup  the resource's structure, class names and data- attributes. Only
 *           the demo content is Indago's: the logo, the route rows and the
 *           two bottom columns.
 *   CSS     UNDERLAY_NAV_CSS below: the resource CSS with its values
 *           unchanged, every selector scoped under .underlay-nav so nothing
 *           leaks into the app, after the Webflow host environment the
 *           resource assumes (base size, font, ink) and before the Indago
 *           integration rules.
 *   JS      initFixedUnderlayNavigation(): the resource script (GSAP 3.15
 *           timeline split by addPause, easeReverse, CustomEase "energy",
 *           four-branch toggle, overlay click, Escape, resize) in an init
 *           that runs once after mount and returns its own cleanup. Indago
 *           additions inside it are marked "Indago:". */

gsap.registerPlugin(CustomEase);
CustomEase.create("energy", "M0,0 C0.32,0.72 0,1 1,1");

const FOCUSABLE = [
  'a[href]:not([tabindex="-1"])',
  'button:not([disabled]):not([tabindex="-1"])',
  'input:not([disabled]):not([tabindex="-1"])',
  'select:not([disabled]):not([tabindex="-1"])',
  'textarea:not([disabled]):not([tabindex="-1"])',
  '[tabindex]:not([tabindex="-1"])',
].join(",");

/* One binding per nav root: React StrictMode runs an effect, its cleanup and
   the effect again; a second init on a root that is still bound is refused. */
const boundRoots = new WeakSet();

/** Binds the resource behaviour to one rendered nav. Returns the cleanup,
 *  which removes only what this init added (listeners, the timeline, the
 *  inline styles GSAP wrote, the body flag and scroll lock it set). */
export function initFixedUnderlayNavigation(root, host = {}) {
  if (!root || boundRoots.has(root)) return undefined;

  const toggleBtn = root.querySelector("[data-underlay-nav-toggle]");
  const toggleLabels = root.querySelectorAll(".underlay-nav__toggle-label");
  const toggleBars = root.querySelectorAll(".underlay-nav__toggle-bar");
  const menuEl = root.querySelector("[data-underlay-nav-menu]");
  const largeItems = root.querySelectorAll("[data-reveal-l]");
  const smallItems = root.querySelectorAll("[data-reveal-s]");
  const menuBorder = root.querySelector(".underlay-nav__bottom-border");
  const mainEl = document.querySelector(host.mainSelector || "[data-main]");
  const overlayEl = root.querySelector("[data-underlay-nav-overlay]");
  const darkEl = root.querySelector(".underlay-nav__dark");
  const corners = root.querySelectorAll(".underlay-nav__corner");
  const overlayBorders = root.querySelectorAll(".underlay-nav__border-row");
  const headerEl = root.querySelector(".underlay-nav__header"); // Indago
  const innerEl = menuEl?.querySelector?.(".underlay-nav__inner") ?? null; // Indago: the menu's scroll box

  if (!toggleBtn || !menuEl || !mainEl || !overlayEl) return undefined;
  boundRoots.add(root);

  // Indago: the resource reads the closed colour once. Here it follows the
  // page under the header (header CSS, inherited by the toggle) and this nav
  // outlives route changes, so it is a function value: GSAP evaluates it when
  // the close leg starts, again after every open's invalidate().
  const closedColor = () => getComputedStyle(headerEl || toggleBtn).color;
  const openColor = getComputedStyle(menuEl).color;

  let isOpen = false;
  let tl;
  let enterEndTime = 0;

  const getMenuOffset = () => -menuEl.offsetWidth;

  gsap.set(overlayEl, { visibility: "hidden", pointerEvents: "none" });
  gsap.set(darkEl, { autoAlpha: 0 });
  gsap.set(mainEl, { x: 0 });
  gsap.set(toggleLabels, { yPercent: 0 });
  gsap.set(toggleBars, { y: 0, rotation: 0 });
  gsap.set(menuBorder, { scaleX: 0 });
  gsap.set(overlayBorders[0], { yPercent: -100 });
  gsap.set(overlayBorders[1], { yPercent: 100 });
  gsap.set(corners, { scale: 0 });

  // Indago: the closed menu sits behind the opaque page, so it leaves the tab
  // order and the accessibility tree (inert), and an open menu isolates the
  // page instead (prior state restored on close).
  const mainHadInert = mainEl.hasAttribute("inert");
  const mainAriaHidden = mainEl.getAttribute("aria-hidden");
  menuEl.setAttribute("inert", "");
  const isolateMain = (open) => {
    menuEl.setAttribute("aria-hidden", open ? "false" : "true");
    if (open) menuEl.removeAttribute("inert");
    else menuEl.setAttribute("inert", "");
    if (open) {
      mainEl.setAttribute("inert", "");
      mainEl.setAttribute("aria-hidden", "true");
    } else {
      if (!mainHadInert) mainEl.removeAttribute("inert");
      if (mainAriaHidden == null) mainEl.removeAttribute("aria-hidden");
      else mainEl.setAttribute("aria-hidden", mainAriaHidden);
    }
  };
  const menuFocusables = () => [...menuEl.querySelectorAll(FOCUSABLE)]
    .filter((el) => !el.hidden && el.getAttribute("aria-hidden") !== "true");
  let focusFrame = 0;
  let releaseScrollLock = null;
  // Indago: true while an embedded workspace (the Deep Research frame) owns the page
  const isExternal = () => Boolean(host.isExternal?.());
  let returnFocus = null;

  function buildTimeline() {
    tl = gsap.timeline({
      paused: true,
      defaults: {
        ease: "energy",
        easeReverse: "power2.inOut"
      },
      // Indago: a close during the open leg reverses to 0, and the
      // position-0 set below may revert the overlay to the state recorded at
      // the last invalidate() (visible, mid toggle spam): land it closed.
      onReverseComplete: () => {
        gsap.set(overlayEl, { visibility: "hidden", pointerEvents: "none" });
        // a reverse landing IS a close landing: retire "closing"
        if (!isOpen) document.body.setAttribute("data-menu-status", "");
        if (!isOpen) gsap.set(toggleBtn, { clearProps: "color" });
      },
    });

    tl.set(overlayEl, { visibility: "visible", pointerEvents: "auto" }, 0);

    tl.to([mainEl, overlayEl], {
      x: getMenuOffset,
      duration: 0.7,
    }, 0)

    .to(darkEl, {
      autoAlpha: 1,
      duration: 0.5,
    }, 0)

    .to(corners, {
      scale: 1,
      duration: 0.5,
    }, 0)

    .to(overlayBorders, {
      yPercent: 0,
      duration: 0.5,
    }, 0)

    .to(toggleLabels, {
      yPercent: -100,
      duration: 0.4,
    }, 0)

    .to(toggleBtn, {
      color: openColor,
      duration: 0.4,
    }, 0)

    .to(toggleBars[0], {
      y: "0.25em",
      rotation: 45,
      duration: 0.35,
      ease: "back.out(1.4)",
      easeReverse: "power3.out",
    }, 0.05)

    .to(toggleBars[1], {
      y: "-0.25em",
      rotation: -45,
      duration: 0.35,
      ease: "back.out(1.4)",
      easeReverse: "power3.out",
    }, 0.05)

    .fromTo(largeItems,
      { autoAlpha: 0, xPercent: 25 },
      {
        autoAlpha: 1,
        xPercent: 0,
        duration: 0.7,
        stagger: 0.05,
      },
      0
    )

    .fromTo(smallItems,
      { autoAlpha: 0, yPercent: 100 },
      {
        autoAlpha: 1,
        yPercent: 0,
        duration: 0.5,
        stagger: 0.03,
        ease: "power3.out"
      },
      0.3
    )

    .to(menuBorder, {
      scaleX: 1,
      duration: 0.5,
    }, "<");

    enterEndTime = tl.duration();

    tl.addPause();

    tl.to([largeItems, smallItems], {
      autoAlpha: 0,
      duration: 0.3,
    }, "<")

    .to([mainEl, overlayEl], {
      x: 0,
      duration: 0.6,
    }, "<")

    .to(darkEl, {
      autoAlpha: 0,
      duration: 0.35,
      ease: "power2.inOut",
    }, "<")

    .to(corners, {
      scale: 0,
      duration: 0.5,
    }, "<")

    .to(overlayBorders[0], {
      yPercent: -100,
      duration: 0.5,
    }, "<")

    .to(overlayBorders[1], {
      yPercent: 100,
      duration: 0.5,
    }, "<")

    .to(toggleBtn, {
      color: closedColor,
      duration: 0.25,
    }, "<+=0.1")

    .to(toggleLabels, {
      yPercent: 0,
      duration: 0.25,
      ease: "power3.in",
    }, "<")

    .to(toggleBars, {
      y: 0,
      rotation: 0,
      duration: 0.25,
      ease: "power3.in",
    }, "<")

    .set(overlayEl, {
      visibility: "hidden",
      pointerEvents: "none"
    })

    // Indago: the close leg has landed: retire "closing" and hand the toggle
    // colour back to the page CSS (a watchdog pause() seek suppresses this
    // call; its closed branch does the same itself).
    .call(() => {
      if (isOpen) return;
      document.body.setAttribute("data-menu-status", "");
      gsap.set(toggleBtn, { clearProps: "color" });
    });
  }

  /* Indago: terminal-state watchdog. Rapid toggling interleaves play(),
     reverse() and restart() on the two-leg timeline and can wedge it
     mid-flight (proven live: page left translated, labels half-swapped).
     The timeline is deterministic by time, so once the animation should long
     be over it is seeked to the exact end frame of the latest intent. After a
     normal finish this lands on the frame already shown. */
  let settleTimer = 0;
  const settleToIntent = () => {
    if (!tl) return;
    if (isOpen) {
      tl.pause(enterEndTime);          // exact end of the open leg
    } else {
      tl.pause(tl.duration());         // exact end of the close leg
      // a seek that lands exactly on a zero-duration set can skip it, and a
      // lingering transform makes [data-main] a containing block for fixed
      // descendants
      gsap.set(overlayEl, { visibility: "hidden", pointerEvents: "none" });
      gsap.set(mainEl, { x: 0, clearProps: "transform" });
      gsap.set(toggleBtn, { clearProps: "color" });
      // pause() seeks suppress the close leg's end call: retire "closing"
      document.body.setAttribute("data-menu-status", "");
    }
  };

  function toggle() {
    isOpen = !isOpen;
    const externalTrigger = isExternal(); // Indago: opened from an embedded workspace
    if (isOpen) prefetchMenuRoutes(menuItems().map((item) => item.route)); // Indago: route code, on idle time
    toggleBtn.setAttribute("aria-expanded", String(isOpen));
    toggleBtn.setAttribute("aria-label", isOpen ? "close menu" : "open menu");
    // Indago: THREE states, "open" -> "closing" -> "" (the resource sets "").
    // The close animation runs ~0.6 s after the click; "" at the click would
    // lift the toast layer's stand-down while the menu is still on screen. A close
    // landing clears it: the close leg's end call, a reverse landing, the
    // watchdog's closed branch, and unmount.
    document.body.setAttribute("data-menu-status", isOpen ? "open" : "closing");
    clearTimeout(settleTimer);
    const intent = isOpen;
    settleTimer = setTimeout(() => {
      if (intent === isOpen) settleToIntent();
    }, 1400);                            // the longer leg (open) is ~1.05 s
    if (isOpen) {
      releaseScrollLock = acquireBodyScrollLock();
    } else {
      releaseScrollLock?.();
      releaseScrollLock = null;
    }

    if (isOpen) {
      // Indago: every open starts at the top of the menu (a phone-height menu
      // scrolls; an offset kept from the last open put rows under the header)
      if (innerEl) innerEl.scrollTop = 0;
      tl.invalidate();
      if (tl.time() >= enterEndTime) tl.timeScale(1).restart();
      else tl.timeScale(1).play();
      // Indago: focus moves into the menu. From an embedded workspace, take
      // focus out of the iframe at once so Escape and Tab belong to the host.
      isolateMain(true);
      if (externalTrigger) toggleBtn.focus({ preventScroll: true });
      cancelAnimationFrame(focusFrame);
      // A row is focusable only once its staggered reveal has started
      // (autoAlpha 0 means visibility:hidden): until then, try every frame
      // (the last row starts 0.35 s into the open leg).
      const focusEntry = (tries) => {
        menuEntryFocus(menuFocusables(), externalTrigger)?.focus({ preventScroll: true });
        if (tries > 0 && isOpen && !menuEl.contains(document.activeElement)) {
          focusFrame = requestAnimationFrame(() => focusEntry(tries - 1));
        }
      };
      focusFrame = requestAnimationFrame(() => focusEntry(60));
    } else {
      // Indago: a focused menu link would stay focused inside the tree that
      // isolateMain() aria-hides; hand focus to the toggle first (a route
      // change then focuses the new page's h1).
      if (externalTrigger) cancelAnimationFrame(focusFrame);
      if (menuEl.contains(document.activeElement)) {
        toggleBtn.focus({ preventScroll: true });
        if (document.activeElement instanceof HTMLElement && menuEl.contains(document.activeElement)) document.activeElement.blur();
      }
      if (tl.time() < enterEndTime) tl.timeScale(1).reverse();
      else tl.timeScale(1).play();
      isolateMain(false);
      if (externalTrigger && returnFocus?.isConnected) returnFocus.focus({ preventScroll: true });
    }
  }

  buildTimeline();

  toggleBtn.addEventListener("click", toggle);

  const overlayClick = () => {
    if (!isOpen) return;
    toggle();
    // Indago: as with Escape, keyboard focus goes back to the toggle (not <body>)
    toggleBtn.focus({ preventScroll: true });
  };
  overlayEl.addEventListener("click", overlayClick);

  const onKeydown = (e) => {
    // Indago: the command palette, when up, owns Escape and Tab
    if (
      isOpen &&
      (e.key === "Escape" || e.key === "Tab") &&
      document.querySelector('[data-command-palette-dialog][role="dialog"]')
    ) return;

    if (e.key === "Escape" && isOpen) {
      toggle();
      toggleBtn.focus();
    } else if (e.key === "Tab" && isOpen) {
      // Indago: keep Tab inside the open menu (toggle + menu links). Focus
      // anywhere else (the page body after a dialog closed, the logo) re-enters
      // the menu at its start (Tab) or end (Shift+Tab).
      const items = [toggleBtn, ...menuFocusables()];
      const first = items[0];
      const last = items[items.length - 1];
      if (!items.includes(document.activeElement)) {
        e.preventDefault();
        (e.shiftKey ? last : first).focus();
      } else if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  };
  document.addEventListener("keydown", onKeydown);

  let resizeTimer;

  const onResize = () => {
    clearTimeout(resizeTimer);

    resizeTimer = setTimeout(() => {
      if (isOpen) {
        // Indago: a resize during the open leg would be overwritten by the
        // running tween's old end value; land the leg first
        if (tl.isActive()) tl.pause(enterEndTime);
        gsap.set([mainEl, overlayEl], {
          x: getMenuOffset()
        });
      } else {
        tl.invalidate();
      }
    }, 150);
  };
  window.addEventListener("resize", onResize);

  // Indago: router integration. A real link in the menu navigates (hash
  // routes) and closes the menu through toggle(); a placeholder "#" link would
  // send HashRouter to "/", so its default is swallowed.
  const menuLinkGuard = (e) => {
    const link = e.target.closest("a");
    if (!link) return;
    const href = link.getAttribute("href");
    if (href === "#" || href === "" || href == null) {
      e.preventDefault();
      return;
    }
    if (isOpen) toggle();
  };
  menuEl.addEventListener("click", menuLinkGuard);

  // Indago: an embedded workspace (the Deep Research frame) opens the menu
  // through a window event; it applies only while the host says so.
  const openFromWorkspace = (event) => {
    if (!isExternal() || isOpen) return;
    returnFocus = event.detail?.returnFocus;
    toggle();
  };
  window.addEventListener(OPEN_INDAGO_NAVIGATION, openFromWorkspace);

  // Indago: router navigation (Back/Forward, links outside the menu) closes
  // an open menu through the same toggle() path.
  host.exposeClose?.(() => {
    if (isOpen) toggle();
  });

  return () => {
    toggleBtn.removeEventListener("click", toggle);
    overlayEl.removeEventListener("click", overlayClick);
    document.removeEventListener("keydown", onKeydown);
    window.removeEventListener("resize", onResize);
    menuEl.removeEventListener("click", menuLinkGuard);
    window.removeEventListener(OPEN_INDAGO_NAVIGATION, openFromWorkspace);
    host.exposeClose?.(null);
    clearTimeout(resizeTimer);
    clearTimeout(settleTimer);
    cancelAnimationFrame(focusFrame);
    tl.kill();
    gsap.set(mainEl, { x: 0, clearProps: "transform" });
    gsap.set([overlayEl, darkEl, toggleBtn, ...toggleLabels, ...toggleBars, menuBorder,
      ...overlayBorders, ...corners, ...largeItems, ...smallItems].filter(Boolean),
    { clearProps: "transform,opacity,visibility,pointerEvents,color" });
    toggleBtn.setAttribute("aria-expanded", "false");
    toggleBtn.setAttribute("aria-label", "open menu");
    isolateMain(false);
    menuEl.removeAttribute("inert");
    document.body.setAttribute("data-menu-status", "");
    releaseScrollLock?.();
    releaseScrollLock = null;
    boundRoots.delete(root);
  };
}

/* ── CSS ──────────────────────────────────────────────────────────────────
   1. Webflow host environment the resource assumes, for the nav only.
   2. The resource CSS, values unchanged, scoped under .underlay-nav.
   3. Indago integration. */
export const UNDERLAY_NAV_CSS = `
/* 1. Webflow host environment ------------------------------------------- */

/* Haffer XH (large links) and Haffer (everything else) are Displaay faces
   licensed to Osmo's site, not part of the resource: both are aliased to the
   closest local face, Helvetica Neue (Arial elsewhere, the resource's own
   fallback). No font file is shipped. */
@font-face {
  font-family: "Haffer XH";
  src: local("Helvetica Neue"), local("HelveticaNeue");
  font-weight: 400;
  font-style: normal;
}
@font-face {
  font-family: "Haffer";
  src: local("Helvetica Neue"), local("HelveticaNeue");
  font-weight: 400;
  font-style: normal;
}

/* The demo body: 16px at every width (the live spec measured
   base(vw) = 16px from 320 to 2560 px, no fluid scaling; every size below is
   em x 16), Haffer 400, line-height 1.25, ink #312e2e. */
.underlay-nav {
  font-family: Haffer, Arial, sans-serif;
  font-size: 16px;
  font-weight: 400;
  line-height: 1.25;
  color: #312e2e;
}

/* Webflow's Link Block class, which the demo's large links carry: it makes
   the current-page highlight a full-width row (416 x 70.8 px at 1440). */
.underlay-nav .w-inline-block {
  max-width: 100%;
  display: inline-block;
}

/* 2. Fixed Underlay Navigation: the resource CSS ------------------------ */

.underlay-nav {
  --menu-width: 30em;
}

.underlay-nav a {
  color: inherit;
  text-decoration: none;
}

.underlay-nav .underlay-nav__header {
  z-index: 100;
  color: #fff;
  position: fixed;
  inset: 0% 0% auto;
}

.underlay-nav .underlay-nav__bar {
  width: 100%;
  margin-left: auto;
  margin-right: auto;
}

.underlay-nav .underlay-nav__container {
  justify-content: space-between;
  align-items: center;
  padding: 2.5em;
  display: flex;
}

.underlay-nav .underlay-nav__logo {
  mix-blend-mode: multiply;
  justify-content: center;
  align-items: center;
  width: 6.875em;
  display: flex;
}

.underlay-nav .underlay-nav__logo-svg {
  width: 100%;
}

.underlay-nav .underlay-nav__toggle {
  grid-column-gap: .75em;
  grid-row-gap: .75em;
  outline-offset: 0px;
  background-color: #0000;
  border: 1px #000;
  outline: 3px #555;
  justify-content: center;
  align-items: center;
  margin: -1em;
  padding: 1em;
  display: flex;
  font: inherit;
  color: #fff;
  cursor: pointer;
}

.underlay-nav .underlay-nav__toggle-text {
  flex-flow: column;
  flex: none;
  justify-content: flex-start;
  align-items: flex-end;
  height: 1.5em;
  display: flex;
  overflow: hidden;
}

.underlay-nav .underlay-nav__toggle-label {
  font-size: 1.25em;
}

.underlay-nav .underlay-nav__toggle-icon {
  grid-column-gap: .375em;
  grid-row-gap: .375em;
  flex-flow: column;
  flex: none;
  justify-content: center;
  align-items: center;
  width: 1.5em;
  margin-bottom: -.3em;
  display: flex;
}

.underlay-nav .underlay-nav__toggle-bar {
  background-color: currentColor;
  flex: none;
  width: 100%;
  height: .125em;
  padding: 0;
}

.underlay-nav .underlay-nav__menu {
  z-index: 1;
  width: var(--menu-width);
  position: fixed;
  top: 0;
  bottom: 0;
  right: 0;
}

.underlay-nav .underlay-nav__overlay {
  z-index: 100;
  pointer-events: none;
  cursor: pointer;
  visibility: hidden;
  position: fixed;
  inset: 0% -1px 0% 0%;
  overflow: clip;
}

.underlay-nav .underlay-nav__inner {
  grid-column-gap: 2em;
  grid-row-gap: 2em;
  flex-flow: column;
  justify-content: space-between;
  align-items: stretch;
  width: 100%;
  height: 100%;
  padding: 7.5em 2em 2em;
  display: flex;
  overflow: auto;
}

.underlay-nav .underlay-nav__list {
  flex-flow: column;
  width: 100%;
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
}

.underlay-nav .underlay-nav__list.is--small {
  grid-column-gap: .75em;
  grid-row-gap: .75em;
}

.underlay-nav .underlay-nav__link-large {
  border-radius: .25em;
  width: 100%;
  padding: .75em 1em;
}

.underlay-nav .underlay-nav__link-large.w--current {
  color: #ededed;
  background-color: #0e1420;
}

.underlay-nav .underlay-nav__link-label {
  letter-spacing: -.04em;
  font-family: Haffer XH, Arial, sans-serif;
  font-size: 3.25em;
  line-height: .9;
}

.underlay-nav .underlay-nav__bottom {
  justify-content: flex-start;
  align-items: flex-start;
  width: 100%;
  padding-top: 1.5em;
  display: flex;
  position: relative;
}

.underlay-nav .underlay-nav__bottom-col {
  grid-column-gap: 1em;
  grid-row-gap: 1em;
  flex-flow: column;
  flex: 1;
  justify-content: flex-start;
  align-items: flex-start;
  display: flex;
}

.underlay-nav .underlay-nav__link-small {
  font-size: 1em;
  line-height: 1.1;
}

.underlay-nav .underlay-nav__link-small.is--faded {
  opacity: .5;
}

.underlay-nav .underlay-nav__corner {
  transform-origin: 100% 0;
  color: #fff;
  background-image: radial-gradient(circle farthest-side at 0 100%, #fff0 99%, #fff);
  width: 2em;
  height: 2em;
}

.underlay-nav .underlay-nav__corner.is--bottom {
  transform-origin: 100% 100%;
  background-image: radial-gradient(circle farthest-side at 0 0, #fff0 99%, #fff);
}

.underlay-nav .underlay-nav__dark {
  opacity: 0;
  background-color: #0000004d;
  position: absolute;
  inset: 0%;
}

.underlay-nav .underlay-nav__bottom-border {
  opacity: .15;
  transform-origin: 0%;
  background-color: currentColor;
  width: 100%;
  height: 1px;
  position: absolute;
  inset: 0% 0% auto;
}

.underlay-nav .underlay-nav__borders {
  flex-flow: column;
  justify-content: space-between;
  align-items: stretch;
  display: flex;
  position: absolute;
  inset: 0;
}

.underlay-nav .underlay-nav__border {
  background-color: #fff;
  width: 100%;
  height: 1em;
}

.underlay-nav .underlay-nav__border-row {
  flex-flow: column;
  justify-content: flex-start;
  align-items: flex-end;
  display: flex;
}

@media screen and (max-width: 767px) {
  .underlay-nav {
    --menu-width: 80vw;
  }

  /* (.section-resource__h1 is the demo page's heading, not part of the nav) */

  .underlay-nav .underlay-nav__container {
    padding: 1.25em;
  }

  .underlay-nav .underlay-nav__logo {
    width: 5em;
  }

  .underlay-nav .underlay-nav__toggle-text {
    height: 1.25em;
  }

  .underlay-nav .underlay-nav__toggle-label {
    font-size: 1em;
  }

  .underlay-nav .underlay-nav__inner {
    padding: 5em 1.25em 1.25em;
  }

  .underlay-nav .underlay-nav__link-label {
    font-size: 2em;
  }

  .underlay-nav .underlay-nav__bottom {
    grid-column-gap: 2em;
    grid-row-gap: 2em;
    flex-flow: column;
    padding-left: 1em;
    padding-right: 1em;
  }
}

/* 3. Indago integration -------------------------------------------------- */

/* Header ink. The demo header is #fff over a dark page; Indago's pages are
   light, so the closed header takes the page ink and the dark pages keep the
   resource's #fff. The toggle inherits it, as in the live demo's compiled CSS
   (color: inherit; the pasted #fff computes the same there). */
.underlay-nav .underlay-nav__header {
  color: #0a0a0a;
}
.underlay-nav .underlay-nav__toggle {
  color: inherit;
}
body[data-home-dark="1"] .underlay-nav .underlay-nav__header {
  color: #fff;
}

/* The pop-out is always white (owner 2026-10-13), also on the dark pages: the resource's menu has no
   fill and showed whatever lay behind it (dark Home's page shell). Over it the CLOSE toggle takes the
   dark ink while the menu is open; the logo keeps its page's ink (it sits over the shrunken page). */
.underlay-nav .underlay-nav__menu {
  background-color: #fff;
}
body[data-menu-status="open"] .underlay-nav .underlay-nav__toggle {
  color: #0a0a0a;
}

/* Header gutters. Above 980 px the logo and the toggle sit on a centred
   1880 px column with 48 px sides instead of the resource's 40 px from the
   window edge. */
@media screen and (min-width: 981px) {
  .underlay-nav .underlay-nav__container {
    box-sizing: border-box;
    max-width: 1880px;
    margin-left: auto;
    margin-right: auto;
    padding-left: 48px;
    padding-right: 48px;
  }
}

/* The fixed full-width header band would swallow clicks on the page content
   under it: only the logo and the toggle take the pointer. */
.underlay-nav .underlay-nav__header {
  pointer-events: none;
}
.underlay-nav .underlay-nav__logo,
.underlay-nav .underlay-nav__toggle {
  pointer-events: auto;
}

/* Deep Research: the frame has its own Dashboard link, so the header shows
   only while the menu owns the screen. */
.underlay-nav-root--external .underlay-nav__header {
  visibility: hidden;
}
body[data-menu-status="open"] .underlay-nav-root--external .underlay-nav__header,
body[data-menu-status="closing"] .underlay-nav-root--external .underlay-nav__header {
  visibility: visible;
}

/* Phones: the open page stops 20vw from the left, so its rounded corner would
   cut through the fixed INDAGO logo. The logo fades out with the open leg's
   slide and back in as the close leg starts (the page is back under it within
   about 0.1 s). Opacity only; the timeline is untouched. */
@media screen and (max-width: 767px) {
  .underlay-nav .underlay-nav__logo {
    transition: opacity 0.3s ease 0.05s;
  }
  body[data-menu-status="open"] .underlay-nav .underlay-nav__logo {
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.2s ease;
  }
}

/* The body-portaled toast layer (z100) sits above the z-index 1 menu. While
   the menu owns the screen ("open", and "closing" until the close leg lands)
   it stands down. */
body[data-menu-status="open"] .app-toast-layer,
body[data-menu-status="closing"] .app-toast-layer {
  opacity: 0 !important;
  visibility: hidden !important;
  pointer-events: none !important;
  transition: none !important;
}

/* Size. Desktop: the menu (not the header) grows with the viewport width
   (16px at 1440 px, as in the demo) and is capped by the viewport height, so
   every row and the whole bottom section fit with no scrolling inside the
   menu. On a short
   viewport two things stop scaling down: the rows start at least 96px down,
   below the toggle's hit area (it ends at 84px), so the Home row never sits
   under CLOSE, and the bottom section keeps its 12px floor (below). The third
   term is the budget for that case: about 50 font-size units plus 250px.
   Below 600px of height (a phone held landscape, 932 x 430) the rows stop
   at 7px instead of shrinking to 3-4px, and the column scrolls (the inner
   box is overflow: auto); a negative budget (under 250px) also lands here.
   Phones keep the resource's 16px. */
/* The menu's top space sits on the menu, above its scroll box (the
   resource puts it inside .underlay-nav__inner). A menu taller than the
   viewport (phones, short windows) scrolls inside that box, and the scrolled
   rows ran under the transparent INDAGO / CLOSE header; now they clip at the
   header's edge. At rest the layout is the same. */
.underlay-nav .underlay-nav__menu {
  box-sizing: border-box;
  padding-top: 7.5em;
}
.underlay-nav .underlay-nav__inner {
  padding-top: 0;
}
@media screen and (max-width: 767px) {
  .underlay-nav .underlay-nav__menu {
    padding-top: 5em;
  }
}
@media screen and (min-width: 768px) {
  .underlay-nav .underlay-nav__menu {
    font-size: max(7px, min(max(16px, 1.1111vw), calc((100vh - 44px) / 66.5), calc((100vh - 250px) / 50)));
    padding-top: max(7.5em, 96px);
  }
}

/* Keyboard focus on the DASHBOARD / CLOSE toggle. The resource's
   "outline: 3px #555" has no style keyword, so it draws nothing; a mouse
   click keeps no ring. */
.underlay-nav .underlay-nav__toggle:focus {
  outline: none;
}
.underlay-nav .underlay-nav__toggle:focus-visible {
  outline: 2px solid currentColor;
  outline-offset: -0.4em;
  border-radius: 0.5em;
}

/* The logo link is the first Tab stop on every page: a ring in the logo's own
   ink, so it shows on the dark page and the light ones alike. */
.underlay-nav .underlay-nav__logo:focus-visible {
  outline: 2px solid currentColor;
  outline-offset: 4px;
  border-radius: 2px;
}

/* Magnetic hover pill. One accent block inside the row list glides to the
   hovered or keyboard-focused row and rests on the current page's row. It
   is the only row highlight, so the resource's accent w--current box is
   cleared here (no second accent box). It sits above the rows as a window:
   its light (#ededed) copy of the row labels, laid out like the rows and
   shifted by the pill's offset (JS), shows the covered text in the light
   ink, also mid-glide. Position and height are written by the glide (JS). */
.underlay-nav .underlay-nav__list {
  position: relative;
}
.underlay-nav .underlay-nav__hover-pill {
  position: absolute;
  left: 0;
  width: 100%;
  top: 0;
  height: 0;
  background-color: #0e1420;
  border-radius: 0.25em;
  opacity: 0;
  pointer-events: none;
  z-index: 2;
  overflow: hidden;
  will-change: transform, height;
}
.underlay-nav .underlay-nav__pill-clone {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  display: flex;
  flex-flow: column;
  color: #ededed;
  pointer-events: none;
  user-select: none;
}
.underlay-nav .underlay-nav__pill-link {
  width: 100%;
  padding: .75em 1em;
}
.underlay-nav .underlay-nav__pill-label {
  letter-spacing: -.04em;
  font-family: Haffer XH, Arial, sans-serif;
  font-size: 3.25em;
  line-height: .9;
}
@media screen and (max-width: 767px) {
  .underlay-nav .underlay-nav__pill-label {
    font-size: 2em;
  }
}
.underlay-nav .underlay-nav__link-large {
  position: relative;
  z-index: 1;
  outline: none;
}
.underlay-nav .underlay-nav__link-large:focus-visible {
  outline: none;
}
.underlay-nav .underlay-nav__link-large.w--current {
  color: inherit;
  background-color: transparent;
}

/* Header sizes. --ul-u is the size of one lettering unit: the toggle's letters
   are 49 u tall (14.68 px on desktop, 10.68 px on phones; narrow phones scale
   down so the logo and the toggle fit one row). The logo is sized in the same
   unit, so both scale together and share one centre line. */
.underlay-nav .underlay-nav__header {
  --ul-u: 0.29959px;
}
@media screen and (max-width: 767px) {
  .underlay-nav .underlay-nav__header {
    --ul-u: min(0.21788px, calc((100vw - 60px) / 1794));
  }
}
/* The logo is a row: the planet, then the word, on one centre line. */
.underlay-nav .underlay-nav__logo {
  width: auto;
  mix-blend-mode: normal;
  display: inline-flex;
  align-items: center;
  gap: calc(var(--ul-u) * 34);
}
/* The planet (LogoPlanet): Europa in coloured ASCII, 104 u across (about
   31 px on desktop), 34 u left of the word; the phone unit above budgets
   these 138 u. It comes up once per page load: it waits 10 px low, faded
   and scaled down (is--below), and rises as its glyphs assemble. Transform
   and opacity only. */
.underlay-nav .underlay-nav__logo-planet {
  display: block;
  flex: none;
  width: calc(var(--ul-u) * 104);
  height: calc(var(--ul-u) * 104);
  transition: opacity 0.9s cubic-bezier(0.22, 1, 0.36, 1), transform 0.9s cubic-bezier(0.22, 1, 0.36, 1);
}
.underlay-nav .underlay-nav__logo-planet.is--below {
  opacity: 0;
  transform: translateY(10px) scale(0.6);
}
.underlay-nav .underlay-nav__logo-planet-canvas {
  display: block;
  width: 100%;
  height: 100%;
}
@media (prefers-reduced-motion: reduce) {
  .underlay-nav .underlay-nav__logo-planet {
    transition: none;
  }
}
/* The wordmark: the word EUROPA in the same lettering and at the same scale
   as the toggle labels, in the header's own ink. */
.underlay-nav .underlay-nav__logo-word {
  display: block;
  flex: none;
  width: calc(var(--ul-u) * var(--ul-w));
  height: calc(var(--ul-u) * 64);
  overflow: visible;
}
.underlay-nav .underlay-nav__toggle-label {
  position: relative;
  display: flex;
  flex: none;
  align-items: center;
  justify-content: flex-end;
  height: 100%;
}
.underlay-nav .underlay-nav__toggle-word {
  display: block;
  flex: none;
  width: calc(var(--ul-u) * var(--ul-w));
  height: calc(var(--ul-u) * 64);
  overflow: visible;
}
.underlay-nav .underlay-nav__toggle-sr {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}
/* The two bars: as thick as a letter stem (11 u), spanning the letter height
   (49 u), 60 u wide. The icon's font-size is 76 u so the resource's
   y: +-0.25em close tween (19 u) brings the bars to the centre line. */
.underlay-nav .underlay-nav__toggle-icon {
  font-size: calc(var(--ul-u) * 76);
  width: calc(60em / 76);
  gap: calc(27em / 76);
  margin-bottom: 0;
}
.underlay-nav .underlay-nav__toggle-bar {
  height: calc(11em / 76);
}
/* Label to bars: two letter gaps, so the bars do not read as a tenth letter. */
.underlay-nav .underlay-nav__toggle {
  gap: calc(var(--ul-u) * 82);
}
/* Narrow phones (under 420 px): the logo and DASHBOARD would read as one
   line of lettering. The toggle's lettering steps down to 0.8 of the logo's
   unit, opening a clear gap after "beta"; the tap target keeps the
   resource's 1em padding (52 px tall). */
@media screen and (max-width: 419px) {
  .underlay-nav .underlay-nav__toggle {
    --ul-u: calc((100vw - 60px) / 1656 * 0.8);
  }
}

/* Bottom section: the credit line. The resource's phone-only 1em
   side inset applies at every width, so the column starts on the same line
   as the row labels (.underlay-nav__link-large's 1em). */
.underlay-nav .underlay-nav__bottom {
  flex-flow: column;
  gap: 2em;
  padding-left: 1em;
  padding-right: 1em;
}
.underlay-nav .underlay-nav__bottom-col {
  row-gap: 0.85em;
  flex: 0 1 auto;
  width: 100%;
}
/* The faded label (the credit line): a solid grey (~5.4:1 on the white panel)
   instead of the resource's opacity .5 (2.9:1). */
.underlay-nav .underlay-nav__link-small.is--faded {
  opacity: 1;
  color: #6b6868;
}
/* Legibility floor for the bottom section. The menu font shrinks with a
   short viewport (about 10 px at 1280 x 720), so the credit line never goes
   below 14 px. Bold and a step larger than the resource's small links (owner 2026-11-22:
   "make this bold and slightly bigger"). */
.underlay-nav .underlay-nav__bottom .underlay-nav__link-small {
  font-size: max(1.2em, 14px);
  font-weight: 700;
}

/* The rows in the resource's own type (owner 2026-10-13: "make it bigger and font like this"): the
   resource's .underlay-nav__link-label rule above, unchanged (Haffer XH, a licensed face not shipped
   here, so Arial, the resource's own fallback; 3.25em, -0.04em, line-height .9; 2em on phones), in
   the labels' own case; the accent hover pill's light copy uses the same type. The bottom too (owner 2026-10-13: "change the bottom font"): the resource's
   small links (1em, line-height 1.1, labels faded .5 in their own case) in the demo's text face
   (Haffer, licensed and not shipped: Arial). */
.underlay-nav .underlay-nav__bottom {
  font-family: Haffer, Arial, sans-serif;
}
/* Narrow phones: a row of up to ~7em of Arial at -0.04em still fits the 80vw
   menu less its 72 px of padding; the resource's 2em wherever it already fits. */
@media screen and (max-width: 767px) {
  .underlay-nav .underlay-nav__link-label,
  .underlay-nav .underlay-nav__pill-label {
    font-size: min(2em, calc((80vw - 72px) / 7));
  }
}
`;

/* A toggle label drawn in the logo's lettering, at the logo's scale (the svg
   is sized in lettering units, --ul-u px each). The word stays in the DOM as
   visually hidden text; the drawing is aria-hidden. */
const LABEL_WORDS = {};
function LetteringLabel({ word, className = "underlay-nav__toggle-word" }) {
  const w = (LABEL_WORDS[word] ||= letteringWord(word));
  return (
    <>
      <svg className={className} viewBox={w.viewBox} style={{ "--ul-w": w.width }} fill="currentColor" stroke="currentColor" strokeWidth="3" strokeLinejoin="round" aria-hidden="true" focusable="false">
        {w.paths.map(({ d, dx, stroke, evenodd }, i) => (
          <path key={i} d={d} transform={dx ? `translate(${dx} 0)` : undefined} fillRule={evenodd ? "evenodd" : undefined} fill={stroke ? "none" : undefined} strokeWidth={stroke ? "10.5" : undefined} />
        ))}
      </svg>
      <span className="underlay-nav__toggle-sr">{word}</span>
    </>
  );
}

/** The line at the foot of the menu. */
export const MENU_CREDIT = "Made by the Europa team in room 323";

export default function UnderlayNav({ mainSelector = "[data-main]", externalTrigger = false }) {
  const rootRef = useRef(null);
  const listRef = useRef(null);
  const pillRef = useRef(null);
  // The init's close routine, for the route-change effect below. Null while unbound.
  const closeMenuRef = useRef(null);
  // Read by the init at event time, so a route change in or out of an embedded
  // workspace never re-binds (or kills mid-close) the timeline.
  const externalTriggerRef = useRef(externalTrigger);
  const location = useLocation();

  /* The row of the current route carries the resource's current-page state:
     aria-current="page" and the w--current class (the accent row). */
  const currentPath = location.pathname || "/";
  const isActive = (target) =>
    currentPath === target ||
    (target === "/Home" && currentPath === "/");


  /* ── Magnetic hover pill ────────────────────────────────────────────
   * One absolutely-positioned accent block lives inside the menu list.
   * On mount (and whenever the route changes) it sits over the current
   * page's link. On `mouseover` of any link it glides to that link; on
   * `mouseleave` of the whole list it returns to the active link. Only
   * ever ONE highlighted item — wherever the cursor is.
   *
   * The glide is liquid: the edge facing the target leads (0.3 s), the
   * far edge trails (0.5 s), both power3.out, so the pill stretches like
   * a drop between rows and settles exactly on the target row. Reduced
   * motion: instant. Devices without hover: it stays on the current row
   * (keyboard focus still moves it). The pill is a window over the rows:
   * its light label copy is shifted by -top on every frame (writes only;
   * rows are measured once per move, not per frame). */
  useEffect(() => {
    const list = listRef.current;
    const pill = pillRef.current;
    if (!list || !pill) return;
    const clone = pill.querySelector(".underlay-nav__pill-clone");
    const media = (query) => {
      try { return window.matchMedia?.(query)?.matches === true; } catch { return false; }
    };

    const findActive = () =>
      list.querySelector(".underlay-nav__link-large.w--current");

    const edges = { top: 0, bottom: 0 };
    let shown = false;
    let edgeTweens = [];
    const render = () => {
      const top = edges.top;
      pill.style.transform = `translate3d(0, ${top}px, 0)`;
      pill.style.height = `${Math.max(0, edges.bottom - top)}px`;
      if (clone) clone.style.transform = `translate3d(0, ${-top}px, 0)`;
    };
    const killEdges = () => {
      edgeTweens.forEach((tween) => tween.kill());
      edgeTweens = [];
    };
    const fade = (opacity, animate) => {
      if (animate) gsap.to(pill, { opacity, duration: 0.28, ease: "power3.out", overwrite: "auto" });
      else gsap.set(pill, { opacity, overwrite: "auto" });
    };

    /* Row edges in the list's coordinates (the pill's containing block).
     * Open menu: the rendered rects. The reveal only moves rows sideways
     * (xPercent) and the page slide is horizontal, so the vertical delta is
     * exact, whatever offsetParent chain, scroll or late font swap the rows
     * have. Closed or mid-close: layout offsets (the rows carry the
     * timeline's transforms then; WebKit phones drew a thin bar under Query
     * from rects). */
    const measureRow = (link) => {
      const open = document.body?.getAttribute?.("data-menu-status") === "open";
      const linkRect = link.getBoundingClientRect();
      if (open && linkRect.height > 0) {
        const listRect = list.getBoundingClientRect();
        const top = linkRect.top - listRect.top - (list.clientTop || 0);
        return { top, bottom: top + linkRect.height };
      }
      let top = 0;
      let el = link;
      while (el && el !== list && list.contains(el)) {
        top += el.offsetTop;
        el = el.offsetParent;
      }
      if (el !== list) top = linkRect.top - list.getBoundingClientRect().top;
      return { top, bottom: top + (link.offsetHeight || linkRect.height) };
    };

    /* The row the pill should rest on once settled. */
    let target = null;
    let pillSettleTimer = 0;
    /* After a glide lands (or the open leg ends), check the pill against the
     * row's live edges and snap if anything moved underneath it. */
    const verify = () => {
      if (!target || !target.isConnected || !shown) return;
      const { top, bottom } = measureRow(target);
      if (Math.abs(top - edges.top) > 0.5 || Math.abs(bottom - edges.bottom) > 0.5) {
        killEdges();
        edges.top = top;
        edges.bottom = bottom;
        render();
      }
    };

    const positionPillOver = (link, animate = true) => {
      target = link || null;
      const still = !animate || media("(prefers-reduced-motion: reduce)");
      killEdges();
      if (!link) {
        shown = false;
        fade(0, !still);
        return;
      }
      /* Layout offsets, not getBoundingClientRect: while the menu is closed
       * (or mid-reveal) the rows carry the timeline's transforms, which would
       * misplace the pill (WebKit phones: a thin bar under Query). */
      const { top, bottom } = measureRow(link);
      if (still || !shown) {
        edges.top = top;
        edges.bottom = bottom;
        render();
      } else {
        const down = top > edges.top;
        const LEAD = 0.3;
        const TRAIL = 0.5;
        edgeTweens = [
          gsap.to(edges, { top, duration: down ? TRAIL : LEAD, ease: "power3.out", onUpdate: render }),
          gsap.to(edges, { bottom, duration: down ? LEAD : TRAIL, ease: "power3.out", onUpdate: render }),
        ];
        edgeTweens[down ? 0 : 1]?.eventCallback?.("onComplete", verify);
      }
      if (!shown) fade(1, !still);
      shown = true;
    };

    /* The light copy follows each row's reveal (the open/close timeline
     * writes transform, opacity and visibility on the rows): copied per
     * frame, style strings only, while the menu is not closed. */
    const realRows = [...list.children].filter((el) => el.hasAttribute?.("data-reveal-l"));
    const cloneRows = clone ? [...clone.children] : [];
    const syncRows = () => {
      for (let i = 0; i < cloneRows.length; i++) {
        const from = realRows[i]?.style;
        const to = cloneRows[i].style;
        if (!from) continue;
        if (to.transform !== from.transform) to.transform = from.transform;
        if (to.opacity !== from.opacity) to.opacity = from.opacity;
        if (to.visibility !== from.visibility) to.visibility = from.visibility;
      }
    };
    gsap.ticker.add(syncRows);

    /* The initial snap is NOT animated (would otherwise slide-in from
     * top:0 on the first open). Subsequent positioning is. */
    positionPillOver(findActive(), false);

    const handleOver = (e) => {
      if (media("(hover: none)")) return;
      const link = e.target.closest(".underlay-nav__link-large");
      if (!link || !list.contains(link)) return;
      positionPillOver(link);
    };
    /* Keyboard focus moves the pill too (the rows draw no focus ring of
     * their own): a row reached by keyboard (:focus-visible) gets it, and
     * keeps it when the cursor leaves the list. A browser without
     * :focus-visible treats every focus as visible. */
    const keyboardRow = (el) => {
      const link = el?.closest?.(".underlay-nav__link-large");
      if (!link || !list.contains(link)) return null;
      try { return link.matches(":focus-visible") ? link : null; } catch { return link; }
    };
    const handleLeave = () => {
      positionPillOver(keyboardRow(document.activeElement) || findActive());
    };
    const handleFocusIn = (e) => {
      const link = keyboardRow(e.target);
      if (link) positionPillOver(link);
    };
    const handleFocusOut = (e) => {
      if (!list.contains(e.relatedTarget)) positionPillOver(findActive());
    };

    list.addEventListener("mouseover", handleOver);
    list.addEventListener("mouseleave", handleLeave);
    list.addEventListener("focusin", handleFocusIn);
    list.addEventListener("focusout", handleFocusOut);

    /* Re-snap (no animation) on viewport resize, whenever the rows change
     * size (fonts landing, WebKit phones settling late) and each time the
     * panel opens, so the first open after a load is right too. */
    const onResize = () => positionPillOver(findActive(), false);
    window.addEventListener("resize", onResize);
    let rowsObserver = null;
    try {
      if (typeof ResizeObserver === "function") {
        rowsObserver = new ResizeObserver(() => onResize());
        rowsObserver.observe(list);
      }
    } catch { rowsObserver = null; }
    let openObserver = null;
    try {
      if (typeof MutationObserver === "function") {
        openObserver = new MutationObserver(() => {
          if (document.body.getAttribute("data-menu-status") !== "open") return;
          onResize();
          /* Once the open leg has landed (~1.05 s), re-check against the
           * settled rows: the hovered row if the pointer is on the list. */
          clearTimeout(pillSettleTimer);
          pillSettleTimer = setTimeout(() => {
            const hovered = list.matches(":hover") ? list.querySelector(".underlay-nav__link-large:hover") : null;
            if (hovered && hovered !== target && !media("(hover: none)")) positionPillOver(hovered);
            else verify();
          }, 1150);
        });
        openObserver.observe(document.body, { attributes: true, attributeFilter: ["data-menu-status"] });
      }
    } catch { openObserver = null; }
    let fontsLive = true;
    try { document.fonts?.ready?.then(() => { if (fontsLive) onResize(); }); } catch { /* No FontFaceSet. */ }

    return () => {
      list.removeEventListener("mouseover", handleOver);
      list.removeEventListener("mouseleave", handleLeave);
      list.removeEventListener("focusin", handleFocusIn);
      list.removeEventListener("focusout", handleFocusOut);
      window.removeEventListener("resize", onResize);
      rowsObserver?.disconnect();
      openObserver?.disconnect();
      fontsLive = false;
      clearTimeout(pillSettleTimer);
      gsap.ticker.remove(syncRows);
      killEdges();
      gsap.killTweensOf(pill);
    };
  }, [currentPath]);

  useEffect(() => {
    externalTriggerRef.current = externalTrigger;
  }, [externalTrigger]);

  /* The resource init, once after mount. */
  useEffect(() => initFixedUnderlayNavigation(rootRef.current, {
    mainSelector,
    isExternal: () => externalTriggerRef.current,
    exposeClose: (close) => { closeMenuRef.current = close; },
  }), [mainSelector]);

  /* Close the menu on any navigation (Back/Forward, a link outside the
     menu, programmatic navigate()) through the resource toggle. Keyed on
     `location`, which changes identity on every navigation. */
  useEffect(() => {
    closeMenuRef.current?.();
  }, [location]);

  return (
    <div ref={rootRef} className={`underlay-nav-root${externalTrigger ? " underlay-nav-root--external" : ""}`}>
      <style>{UNDERLAY_NAV_CSS}</style>
      <div className="underlay-nav">
        <header className="underlay-nav__header">
          <div className="underlay-nav__bar">
            <div className="underlay-nav__container">
              {/* The logo in the resource's logo slot. indago-wordmark and
                  indago-wordmark__name are the brand-mark hooks pages already
                  use (Screener and live globe sections hide it, the company
                  page recolours it, print hides it). */}
              <a href="#/Home" className="underlay-nav__logo indago-wordmark">
                <LogoPlanet />
                <LetteringLabel word="Europa" className="underlay-nav__logo-word" />
              </a>
              <button data-underlay-nav-toggle aria-expanded="false" aria-label="open menu" className="underlay-nav__toggle" type="button">
                <span className="underlay-nav__toggle-text">
                  <span className="underlay-nav__toggle-label"><LetteringLabel word="Dashboard" /></span>
                  <span className="underlay-nav__toggle-label"><LetteringLabel word="Close" /></span>
                </span>
                <span className="underlay-nav__toggle-icon">
                  <span className="underlay-nav__toggle-bar"></span>
                  <span className="underlay-nav__toggle-bar"></span>
                </span>
              </button>
            </div>
          </div>
        </header>
        <nav data-underlay-nav-menu className="underlay-nav__menu" role="dialog" aria-modal="true" aria-label="Dashboard navigation" aria-hidden="true">
          <div className="underlay-nav__inner">
            <ul ref={listRef} className="underlay-nav__list">
              {/* Magnetic hover pill — absolutely positioned over whichever
                  link the cursor is on (defaults to the active route). Lives
                  inside the <ul> as an aria-hidden <li> so the markup is
                  valid HTML while its `position: absolute` keeps it out of
                  the list's flex flow. It is a window above the rows: inside
                  it, an inert light copy of the row labels, laid out like the
                  rows and shifted by the pill's offset, shows the covered text
                  in the light ink at every frame of a glide. */}
              <li
                ref={pillRef}
                className="underlay-nav__hover-pill"
                aria-hidden="true"
              >
                <div className="underlay-nav__pill-clone" inert="">
                  {menuItems().map(({ route, label }) => (
                    <div key={route} className="underlay-nav__pill-row">
                      <span className="underlay-nav__pill-link w-inline-block">
                        <span className="underlay-nav__pill-label">{label}</span>
                      </span>
                    </div>
                  ))}
                </div>
              </li>
              {/* One row per page (navItems.js). */}
              {menuItems().map(({ route, label }) => (
                <li data-reveal-l key={route}>
                  <a
                    href={`#${route}`}
                    onPointerEnter={() => prefetchRoute(route)}
                    onFocus={() => prefetchRoute(route)}
                    aria-current={isActive(route) ? "page" : undefined}
                    className={
                      "underlay-nav__link-large w-inline-block" +
                      (isActive(route) ? " w--current" : "")
                    }
                  >
                    <span className="underlay-nav__link-label">{label}</span>
                  </a>
                </li>
              ))}
            </ul>
            <div className="underlay-nav__bottom">
              <div className="underlay-nav__bottom-col">
                {/* The credit line (owner 2026-11-22), in the slot of the resource's faded label. */}
                <div data-reveal-s>
                  <span className="underlay-nav__link-small is--faded">{MENU_CREDIT}</span>
                </div>
              </div>
              <div className="underlay-nav__bottom-border"></div>
            </div>
          </div>
        </nav>
        <div data-underlay-nav-overlay="" className="underlay-nav__overlay">
          <div className="underlay-nav__dark"></div>
          <div className="underlay-nav__borders">
            <div className="underlay-nav__border-row">
              <div className="underlay-nav__border"></div>
              <div className="underlay-nav__corner"></div>
            </div>
            <div className="underlay-nav__border-row">
              <div className="underlay-nav__corner is--bottom"></div>
              <div className="underlay-nav__border"></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
