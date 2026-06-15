import { useEffect, useState } from 'react'
import GraphCanvas from './components/GraphCanvas.jsx'
import ChatPanel from './components/ChatPanel.jsx'

export default function App() {
  const [graphData, setGraphData] = useState(null)
  const [graphError, setGraphError] = useState(null)
  const [trace, setTrace] = useState(null)
  const [traceInput, setTraceInput] = useState('')
  const [traceLoading, setTraceLoading] = useState(false)
  const [traceError, setTraceError] = useState(null)

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
          <PipeSearch
            value={traceInput}
            onChange={setTraceInput}
            onTrace={runTrace}
            onClear={clearTrace}
            loading={traceLoading}
            error={traceError}
            trace={trace}
          />
          <div style={{ flex: 1, overflow: 'hidden', position: 'relative' }}>
            {graphError
              ? <div style={styles.error}>Graph load failed: {graphError}</div>
              : graphData
                ? <GraphCanvas nodes={graphData.nodes} edges={graphData.edges} trace={trace} />
                : <div style={styles.loading}>Loading network graph…</div>
            }
          </div>
        </div>
        <div style={styles.chatPane}>
          <ChatPanel onPipeResolved={runTrace} />
        </div>
      </div>
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
