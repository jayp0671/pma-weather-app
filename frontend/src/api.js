// ===== PMA Weather App — API helpers =====

// Utility: handle fetch responses safely
async function handle(r) {
  const text = await r.text()
  if (!r.ok) {
    try { throw new Error(JSON.stringify(JSON.parse(text))) }
    catch { throw new Error(text || `HTTP ${r.status}`) }
  }
  try { return JSON.parse(text) } catch { return text }
}

// -------------------- Assessment 1 --------------------
export async function getCurrent(location) {
  const r = await fetch(`/api/weather/current?location=${encodeURIComponent(location)}`)
  return handle(r)
}

export async function searchLocations(q) {
  const r = await fetch(`/api/locations/search?q=${encodeURIComponent(q)}`)
  return handle(r)
}

// -------------------- Assessment 2 — CRUD --------------------
export async function createRecord(payload) {
  const r = await fetch('/api/records', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return handle(r)
}

export async function listRecords() {
  const r = await fetch('/api/records')
  return handle(r)
}

export async function updateRecord(id, payload) {
  const r = await fetch(`/api/records/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return handle(r)
}

export async function deleteRecord(id) {
  const r = await fetch(`/api/records/${id}`, { method: 'DELETE' })
  return handle(r)
}

// -------------------- Assessment 2 — Export --------------------
export async function exportData(fmt = 'json') {
  const r = await fetch(`/api/export?fmt=${fmt}`)
  if (fmt === 'json') return handle(r)
  if (!r.ok) throw new Error(await r.text())
  return r.text()
}

// -------------------- Extras (no YouTube / no static map) --------------------
export async function getNearby(lat, lon, radius = 1200, limit = 18) {
  const r = await fetch(`/api/places/nearby?lat=${lat}&lon=${lon}&radius=${radius}&limit=${limit}`)
  return handle(r)
}

export async function getAstronomy(lat, lon) {
  const r = await fetch(`/api/extras/astronomy?lat=${lat}&lon=${lon}`)
  return handle(r)
}

export async function getAir(lat, lon) {
  const r = await fetch(`/api/extras/air?lat=${lat}&lon=${lon}`)
  return handle(r)
}

export async function getPollen(lat, lon) {
  const r = await fetch(`/api/extras/pollen?lat=${lat}&lon=${lon}`)
  return handle(r)
}

export async function getWiki(lat, lon) {
  const r = await fetch(`/api/extras/wiki?lat=${lat}&lon=${lon}`)
  return handle(r)
}

export async function getDateFact() {
  const r = await fetch(`/api/extras/datefact`)
  return handle(r)
}

// -------------------- Health (optional) --------------------
export async function ping() {
  const r = await fetch('/api/health')
  return handle(r)
}
