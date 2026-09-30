import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import { consumeAddressFromUrl } from './services/localAiConfig.js'
import './styles.css'

// Read `?ai=<url>` before the first render, so the very first health probe
// already goes to the address the shared link names rather than to whatever was
// stored from a previous session.
consumeAddressFromUrl()

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
