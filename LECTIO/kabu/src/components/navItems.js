/* Dashboard menu entries, in order. Every row is a working link to a page of
 * this app (pages.config.js). */

/** @typedef {{ route: string, label: string }} MenuItem */
/** @type {ReadonlyArray<Readonly<MenuItem>>} */
export const MENU_ITEMS = Object.freeze([
  Object.freeze({ route: "/Home", label: "Home" }),
  Object.freeze({ route: "/Reports", label: "Reports" }),
  Object.freeze({ route: "/DeepResearch", label: "Callisto" }),
]);

/** The menu as shown. */
export function menuItems() {
  return MENU_ITEMS;
}
