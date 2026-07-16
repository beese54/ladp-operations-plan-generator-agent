import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'

const SESSION_ID = `web-${Date.now()}`

export default function ChatPanel({ onPipeResolved }) {
  const [messages, setMessages] = useState([
    { role: 'assistant', text: 'Ask me about any pipe shutdown, e.g. "Can I shut down pipe_084 on 2026-05-10 from 08:00 to 16:00?"' },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  async function send() {
    const text = input.trim()
    if (!text || loading) return
    setInput('')
    setMessages(prev => [...prev, { role: 'user', text }])
    setLoading(true)
    try {
      const res = await fetch('/api/v1/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: SESSION_ID, message: text }),
      })
      const data = await res.json()
      const reply = data.message ?? 'No response received.'
      setMessages(prev => [...prev, { role: 'assistant', text: reply }])
      // Auto-trace: highlight the resolved pipe's shutdown chain on the network graph
      if (data.pipe_id && onPipeResolved) onPipeResolved(data.pipe_id)
    } catch {
      setMessages(prev => [...prev, { role: 'assistant', text: 'Connection error — is the API running?' }])
    } finally {
      setLoading(false)
    }
  }

  function onKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
  }

  return (
    <div style={styles.panel}>
      <style>{markdownCss}</style>
      <div style={styles.header}>Operations Chat</div>

      <div style={styles.messages}>
        {messages.map((m, i) => (
          <div key={i} style={m.role === 'user' ? styles.userMsg : styles.assistantMsg}>
            <span style={styles.role}>{m.role === 'user' ? 'You' : 'Agent'}</span>
            {m.role === 'user'
              ? <pre style={styles.text}>{m.text}</pre>
              : <div className="md" style={styles.mdText}>
                  <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeRaw]}>{m.text}</ReactMarkdown>
                </div>}
          </div>
        ))}
        {loading && (
          <div style={styles.assistantMsg}>
            <span style={styles.role}>Agent</span>
            <span style={styles.typing}>Thinking…</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div style={styles.inputRow}>
        <textarea
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={onKey}
          placeholder="Ask about a pipe shutdown…"
          rows={2}
          style={styles.textarea}
          disabled={loading}
        />
        <button onClick={send} disabled={loading || !input.trim()} style={styles.sendBtn}>
          Send
        </button>
      </div>
    </div>
  )
}

// Dark-theme styling for rendered markdown in assistant messages.
const markdownCss = `
.md > :first-child { margin-top: 0; }
.md > :last-child { margin-bottom: 0; }
.md p { margin: 0 0 8px; }
.md ul, .md ol { margin: 4px 0 8px; padding-left: 20px; }
.md li { margin: 2px 0; }
.md strong { color: #f1f5f9; font-weight: 700; }
.md h1, .md h2, .md h3 { color: #e2e8f0; margin: 10px 0 6px; line-height: 1.3; }
.md h1 { font-size: 15px; } .md h2 { font-size: 14px; } .md h3 { font-size: 13px; }
.md code { background: #0b1220; border: 1px solid #334155; border-radius: 4px; padding: 1px 5px; font-size: 11px; font-family: ui-monospace, monospace; }
.md pre { background: #0b1220; border: 1px solid #334155; border-radius: 6px; padding: 8px 10px; overflow-x: auto; }
.md pre code { background: none; border: none; padding: 0; }
.md table { border-collapse: collapse; width: 100%; margin: 6px 0; font-size: 10.5px; }
.md th, .md td { border: 1px solid #334155; padding: 3px 6px; text-align: left; vertical-align: top; overflow-wrap: anywhere; }
.md th { background: #1e293b; color: #cbd5e1; font-weight: 600; }
.md blockquote { border-left: 3px solid #475569; margin: 6px 0; padding: 2px 0 2px 10px; color: #94a3b8; }
.md hr { border: none; border-top: 1px solid #334155; margin: 10px 0; }
.md a { color: #60a5fa; }
`

const styles = {
  panel: { display: 'flex', flexDirection: 'column', height: '100%', background: '#0f172a' },
  header: {
    background: '#1e293b',
    borderBottom: '1px solid #334155',
    padding: '10px 14px',
    fontSize: 13,
    fontWeight: 600,
    color: '#94a3b8',
    flexShrink: 0,
  },
  messages: {
    flex: 1,
    overflowY: 'auto',
    padding: '12px',
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
  },
  userMsg: {
    alignSelf: 'flex-end',
    maxWidth: '85%',
    background: '#1e40af',
    borderRadius: '12px 12px 2px 12px',
    padding: '8px 12px',
  },
  assistantMsg: {
    alignSelf: 'flex-start',
    maxWidth: '95%',
    background: '#1e293b',
    borderRadius: '2px 12px 12px 12px',
    padding: '8px 12px',
  },
  role: { display: 'block', fontSize: 10, color: '#64748b', marginBottom: 4, fontWeight: 600, textTransform: 'uppercase' },
  text: {
    fontSize: 12,
    lineHeight: 1.6,
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    margin: 0,
    fontFamily: 'inherit',
    color: '#e2e8f0',
  },
  mdText: {
    fontSize: 12,
    lineHeight: 1.6,
    wordBreak: 'break-word',
    color: '#e2e8f0',
  },
  typing: { fontSize: 12, color: '#64748b', fontStyle: 'italic' },
  inputRow: {
    display: 'flex',
    gap: 8,
    padding: '10px 12px',
    borderTop: '1px solid #334155',
    background: '#1e293b',
    flexShrink: 0,
  },
  textarea: {
    flex: 1,
    background: '#0f172a',
    border: '1px solid #334155',
    borderRadius: 8,
    color: '#e2e8f0',
    padding: '8px 10px',
    fontSize: 13,
    resize: 'none',
    outline: 'none',
    fontFamily: 'inherit',
  },
  sendBtn: {
    background: '#2563eb',
    color: '#fff',
    border: 'none',
    borderRadius: 8,
    padding: '0 16px',
    cursor: 'pointer',
    fontWeight: 600,
    fontSize: 13,
    alignSelf: 'stretch',
  },
}
