/**
 * CrewPage — mobile-first field crew interface.
 *
 * Standalone page at /crew/:operationId — no graph, no calendar.
 * Rendered by App.jsx when the URL hash starts with #/crew/
 *
 * Features:
 *  - Operation header (pipe, road, date window, progress bar)
 *  - Checklist with per-step dropdown (Pending / Done / Flagged)
 *  - Flagged spawns a note textbox + Send button
 *  - Notes log (scrollable, newest first)
 *  - Download PDF button
 *  - Collapsible AI assistant chat widget
 */

import { useEffect, useRef, useState } from 'react'

const STATUS_OPTIONS = [
  { value: 'PENDING', label: '⬜  Pending' },
  { value: 'DONE',    label: '✅  Done' },
  { value: 'FLAGGED', label: '🚩  Flagged' },
]

const PHASE_LABELS = {
  isolation:      'Isolation',
  alternate_feed: 'Alternate Feed',
  re_feed:        'Re-feed Check',
  notify:         'Notify Residents',
  verify:         'Verification',
}

function fmtDateTime(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString(undefined, {
      weekday: 'short', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch { return iso }
}

function fmtTime(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
  } catch { return iso }
}

// ── Main component ────────────────────────────────────────────────────────────

export default function CrewPage({ operationId }) {
  const [op, setOp] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [chatOpen, setChatOpen] = useState(false)

  const reload = () => {
    setLoading(true)
    setError(null)
    fetch(`/api/v1/crew/${operationId}`)
      .then(r => {
        if (!r.ok) return r.json().then(b => Promise.reject(b.detail || `HTTP ${r.status}`))
        return r.json()
      })
      .then(d => { setOp(d); setLoading(false) })
      .catch(e => { setError(String(e)); setLoading(false) })
  }

  useEffect(() => { reload() }, [operationId])

  if (loading) return <div style={s.fullPage}><div style={s.loading}>Loading operation…</div></div>
  if (error)   return <div style={s.fullPage}><div style={s.errorBox}>⚠️ {error}</div></div>
  if (!op)     return null

  const { total, done, flagged, percent_complete } = op.completion || {}

  return (
    <div style={s.fullPage}>
      {/* ── Header ── */}
      <div style={s.header}>
        <div style={s.headerTop}>
          <span style={s.logo}>💧</span>
          <div>
            <div style={s.headerPipe}>{op.pipe_id || 'Unknown pipe'}</div>
            {op.pipe_road && <div style={s.headerRoad}>{op.pipe_road}</div>}
          </div>
          <div style={{ ...s.classBadge, background: op.operation_class === 'EMERGENCY' ? '#7f1d1d' : '#1e3a5f' }}>
            {op.operation_class}
          </div>
        </div>
        <div style={s.headerDates}>
          {fmtDateTime(op.scheduled_start)} → {fmtDateTime(op.scheduled_end)}
        </div>
        <ProgressBar percent={percent_complete} done={done} flagged={flagged} total={total} />
      </div>

      {/* ── Body ── */}
      <div style={s.body}>
        <ChecklistSection
          operationId={operationId}
          checklist={op.checklist || []}
          onChanged={reload}
        />
        <NotesSection operationId={operationId} />
        <ActionRow operationId={operationId} onChatToggle={() => setChatOpen(v => !v)} />
      </div>

      {/* ── AI assistant overlay ── */}
      {chatOpen && (
        <AiAssistant
          operationId={operationId}
          pipeId={op.pipe_id}
          onClose={() => setChatOpen(false)}
        />
      )}
    </div>
  )
}

// ── Progress bar ──────────────────────────────────────────────────────────────

function ProgressBar({ percent, done, flagged, total }) {
  const pct = Math.min(100, Math.max(0, percent || 0))
  return (
    <div style={s.progressWrap}>
      <div style={s.progressTrack}>
        <div style={{ ...s.progressFill, width: `${pct}%` }} />
      </div>
      <div style={s.progressLabel}>
        {pct.toFixed(0)}% complete — {done}/{total} done
        {flagged > 0 && <span style={s.flagCount}> · {flagged} flagged</span>}
      </div>
    </div>
  )
}

// ── Checklist ─────────────────────────────────────────────────────────────────

function ChecklistSection({ operationId, checklist, onChanged }) {
  if (!checklist.length) return (
    <div style={s.section}>
      <div style={s.sectionTitle}>Checklist</div>
      <div style={{ color: '#64748b', fontSize: 13 }}>No checklist steps available yet.</div>
    </div>
  )

  // Group steps by phase for display
  const phases = []
  let currentPhase = null
  for (const step of checklist) {
    const phaseName = PHASE_LABELS[step.phase] || step.phase
    if (phaseName !== currentPhase) {
      currentPhase = phaseName
      phases.push({ name: phaseName, steps: [step] })
    } else {
      phases[phases.length - 1].steps.push(step)
    }
  }

  return (
    <div style={s.section}>
      <div style={s.sectionTitle}>Checklist</div>
      {phases.map(phase => (
        <div key={phase.name} style={s.phaseGroup}>
          <div style={s.phaseLabel}>{phase.name}</div>
          {phase.steps.map(step => (
            <StepRow
              key={step.step_number}
              step={step}
              operationId={operationId}
              onChanged={onChanged}
            />
          ))}
        </div>
      ))}
    </div>
  )
}

function StepRow({ step, operationId, onChanged }) {
  const [status, setStatus] = useState(step.status || 'PENDING')
  const [flagNote, setFlagNote] = useState(step.flag_note || '')
  const [saving, setSaving] = useState(false)
  const [noteError, setNoteError] = useState(null)

  const statusColor = status === 'DONE' ? '#22c55e' : status === 'FLAGGED' ? '#ef4444' : '#64748b'

  const handleStatusChange = async (newStatus) => {
    if (newStatus === 'FLAGGED') {
      // Just show the text box — don't save yet
      setStatus(newStatus)
      return
    }
    setSaving(true)
    try {
      const res = await fetch(`/api/v1/crew/${operationId}/steps/${step.step_number}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus }),
      })
      if (!res.ok) throw new Error(await res.text())
      setStatus(newStatus)
      onChanged()
    } catch (e) {
      setNoteError(String(e))
    } finally {
      setSaving(false)
    }
  }

  const handleFlagSend = async () => {
    if (!flagNote.trim()) { setNoteError('Please describe the issue.'); return }
    setSaving(true)
    setNoteError(null)
    try {
      const res = await fetch(`/api/v1/crew/${operationId}/steps/${step.step_number}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'FLAGGED', flag_note: flagNote.trim() }),
      })
      if (!res.ok) throw new Error(await res.text())
      onChanged()
    } catch (e) {
      setNoteError(String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ ...s.stepRow, borderLeft: `3px solid ${statusColor}` }}>
      <div style={s.stepTop}>
        <span style={s.stepNum}>{step.step_number}</span>
        <span style={s.stepDesc}>{step.description}</span>
        <select
          style={{ ...s.statusSelect, color: statusColor }}
          value={status}
          onChange={e => handleStatusChange(e.target.value)}
          disabled={saving}
        >
          {STATUS_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>

      {status === 'FLAGGED' && (
        <div style={s.flagBox}>
          <textarea
            style={s.flagTextarea}
            placeholder="Describe the issue or complication…"
            value={flagNote}
            onChange={e => setFlagNote(e.target.value)}
            rows={3}
          />
          {noteError && <div style={s.inputError}>{noteError}</div>}
          <div style={s.flagActions}>
            <button style={s.sendBtn} onClick={handleFlagSend} disabled={saving}>
              {saving ? 'Sending…' : 'Send Flag'}
            </button>
            <button style={s.cancelBtn} onClick={() => { setStatus(step.status || 'PENDING'); setNoteError(null) }}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {step.flag_note && status !== 'FLAGGED' && (
        <div style={s.savedNote}>🚩 {step.flag_note}</div>
      )}
    </div>
  )
}

// ── Notes section ─────────────────────────────────────────────────────────────

function NotesSection({ operationId }) {
  const [notes, setNotes] = useState([])
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)
  const [err, setErr] = useState(null)

  const loadNotes = () => {
    fetch(`/api/v1/crew/${operationId}/notes`)
      .then(r => r.ok ? r.json() : [])
      .then(data => setNotes(Array.isArray(data) ? data : []))
      .catch(() => {})
  }

  useEffect(() => { loadNotes() }, [operationId])

  const send = async () => {
    if (!message.trim()) return
    setSending(true)
    setErr(null)
    try {
      const res = await fetch(`/api/v1/crew/${operationId}/notes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: message.trim() }),
      })
      if (!res.ok) throw new Error(await res.text())
      setMessage('')
      loadNotes()
    } catch (e) {
      setErr(String(e))
    } finally {
      setSending(false)
    }
  }

  const onKey = e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }

  return (
    <div style={s.section}>
      <div style={s.sectionTitle}>Notes & Updates</div>
      <div style={s.noteInputRow}>
        <textarea
          style={s.noteTextarea}
          placeholder="Add a general update or report a complication…"
          value={message}
          onChange={e => setMessage(e.target.value)}
          onKeyDown={onKey}
          rows={2}
        />
        <button style={s.sendBtn} onClick={send} disabled={sending || !message.trim()}>
          {sending ? '…' : 'Send'}
        </button>
      </div>
      {err && <div style={s.inputError}>{err}</div>}
      {notes.length > 0 && (
        <div style={s.notesList}>
          {notes.map(n => (
            <div key={n.id} style={s.noteItem}>
              <div style={s.noteMsg}>{n.message}</div>
              <div style={s.noteMeta}>
                {n.step_number ? `Step ${n.step_number} · ` : ''}
                {fmtTime(n.created_at)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Action row (PDF + AI) ────────────────────────────────────────────────────

function ActionRow({ operationId, onChatToggle }) {
  return (
    <div style={s.actionRow}>
      <a
        href={`/api/v1/operations/${operationId}/report`}
        target="_blank"
        rel="noreferrer"
        style={s.pdfBtn}
      >
        📄 Download PDF
      </a>
      <button style={s.aiBtn} onClick={onChatToggle}>
        🤖 Ask AI assistant
      </button>
    </div>
  )
}

// ── AI assistant overlay ──────────────────────────────────────────────────────

function AiAssistant({ operationId, pipeId, onClose }) {
  const [messages, setMessages] = useState([
    { role: 'assistant', content: `Hi! I'm here to help with the ${pipeId || 'pipe'} operation. Ask me anything about the valve sequence, safety checks, or procedures.` }
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const sessionId = useRef(`crew-${operationId}-${Date.now()}`)
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const send = async () => {
    const msg = input.trim()
    if (!msg || loading) return
    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: msg }])
    setLoading(true)
    try {
      // Prefix the crew member's question with context so the backend gives
      // terse, action-oriented answers relevant to their on-site situation.
      const contextPrefix = `[FIELD CREW on ${pipeId || 'unknown pipe'} — give a short, direct answer for someone on site] `
      const res = await fetch('/api/v1/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId.current,
          message: contextPrefix + msg,
        }),
      })
      const data = await res.json()
      setMessages(prev => [...prev, { role: 'assistant', content: data.message || 'No response received.' }])
    } catch {
      setMessages(prev => [...prev, { role: 'assistant', content: '⚠️ Could not reach the assistant. Please try again.' }])
    } finally {
      setLoading(false)
    }
  }

  const onKey = e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }

  return (
    <div style={s.aiOverlay}>
      <div style={s.aiHeader}>
        <span style={{ fontWeight: 700, color: '#f1f5f9', fontSize: 13 }}>🤖 AI Assistant</span>
        <button style={s.closeBtn} onClick={onClose}>✕</button>
      </div>
      <div style={s.aiMessages}>
        {messages.map((m, i) => (
          <div key={i} style={m.role === 'user' ? s.userMsg : s.assistantMsg}>
            {m.content}
          </div>
        ))}
        {loading && <div style={s.assistantMsg}>…</div>}
        <div ref={bottomRef} />
      </div>
      <div style={s.aiInputRow}>
        <input
          style={s.aiInput}
          placeholder="Ask about valve sequence, safety, procedures…"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={onKey}
          disabled={loading}
        />
        <button style={s.sendBtn} onClick={send} disabled={loading || !input.trim()}>
          {loading ? '…' : '↑'}
        </button>
      </div>
    </div>
  )
}

// ── Styles ────────────────────────────────────────────────────────────────────

const s = {
  fullPage: {
    minHeight: '100vh',
    background: '#0f172a',
    color: '#e2e8f0',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    display: 'flex',
    flexDirection: 'column',
  },
  loading: {
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    height: '100vh', color: '#64748b', fontSize: 14,
  },
  errorBox: {
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    height: '100vh', color: '#f87171', padding: 24, textAlign: 'center', fontSize: 14,
  },

  // Header
  header: {
    background: '#1e293b',
    borderBottom: '1px solid #334155',
    padding: '12px 16px',
    flexShrink: 0,
  },
  headerTop: { display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 },
  logo: { fontSize: 22 },
  headerPipe: { fontWeight: 700, fontSize: 16, color: '#38bdf8' },
  headerRoad: { fontSize: 12, color: '#94a3b8', marginTop: 1 },
  classBadge: {
    marginLeft: 'auto', fontSize: 10, fontWeight: 700, color: '#f1f5f9',
    padding: '2px 8px', borderRadius: 4, letterSpacing: '0.05em',
  },
  headerDates: { fontSize: 12, color: '#94a3b8', marginBottom: 8 },

  // Progress bar
  progressWrap: { display: 'flex', flexDirection: 'column', gap: 4 },
  progressTrack: {
    height: 8, background: '#334155', borderRadius: 4, overflow: 'hidden',
  },
  progressFill: {
    height: '100%', background: '#22c55e', borderRadius: 4,
    transition: 'width 0.4s ease',
  },
  progressLabel: { fontSize: 11, color: '#94a3b8' },
  flagCount: { color: '#ef4444' },

  // Body
  body: { flex: 1, overflowY: 'auto', padding: '0 0 80px 0' },

  // Section
  section: { padding: '14px 16px', borderBottom: '1px solid #1e293b' },
  sectionTitle: {
    fontWeight: 700, fontSize: 12, color: '#64748b',
    textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 10,
  },

  // Phase group
  phaseGroup: { marginBottom: 12 },
  phaseLabel: {
    fontSize: 11, color: '#f59e0b', fontWeight: 600,
    textTransform: 'uppercase', letterSpacing: '0.06em',
    marginBottom: 4, paddingLeft: 4,
  },

  // Step row
  stepRow: {
    background: 'rgba(255,255,255,0.03)',
    borderRadius: 6,
    padding: '8px 10px',
    marginBottom: 6,
  },
  stepTop: { display: 'flex', alignItems: 'flex-start', gap: 8 },
  stepNum: {
    flexShrink: 0, width: 22, height: 22,
    background: '#334155', borderRadius: '50%',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontSize: 11, fontWeight: 700, color: '#94a3b8',
  },
  stepDesc: { flex: 1, fontSize: 13, color: '#e2e8f0', lineHeight: 1.4, paddingTop: 2 },
  statusSelect: {
    flexShrink: 0,
    background: '#0f172a',
    border: '1px solid #334155',
    borderRadius: 5,
    fontSize: 12,
    padding: '3px 6px',
    cursor: 'pointer',
    fontWeight: 600,
  },

  // Flag box
  flagBox: { marginTop: 8, paddingLeft: 30 },
  flagTextarea: {
    width: '100%', background: '#1e293b', border: '1px solid #475569',
    borderRadius: 5, color: '#e2e8f0', fontSize: 12, padding: '6px 8px',
    resize: 'vertical', fontFamily: 'inherit', boxSizing: 'border-box',
  },
  flagActions: { display: 'flex', gap: 8, marginTop: 6 },
  savedNote: {
    fontSize: 11, color: '#f87171', marginTop: 4,
    paddingLeft: 30, fontStyle: 'italic',
  },

  // Notes section
  noteInputRow: { display: 'flex', gap: 8, alignItems: 'flex-end' },
  noteTextarea: {
    flex: 1, background: '#1e293b', border: '1px solid #334155',
    borderRadius: 5, color: '#e2e8f0', fontSize: 13, padding: '6px 8px',
    resize: 'none', fontFamily: 'inherit',
  },
  notesList: { marginTop: 10, display: 'flex', flexDirection: 'column', gap: 6 },
  noteItem: {
    background: 'rgba(255,255,255,0.03)', borderRadius: 5,
    padding: '6px 8px', borderLeft: '3px solid #334155',
  },
  noteMsg: { fontSize: 13, color: '#e2e8f0', lineHeight: 1.4 },
  noteMeta: { fontSize: 10.5, color: '#475569', marginTop: 3 },

  // Action row
  actionRow: {
    display: 'flex', gap: 10, padding: '12px 16px',
    borderTop: '1px solid #1e293b',
  },
  pdfBtn: {
    flex: 1, background: '#1e293b', border: '1px solid #334155',
    borderRadius: 6, color: '#94a3b8', fontSize: 12, fontWeight: 600,
    padding: '10px 0', textAlign: 'center', textDecoration: 'none',
    cursor: 'pointer',
  },
  aiBtn: {
    flex: 1, background: '#1e3a5f', border: '1px solid #2563eb',
    borderRadius: 6, color: '#93c5fd', fontSize: 12, fontWeight: 600,
    padding: '10px 0', cursor: 'pointer',
  },

  // Shared button styles
  sendBtn: {
    background: '#f59e0b', border: 'none', borderRadius: 5,
    color: '#0f172a', fontWeight: 700, fontSize: 12,
    padding: '6px 14px', cursor: 'pointer',
  },
  cancelBtn: {
    background: 'none', border: '1px solid #475569',
    borderRadius: 5, color: '#94a3b8', fontSize: 12,
    padding: '6px 14px', cursor: 'pointer',
  },
  inputError: { color: '#f87171', fontSize: 11, marginTop: 4 },

  // AI assistant overlay
  aiOverlay: {
    position: 'fixed', bottom: 0, left: 0, right: 0,
    height: '55vh',
    background: 'rgba(10, 18, 35, 0.97)',
    backdropFilter: 'blur(10px)',
    borderTop: '1px solid #334155',
    display: 'flex', flexDirection: 'column',
    zIndex: 100,
  },
  aiHeader: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '8px 12px', borderBottom: '1px solid #334155', flexShrink: 0,
  },
  closeBtn: {
    background: 'none', border: 'none', color: '#64748b',
    cursor: 'pointer', fontSize: 16, padding: 2,
  },
  aiMessages: {
    flex: 1, overflowY: 'auto', padding: '8px 12px',
    display: 'flex', flexDirection: 'column', gap: 8,
  },
  userMsg: {
    alignSelf: 'flex-end', background: '#1e3a5f',
    color: '#e2e8f0', borderRadius: '12px 12px 2px 12px',
    padding: '6px 10px', maxWidth: '80%', fontSize: 13,
  },
  assistantMsg: {
    alignSelf: 'flex-start', background: '#1e293b',
    color: '#e2e8f0', borderRadius: '2px 12px 12px 12px',
    padding: '6px 10px', maxWidth: '85%', fontSize: 13, lineHeight: 1.5,
    whiteSpace: 'pre-wrap',
  },
  aiInputRow: {
    display: 'flex', gap: 8, padding: '8px 12px',
    borderTop: '1px solid #1e293b', flexShrink: 0,
  },
  aiInput: {
    flex: 1, background: '#1e293b', border: '1px solid #334155',
    borderRadius: 5, color: '#e2e8f0', fontSize: 13,
    padding: '6px 10px', outline: 'none', fontFamily: 'inherit',
  },
}
