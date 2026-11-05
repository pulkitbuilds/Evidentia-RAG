import { NavLink, Route, Routes } from 'react-router-dom'
import EditorPage from './pages/EditorPage.jsx'
import LibraryPage from './pages/LibraryPage.jsx'
import HistoryPage from './pages/HistoryPage.jsx'
import ResearchPage from './pages/ResearchPage.jsx'
import VerifyPage from './pages/VerifyPage.jsx'
import AboutPage from './pages/AboutPage.jsx'
import CasesPage from './pages/CasesPage.jsx'
import { useCase } from './CaseContext.jsx'
import { useAuth } from './AuthContext.jsx'

function Tab({ to, children }) {
  return (
    <NavLink to={to} end={to === '/'} className={({ isActive }) => 'tab' + (isActive ? ' tab-active' : '')}>
      {children}
    </NavLink>
  )
}

function CaseSwitcher() {
  const { cases, activeCaseId, setActiveCaseId, loading, error } = useCase()

  if (loading) return <div className="case-switcher muted">Loading cases…</div>
  if (error) return null

  if (cases.length === 0) {
    return (
      <NavLink to="/cases" className="case-switcher-empty">
        + Create your first case
      </NavLink>
    )
  }

  return (
    <div className="case-switcher">
      <span className="case-switcher-label">Case</span>
      <select value={activeCaseId || ''} onChange={(e) => setActiveCaseId(e.target.value)}>
        {cases.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </select>
      <NavLink to="/cases" className="case-switcher-manage">
        Manage
      </NavLink>
    </div>
  )
}

function UserMenu() {
  const { user, logout } = useAuth()
  if (!user) return null
  return (
    <div className="user-menu">
      <span className="user-menu-email">{user.email}</span>
      <button type="button" className="btn-secondary" onClick={logout}>
        Log Out
      </button>
    </div>
  )
}

export default function App() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Evidentia</h1>
        <span className="tagline">Evidence-First Research &amp; Writing</span>
        <div className="header-right">
          <CaseSwitcher />
          <UserMenu />
        </div>
      </header>

      <nav className="tab-nav">
        <Tab to="/">Draft</Tab>
        <Tab to="/library">Library</Tab>
        <Tab to="/research">Research</Tab>
        <Tab to="/verify">Verify Source</Tab>
        <Tab to="/history">Case Log</Tab>
        <Tab to="/cases">Cases</Tab>
        <Tab to="/about">How It Works</Tab>
      </nav>

      <Routes>
        <Route path="/" element={<EditorPage />} />
        <Route path="/library" element={<LibraryPage />} />
        <Route path="/research" element={<ResearchPage />} />
        <Route path="/verify" element={<VerifyPage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/cases" element={<CasesPage />} />
        <Route path="/about" element={<AboutPage />} />
      </Routes>
    </div>
  )
}
