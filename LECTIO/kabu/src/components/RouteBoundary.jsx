import { Component } from 'react';
import { isChunkFailure } from '../lib/routeRecovery.js';

export default class RouteBoundary extends Component {
  state = { error: null };
  static getDerivedStateFromError(error) { return { error }; }

  render() {
    if (!this.state.error) return this.props.children;
    const chunk = isChunkFailure(this.state.error);
    return <section role="alert" className="mx-auto flex min-h-[50vh] max-w-lg flex-col items-center justify-center gap-4 p-8 text-center text-[#f4f5f7]">
      <h1 className="text-xl font-semibold">{chunk ? 'This page could not finish loading' : 'This page encountered a problem'}</h1>
      <p className="text-sm opacity-75">{chunk
        ? 'The connection may have dropped, or a new release may be available.'
        : 'You can return to another page or reload to try again.'}</p>
      <p className="text-sm opacity-75">Reloading does not cancel server-side research. Copy any unsaved text before reloading.</p>
      <div className="flex flex-wrap justify-center gap-3">
        <button type="button" className="rounded border border-white/25 px-4 py-2" onClick={() => { window.location.hash = '#/Home'; }}>Go Home</button>
        <button type="button" className="rounded bg-[#f4f5f7] px-4 py-2 text-[#0e1420]" onClick={() => window.location.reload()}>Reload page</button>
      </div>
    </section>;
  }
}
