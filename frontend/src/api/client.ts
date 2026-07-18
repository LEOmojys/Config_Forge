const API_BASE = '/api'

export async function generate(req: { job_type: string; requirement: string; enable_critic: boolean }) {
  const res = await fetch(`${API_BASE}/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getTraces(limit = 50) {
  const res = await fetch(`${API_BASE}/traces?limit=${limit}`)
  return res.json()
}

export async function getTrace(traceId: string) {
  const res = await fetch(`${API_BASE}/traces/${traceId}`)
  if (!res.ok) throw new Error('Trace not found')
  return res.json()
}

export async function getTables() {
  const res = await fetch(`${API_BASE}/tables`)
  return res.json()
}

export async function getTable(name: string) {
  const res = await fetch(`${API_BASE}/tables/${name}`)
  return res.json()
}

export async function runEval() {
  const res = await fetch(`${API_BASE}/eval/run`, { method: 'POST' })
  return res.json()
}

export async function getSeedContext() {
  const res = await fetch(`${API_BASE}/seed/context`)
  return res.json()
}
