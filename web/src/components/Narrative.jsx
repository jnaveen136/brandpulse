import { useState } from 'react'
import { useView, viewQuery } from '../state'
import { Card } from './ui'

/** Asks the LLM layer to narrate a diagnostics result. The numbers come from the
 *  diagnostics payload; the server checks every figure in the reply against it. */
export default function Narrative({ brand, diag }) {
  const { view } = useView()
  const [state, setState] = useState({ text: null, loading: false, error: null, meta: null })
  const run = async () => {
    setState({ text: null, loading: true, error: null })
    try {
      const r = await fetch(`/api/ask/explain?${viewQuery(view, { brand, subcategory: diag.subcategory || '' })}`, { method: 'POST' })
      const body = await r.json()
      if (!r.ok) throw new Error(body.detail || r.status)
      setState({ text: body.answer, loading: false, error: null, meta: body })
    } catch (e) {
      setState({ text: null, loading: false, error: String(e.message || e) })
    }
  }
  return (
    <Card style={{ marginTop: 14 }} title="Explanation in plain words"
      sub="Written by the LLM from the numbers above; every figure is checked against them before it is shown."
      right={<button className="btn" onClick={run} disabled={state.loading}>{state.loading ? 'Writing…' : state.text ? 'Rewrite' : 'Explain'}</button>}>
      {state.error && <p className="muted">Not available: {state.error}</p>}
      {state.text && (
        <>
          <p style={{ whiteSpace: 'pre-wrap' }}>{state.text}</p>
          {state.meta && (
            <p className="faint small" style={{ marginTop: 8 }}>
              {state.meta.provider} · {state.meta.verified ? '✓ all figures verified' : '⚠ figures could not be verified, showing the template summary'}
            </p>
          )}
        </>
      )}
    </Card>
  )
}
