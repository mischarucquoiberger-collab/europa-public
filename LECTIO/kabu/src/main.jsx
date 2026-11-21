import ReactDOM from 'react-dom/client'
import App from '@/App.jsx'
import '@/index.css'
import { observePreloadFailure } from './lib/routeRecovery.js'

window.addEventListener('vite:preloadError', observePreloadFailure)

ReactDOM.createRoot(document.getElementById('root')).render(<App />)
