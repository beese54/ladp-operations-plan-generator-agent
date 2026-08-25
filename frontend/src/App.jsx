import { useEffect, useState } from 'react'
import GraphCanvas from './components/GraphCanvas.jsx'
import CalendarView from './components/CalendarView.jsx'
import ChatPanel from './components/ChatPanel.jsx'
import CrewPage from './components/CrewPage.jsx'

// Hash-based routing for the crew page: /crew/:operationId lives at
// http://localhost:5174/#/crew/OPS-XXXXXXXX — no React Router needed,
// same zero-dep approach as the rest of the app.
function useCrewRoute() {
  const [crewOpId, setCrewOpId] = useState(() => {
    const h = window.location.hash
    return h.startsWith('#/crew/') ? h.slice(7) : null
  })
  useEffect(() => {
    const handler = () => {
      const h = window.location.hash
      setCrewOpId(h.startsWith('#/crew/') ? h.slice(7) : null)
    }
    window.addEventListener('hashchange', handler)
    return () => window.removeEventListener('hashchange', handler)
  }, [])
  return crewOpId
}

export default function App() {
  const crewOpId = useCrewRoute()

  // If we're on a crew page, render that standalone — no graph/calendar/chat
  if (crewOpId) return <CrewPage operationId={crewOpId} />

  const [graphData, setGraphData] = useState(null)
  const [graphError, setGraphError] = useState(null)
  const [trace, setTrace] = useState(null)
  const [traceInput, setTraceInput] = useState('')
  const [traceLoading, setTraceLoading] = useState(false)
  const [traceError, setTraceError] = useState(null)

  // Left panel: which view is showing, auto-switched by chat activity
  // (schedule question answered / booking confirmed -> calendar; pipe
  // question resolved -> back to graph) as well as manual toolbar tabs.
  const now = new Date()
  const [leftView, setLeftView] = useState('graph')
  const [calendarYear, setCalendarYear] = useState(now.getFullYear())
  const [calendarMonth, setCalendarMonth] = useState(now.getMonth() + 1)

  useEffect(() => {
    fetch('/api/v1/graph')
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(setGraphData)
      .catch(e => setGraphError(e.message))
  }, [])

  const runTrace = (idArg) => {
    // idArg may be a string (chat-driven) or absent/event (button/Enter) → fall back to the input box
    const id = (typeof idArg === 'string' ? idArg : traceInput).trim()
    if (!id) return
    setLeftView('graph')         // a pipe question is being answered — show the graph
    setTraceInput(id)            // reflect the traced pipe in the search box
    setTraceLoading(true)
    setTraceError(null)
    fetch(`/api/v1/trace/${encodeURIComponent(id)}`)
      .then(r => {
        if (!r.ok) return r.json().then(b => Promise.reject(b.detail || `HTTP ${r.status}`))
        return r.json()
      })
      .then(data => { setTrace(data); setTraceLoading(false) })
      .catch(err => { setTraceError(String(err)); setTraceLoading(false) })
  }

  const clearTrace = () => {
    setTrace(null)
    setTraceError(null)
    setTraceInput('')
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      <header style={styles.header}>
        <span style={styles.headerTitle}>💧 Water Network Operations</span>
        {graphData && (
          <span style={styles.headerMeta}>
            {graphData.nodes.length} nodes · {graphData.edges.length} pipes
          </span>
        )}
      </header>

      <div style={styles.body}>
        <div style={styles.graphPane}>
          <div style={styles.viewTabRow}>
            <ViewTabs leftView={leftView} onChange={setLeftView} />
          </div>
          {leftView === 'graph' && (
            <PipeSearch
              value={traceInput}
              onChange={setTraceInput}
              onTrace={runTrace}
              onClear={clearTrace}
              loading={traceLoading}
              error={traceError}
              trace={trace}
            />
          )}
          <div style={{ flex: 1, overflow: 'hidden', position: 'relative' }}>
            {/* Both views stay mounted permanently and are toggled via CSS, not
                conditional rendering — GraphCanvas's cose-bilkent layout is
                randomized (randomize: true), so unmounting/remounting it on every
                tab switch reshuffled the whole graph into a new random layout
                each time, which read as "a different pipe is selected" even
                though the trace itself never changed. Keeping it mounted
                preserves both its layout and Cytoscape instance across switches. */}
            <div style={{ display: leftView === 'graph' ? 'block' : 'none', height: '100%' }}>
              {graphError
                ? <div style={styles.error}>Graph load failed: {graphError}</div>
                : graphData
                  ? <GraphCanvas nodes={graphData.nodes} edges={graphData.edges} trace={trace} />
                  : <div style={styles.loading}>Loading network graph…</div>}
            </div>
            <div style={{ display: leftView === 'calendar' ? 'block' : 'none', height: '100%' }}>
              <CalendarView
                year={calendarYear}
                month={calendarMonth}
                onNavigate={(y, m) => { setCalendarYear(y); setCalendarMonth(m) }}
              />
            </div>
          </div>
        </div>
        <div style={styles.chatPane}>
          <ChatPanel
            onPipeResolved={runTrace}
            onScheduleUpdated={(y, m) => {
              setLeftView('calendar')
              setCalendarYear(y)
              setCalendarMonth(m)
            }}
          />
        </div>
      </div>
    </div>
  )
}

function ViewTabs({ leftView, onChange }) {
  return (
    <div style={styles.viewTabs}>
      <button
        style={{ ...styles.viewTabBtn, ...(leftView === 'graph' ? styles.viewTabActive : {}) }}
        onClick={() => onChange('graph')}
      >
        Network Graph
      </button>
      <button
        style={{ ...styles.viewTabBtn, ...(leftView === 'calendar' ? styles.viewTabActive : {}) }}
        onClick={() => onChange('calendar')}
      >
        Ops Calendar
      </button>
    </div>
  )
}

function PipeSearch({ value, onChange, onTrace, onClear, loading, error, trace }) {
  const onKey = e => { if (e.key === 'Enter') onTrace() }
  return (
    <div style={styles.toolbar}>
      <input
        style={styles.traceInput}
        placeholder="Enter pipe ID to trace…"
        value={value}
        onChange={e => onChange(e.target.value)}
        onKeyDown={onKey}
        disabled={loading}
      />
      <button style={styles.traceBtn} onClick={onTrace} disabled={loading || !value.trim()}>
        {loading ? '…' : 'Trace'}
      </button>
      {trace && (
        <button style={styles.clearBtn} onClick={onClear}>Clear</button>
      )}
      {trace && !error && (
        <span style={styles.traceStats}>
          <span style={styles.statPipe}>{trace.pipe_ids.length} pipes</span>
          <span style={styles.statValve}>{trace.valve_ids.length} valves</span>
          {trace.tail_valve_ids.length > 0 && (
            <span style={styles.statTail}>{trace.tail_valve_ids.length} tail-end</span>
          )}
        </span>
      )}
      {error && <span style={styles.traceError}>{error}</span>}
    </div>
  )
}

const styles = {
  header: {
    background: '#1e293b',
    borderBottom: '1px solid #334155',
    padding: '10px 18px',
    display: 'flex',
    alignItems: 'center',
    gap: '16px',
    flexShrink: 0,
  },
  headerTitle: { fontWeight: 700, fontSize: '15px', color: '#38bdf8' },
  headerMeta: { fontSize: '12px', color: '#64748b' },
  body: { display: 'flex', flex: 1, overflow: 'hidden' },
  graphPane: { flex: '0 0 60%', borderRight: '1px solid #334155', display: 'flex', flexDirection: 'column', overflow: 'hidden' },
  chatPane: { flex: '0 0 40%', display: 'flex', flexDirection: 'column', overflow: 'hidden' },
  loading: { display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#64748b' },
  error: { display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#f87171', padding: '24px', textAlign: 'center' },

  // Left-panel view switcher (graph <-> calendar)
  viewTabRow: {
    display: 'flex', padding: '7px 12px 0',
    background: '#1e293b', flexShrink: 0,
  },
  viewTabs: { display: 'flex', gap: 2 },
  viewTabBtn: {
    background: 'none', border: '1px solid #334155', borderBottom: 'none',
    borderRadius: '5px 5px 0 0',
    color: '#94a3b8', fontSize: 12, fontWeight: 600,
    padding: '5px 12px', cursor: 'pointer',
  },
  viewTabActive: { background: '#0f172a', color: '#f59e0b' },

  // Pipe trace toolbar
  toolbar: {
    display: 'flex', alignItems: 'center', gap: 8,
    padding: '7px 12px',
    background: '#1e293b',
    borderBottom: '1px solid #334155',
    flexShrink: 0,
  },
  traceInput: {
    flex: '0 0 180px',
    background: '#0f172a',
    border: '1px solid #334155',
    borderRadius: 5,
    color: '#e2e8f0',
    fontSize: 12,
    padding: '4px 8px',
    outline: 'none',
  },
  traceBtn: {
    background: '#f59e0b',
    border: 'none',
    borderRadius: 5,
    color: '#0f172a',
    fontWeight: 700,
    fontSize: 12,
    padding: '4px 12px',
    cursor: 'pointer',
  },
  clearBtn: {
    background: 'none',
    border: '1px solid #475569',
    borderRadius: 5,
    color: '#94a3b8',
    fontSize: 12,
    padding: '4px 10px',
    cursor: 'pointer',
  },
  traceStats: { display: 'flex', gap: 8, fontSize: 11, marginLeft: 4 },
  statPipe:  { color: '#f59e0b', fontWeight: 600 },
  statValve: { color: '#f59e0b' },
  statTail:  { color: '#ec4899', fontWeight: 600 },
  traceError: { color: '#f87171', fontSize: 11 },
}
