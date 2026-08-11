const API_BASE = '/api'
const tablePath = (name: string) => `${API_BASE}/tables/${encodeURIComponent(name)}`

export async function generate(req: { job_type: string; requirement: string; enable_critic: boolean; batch_count?: number }) {
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
  const res = await fetch(tablePath(name))
  return res.json()
}

export async function addTableRow(name: string, row: Record<string, any>) {
  const res = await fetch(`${tablePath(name)}/rows`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ row }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function updateTableRow(name: string, rowIndex: number, row: Record<string, any>) {
  const res = await fetch(`${tablePath(name)}/rows/${rowIndex}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ row }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function deleteTableRow(name: string, rowIndex: number) {
  const res = await fetch(`${tablePath(name)}/rows/${rowIndex}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function deleteTrace(traceId: string) {
  const res = await fetch(`${API_BASE}/traces/${traceId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function clearTraces(status?: string) {
  const query = status ? `?status=${encodeURIComponent(status)}` : ''
  const res = await fetch(`${API_BASE}/traces${query}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await res.text())
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
