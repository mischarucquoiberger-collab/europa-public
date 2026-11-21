/**
 * The main app (the shell) that frames this desk on its Home page. A direct visit is
 * sent there, and "Full report" opens its Reports page. NEXT_PUBLIC_ values are
 * inlined when the app is built, so a production build keeps the value it was built with.
 */
export const shellUrl = (process.env.NEXT_PUBLIC_EUROPA_URL || "http://127.0.0.1:3000").replace(/\/+$/, "");
