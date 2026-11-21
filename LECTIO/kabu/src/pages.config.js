/** Explicit route registry. Modules load only when their route renders. */
import { lazy as reactLazy } from 'react';
import { loadRoute } from './lib/routeRecovery.js';
import { registerRouteImporters } from './lib/routePrefetch.js';
import __Layout from './Layout.jsx';
const lazy = importer => reactLazy(() => loadRoute(importer));

const LectioHome = lazy(() => import('./pages/LectioHome'));
const Home = lazy(() => import('./pages/Home'));
const GenerateReport = lazy(() => import('./pages/GenerateReport'));
const ReportViewer = lazy(() => import('./pages/ReportViewer'));
const DeepResearch = lazy(() => import('./pages/DeepResearch'));

// Route code the menu may prefetch (same modules as below). Deep Research is
// left out: its page owns its own workspace preload.
registerRouteImporters({
    "/Home": () => import('./pages/LectioHome'),
    "/Reports": () => import('./pages/Home'),
});

export const PAGES = {
    "Home": LectioHome,      // landing: one word
    "Reports": Home,         // the research-report home
    "GenerateReport": GenerateReport,
    "Viewer": ReportViewer,
    "DeepResearch": DeepResearch,   // Deep Research workspace (embedded at /xyz)
}

export const pagesConfig = {
    mainPage: "Home",
    Pages: PAGES,
    Layout: __Layout,
};
