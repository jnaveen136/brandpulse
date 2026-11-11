import { useEffect, useRef, useState } from 'react'
import { Card, Note } from '../components/ui'
import { useView } from '../state'

const EXAMPLES = [
  'How did revenue do this period compared with last year?',
  'Who is discounting most in our sub-categories?',
  'Which retailer gives us the highest margin?',
  'Why did revenue change last month?',
  'What is our price gap against competitors in Soap?',
  'Which competitor gained the most share?',
]

function Answer({ m }) {
  return (
    <div className="msg bot">
      <p style={{ whiteSpace: 'pre-wrap' }}>{m.answer}</p>
      <div className="faint small" style={{ marginTop: 8, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        <span>{m.provider}</span>
        {m.verified != null && <span>{m.verified ? '✓ every figure verified against the KPI engine' : '⚠ unverified figures removed'}</span>}
        {m.refused && <span>answer limited by the data</span>}
      </div>
      {m.tool_calls?.length > 0 && (
        <details style={{ marginTop: 6 }}>
          <summary className="small muted" style={{ cursor: 'pointer' }}>Sources ({m.tool_calls.length} KPI engine call{m.tool_calls.length > 1 ? 's' : ''})</summary>
          <pre className="small" style={{ whiteSpace: 'pre-wrap', background: 'var(--surface-2)', padding: 8, borderRadius: 6, maxHeight: 260, overflow: 'auto' }}>
            {m.tool_calls.map((t) => `${t.name}(${JSON.stringify(t.args)})`).join('\n')}
          </pre>
        </details>
      )}
    </div>
  )
}

export default function Ask() {
  const { view } = useView()
  const [msgs, setMsgs] = useState([])
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState(null)
  const end = useRef(null)
  useEffect(() => { fetch('/api/ask/status').then((r) => (r.ok ? r.json() : null)).then(setStatus).catch(() => setStatus(null)) }, [])
  // braces matter: newer browsers return a Promise from scrollIntoView, and a value returned from an
  // effect is treated as its cleanup function (calling the Promise crashed the whole app)
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs])

  const send = async (text) => {
    const question = (text ?? q).trim()
    if (!question || busy) return
    setQ('')
    setMsgs((m) => [...m, { role: 'user', text: question }])
    setBusy(true)
    try {
      const r = await fetch('/api/ask', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, brand: view.brand, period: view.period, mode: view.mode,
          history: msgs.slice(-6).map((m) => ({ role: m.role, text: m.role === 'user' ? m.text : m.answer })) }),
      })
      const body = await r.json()
      if (!r.ok) throw new Error(body.detail || r.status)
      setMsgs((m) => [...m, { role: 'bot', ...body }])
    } catch (e) {
      setMsgs((m) => [...m, { role: 'bot', answer: `Sorry, that failed: ${e.message}`, provider: 'error' }])
    }
    setBusy(false)
  }

  return (
    <div className="chat">
      <Card title="Ask about your brand"
        sub={`Answers come only from the KPI engine for ${view.brand}, with the period and comparison selected above unless you name others.`}>
        {status && <p className="small muted">Model: {status.provider}{status.model ? ` (${status.model})` : ''}{status.ready ? '' : ' · not configured, using offline templates'}</p>}
        {!status && <Note>The Q&A service is not running on this server.</Note>}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 10 }}>
          {EXAMPLES.map((e) => <button key={e} className="pill" onClick={() => send(e)} disabled={busy}>{e}</button>)}
        </div>
      </Card>
      {msgs.map((m, i) => (m.role === 'user' ? <div key={i} className="msg user">{m.text}</div> : <Answer key={i} m={m} />))}
      {busy && <div className="msg bot muted">Computing from the KPI engine…</div>}
      <div ref={end} />
      <form className="chat-input" onSubmit={(e) => { e.preventDefault(); send() }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Ask about ${view.brand}…`} aria-label="Question" />
        <button className="btn" disabled={busy || !q.trim()}>Ask</button>
      </form>
    </div>
  )
}
