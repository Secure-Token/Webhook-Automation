import { useState } from 'react'
import { keys, setKeys } from './api.js'
import Dashboard from './pages/Dashboard.jsx'
import Tasks from './pages/Tasks.jsx'
import Webhooks from './pages/Webhooks.jsx'
import Events from './pages/Events.jsx'
import Deliveries from './pages/Deliveries.jsx'
import Claims from './pages/Claims.jsx'

const PAGES = { Dashboard, Tasks, Webhooks, Events, Deliveries, Claims }

export default function App() {
  const [page, setPage] = useState('Dashboard')
  const [dev, setDev] = useState(keys.devKey)
  const [admin, setAdmin] = useState(keys.adminKey)
  const Page = PAGES[page]
  return (
    <div className="app">
      <header>
        <h1>Secure Tokens <span>Webhook Automation Prototype</span></h1>
        <nav>{Object.keys(PAGES).map(p => (
          <button key={p} className={p === page ? 'active' : ''} onClick={() => setPage(p)}>{p}</button>))}
        </nav>
        <div className="keys">
          <input title="Developer API key" placeholder="developer API key" value={dev}
                 onChange={e => { setDev(e.target.value); setKeys(e.target.value, admin) }} />
          <input title="Admin API key (adjudicate, settle, retry)" placeholder="admin API key" type="password" value={admin}
                 onChange={e => { setAdmin(e.target.value); setKeys(dev, e.target.value) }} />
        </div>
      </header>
      <div className="banner">
        SIMULATED PROTOTYPE: AI execution, snapshots, evaluation, settlement and the reserve are mock demo data.
        This demonstrates only the proposed webhook automation layer, not the full Secure Tokens platform.
      </div>
      <main><Page /></main>
    </div>
  )
}
