import { useState, Component, Suspense } from 'react'
import { Toaster } from "@/components/ui/toaster"
import NavigationTracker from '@/lib/NavigationTracker'
import { pagesConfig } from './pages.config'
import { HashRouter as Router, Route, Routes, Navigate } from 'react-router-dom';
import PageNotFound from './lib/PageNotFound';
import { CircleTransitionProvider } from '@/components/CircleTransition';
import IndagoLoader from '@/components/IndagoLoader';
import RouteBoundary from '@/components/RouteBoundary';
import EuropaSplash from '@/components/EuropaSplash';

/* The app routes by hash (#/Home), so the shell's real address path is only
   ever "/" (or "/index.html"). Any other path that reaches the shell (for
   example /no-such-page, served the same index.html) has no page here. */
export function isUnknownShellPath(pathname) {
  const path = String(pathname ?? '/');
  return !(path === '' || path === '/' || path === '/index.html');
}

class ErrorBoundary extends Component {
  state = { hasError: false, error: null };
  static getDerivedStateFromError(error) { return { hasError: true, error }; }
  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <div className="fixed inset-0 flex items-center justify-center bg-[#0e1420] text-[#f4f5f7]">
        <div className="text-center max-w-md px-6">
          <p className="text-lg font-semibold mb-2">Something went wrong</p>
          <p className="text-sm text-white/60 mb-4">Please reload to recover.</p>
          <button onClick={() => { this.setState({ hasError: false, error: null }); window.location.hash = "#/Home"; }}
            className="px-4 py-2 rounded-lg bg-[#f4f5f7] text-[#0e1420] hover:bg-white text-sm font-medium transition-colors">
            Go Home
          </button>
          <button onClick={() => window.location.reload()} className="ml-3 px-4 py-2 rounded-lg border border-white/25 text-sm">Reload page</button>
        </div>
      </div>
    );
  }
}

const { Pages, Layout, mainPage } = pagesConfig;
const HOME_ROUTE = `/${mainPage}`;

// Every page is navy: the loader paints the page ink so a cold load or a lazy
// chunk never shows a white screen.
function RouteLoading() {
  return <div role="status" aria-live="polite" className="fixed inset-0 z-[60] flex items-center justify-center bg-[#0e1420]">
    <IndagoLoader label="Loading page…" tone="dark" />
  </div>;
}

const LayoutWrapper = ({ children, currentPageName }) => (
  <Layout currentPageName={currentPageName}>
    <RouteBoundary key={currentPageName}><Suspense fallback={<RouteLoading />}>{children}</Suspense></RouteBoundary>
  </Layout>
);

function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to={HOME_ROUTE} replace />} />
      {Object.entries(Pages).map(([path, Page]) => (
        <Route
          key={path}
          path={`/${path}`}
          element={
            <LayoutWrapper currentPageName={path}>
              <Page />
            </LayoutWrapper>
          }
        />
      ))}
      <Route path="*" element={<PageNotFound />} />
    </Routes>
  );
}

function App() {
  // /no-such-page reaches the shell through the host's index.html fallback; it is a 404, not Home.
  const [serverPath] = useState(() => {
    try { return window.location.pathname; } catch { return '/'; }
  });
  const unknownPath = isUnknownShellPath(serverPath);

  return (
    <ErrorBoundary>
      {/* The splash plays over the app on every page load and lifts onto the page beneath. */}
      <EuropaSplash />
      <Router>
        <CircleTransitionProvider>
          <NavigationTracker />
          {unknownPath ? <PageNotFound serverPath={serverPath} /> : <AppRoutes />}
        </CircleTransitionProvider>
      </Router>
      <Toaster />
    </ErrorBoundary>
  )
}

export default App
