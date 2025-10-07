import { useEffect, useState } from 'react'
import {
  getCurrent, searchLocations,
  createRecord, listRecords, updateRecord, deleteRecord, exportData,
  getNearby, getAstronomy, getAir
} from './api'

// ---------- tiny emoji mapper ----------
function wcToEmoji(wcode){
  if([0].includes(wcode)) return '☀️'
  if([1,2,3].includes(wcode)) return '⛅'
  if([45,48].includes(wcode)) return '🌫️'
  if([51,53,55,61,63,65,80,81,82].includes(wcode)) return '🌧️'
  if([71,73,75,85,86].includes(wcode)) return '❄️'
  if([95,96,99].includes(wcode)) return '⛈️'
  return '🌡️'
}

// ---------- input classification ----------
const COORD_RE = /^\s*-?\d+\.?\d*\s*,\s*-?\d+\.?\d*\s*$/
const ZIP_RE   = /^\s*\d{5}\s*$/
function isWordyQuery(q){
  const s = q.trim()
  if (!s) return false
  if (COORD_RE.test(s)) return false
  if (ZIP_RE.test(s))   return false
  return true
}

// ---------- unit helpers ----------
const toF = c => (c * 9) / 5 + 32
const kmhToMph = kmh => kmh * 0.621371
function fmtTemp(c, unit){ if(c==null) return '—'; return unit==='f'?`${Math.round(toF(c))}°F`:`${Math.round(c)}°C` }
function fmtWind(kmh, unit){ if(kmh==null) return '—'; return unit==='f'?`${Math.round(kmhToMph(kmh))} mph`:`${Math.round(kmh)} km/h` }
function fmtPrecip(mm){ if(mm==null) return '—'; return `${mm.toFixed(1)} mm` }

export default function App(){
  const [location,setLocation]=useState(()=>localStorage.getItem('pma:lastLocation')||'')
  const [unit,setUnit]=useState(()=>localStorage.getItem('pma:unit')||'c')
  const [current,setCurrent]=useState(null)
  const [error,setError]=useState('')
  const [records,setRecords]=useState([])
  const [selectedId,setSelectedId]=useState(null)
  const [range,setRange]=useState({start:'2025-10-01',end:'2025-10-05'})
  const [cands,setCands]=useState([]); const [openSug,setOpenSug]=useState(false)
  const [activeIdx,setActiveIdx]=useState(-1); const [typingTimer,setTypingTimer]=useState(null)

  // integrations
  const [pois,setPois]=useState([]); const [astro,setAstro]=useState(null); const [air,setAir]=useState(null)

  useEffect(()=>{refresh()},[])
  useEffect(()=>{localStorage.setItem('pma:lastLocation',location||'')},[location])
  useEffect(()=>{localStorage.setItem('pma:unit',unit)},[unit])

  async function refresh(){ try{setRecords(await listRecords())}catch(e){console.error(e)} }

  async function fetchCurrentFor(loc){
    setError('')
    try{
      const j=await getCurrent(loc)
      setCurrent(j)
      const lat=j?.resolved?.latitude, lon=j?.resolved?.longitude
      if(lat!=null&&lon!=null){
        getNearby(lat,lon,1200,18).then(r=>setPois(r.items||[])).catch(()=>{})
        getAstronomy(lat,lon).then(setAstro).catch(()=>{})
        getAir(lat,lon).then(setAir).catch(()=>{})
      }
    }catch(e){ setError(cleanErr(e)) }
  }
  async function fetchCurrent(){ if(!location?.trim()){setError('Please enter a location');return} fetchCurrentFor(location) }

  function scheduleSuggest(q){
    if(typingTimer)clearTimeout(typingTimer)
    if(!isWordyQuery(q)){setCands([]);setOpenSug(false);return}
    const t=setTimeout(async()=>{
      try{const res=await searchLocations(q);setCands(res.slice(0,8));setOpenSug(res.length>0)}
      catch{setCands([]);setOpenSug(false)}
    },300)
    setTypingTimer(t)
  }
  function chooseCand(c,{autoFetch=false}={}){setLocation(c.name);setCands([]);setOpenSug(false);const precise=`${c.latitude.toFixed(4)},${c.longitude.toFixed(4)}`;if(autoFetch)fetchCurrentFor(precise)}
  function useMyLocation(){if(!navigator.geolocation){setError('Geolocation not supported');return}
    navigator.geolocation.getCurrentPosition(
      pos=>{const coords=`${pos.coords.latitude.toFixed(4)},${pos.coords.longitude.toFixed(4)}`;setLocation(coords);fetchCurrentFor(coords)},
      err=>setError(err.message),
      {enableHighAccuracy:true,timeout:10000}
    )
  }

  async function onCreate(){try{const r=await createRecord({location,start_date:range.start,end_date:range.end});setSelectedId(r.id);await refresh()}catch(e){setError(cleanErr(e))}}
async function onUpdate(){
  if(!selectedId) return;
  setError('');
  try{
    await updateRecord(selectedId, {
      location,
      start_date: range.start,
      end_date: range.end
    });
    await refresh();
  }catch(e){
    setError(cleanErr(e));
  }
}
  async function onDelete(){if(!selectedId)return;try{await deleteRecord(selectedId);setSelectedId(null);await refresh()}catch(e){setError(cleanErr(e))}}
  async function onExport(fmt){try{const d=await exportData(fmt);const blob=new Blob([typeof d==='string'?d:JSON.stringify(d,null,2)],{type:'text/plain'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`export.${fmt}`;a.click();URL.revokeObjectURL(url)}catch(e){setError(cleanErr(e))}}

  return (
    <div className="app">
      <div className="header"><div className="h1">PMA Weather — Jay Patel</div><div className="badge">v1 • simple dark UI</div></div>

      {/* ===== Weather ===== */}
      <div className="card">
        <div className="title">Assessment 1 · Current weather + 5-day</div>
        <div className="row" style={{position:'relative',marginBottom:8}}>
          <input className="input" value={location} onChange={e=>{const v=e.target.value;setLocation(v);scheduleSuggest(v)}} placeholder="City / Town / Landmark (ZIP & GPS also work)"/>
          <button className="btn primary" onClick={fetchCurrent}>Get Weather</button>
          <button className="btn" onClick={useMyLocation}>Use My Location</button>
          <button className="btn" onClick={()=>setUnit(u=>u==='c'?'f':'c')}>{unit==='c'?'Show °F':'Show °C'}</button>
        </div>

        {error && <div className="tag" style={{borderColor:'#6d2b2b',color:'#ffb4b4'}}>⚠️ {error}</div>}

        {current && (
          <div className="grid" style={{marginTop:10}}>
            <div className="pill"><div className="muted">Resolved</div><div style={{fontWeight:600}}>{current.resolved.name}</div>
              <div className="muted">{current.resolved.latitude.toFixed(2)}, {current.resolved.longitude.toFixed(2)}</div></div>
            <div className="pill">
              <div className="muted">Now</div>
              <div style={{fontSize:28}}>{wcToEmoji(current.data.current.weather_code)} {fmtTemp(current.data.current.temperature_2m,unit)}</div>
              <div className="kv"><b>Feels</b> {fmtTemp(current.data.current.apparent_temperature,unit)}</div>
              <div className="kv"><b>Humid</b> {current.data.current.relative_humidity_2m}%</div>
              <div className="kv"><b>Wind</b> {fmtWind(current.data.current.wind_speed_10m,unit)}</div>
            </div>
            <div className="pill" style={{gridColumn:'1 / -1'}}>
              <div className="muted">5-day forecast</div>
              <div className="grid" style={{marginTop:8}}>
                {current.data.daily.time.map((d,i)=>(
                  <div key={d} className="pill">
                    <div style={{fontWeight:600}}>{d}</div>
                    <div style={{fontSize:20}}>
                      {wcToEmoji(current.data.daily.weather_code?.[i]??0)}{' '}
                      {fmtTemp(current.data.daily.temperature_2m_max[i],unit)} / {fmtTemp(current.data.daily.temperature_2m_min[i],unit)}
                    </div>
                    <div className="muted">
                      Precip {fmtPrecip(current.data.daily.precipitation_sum[i])} · Wind max {fmtWind(current.data.daily.wind_speed_10m_max?.[i],unit)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ===== API Integrations (only reliable ones) ===== */}
      {current && (
        <div className="card">
          <div className="title">API Integrations · POIs, Air Quality, Astronomy</div>
          <div className="grid" style={{marginTop:10}}>
            {/* Nearby Places — horizontal scroll strip */}
            <div className="pill">
              <div className="muted" style={{marginBottom:6}}>Nearby Places (~1 km)</div>
              {pois.length===0 && <div className="muted">(loading...)</div>}
              {pois.length>0 && (
                <div
                  className="scroll-strip"
                  style={{
                    display: 'flex',
                    gap: 12,
                    overflowX: 'auto',
                    paddingBottom: 6,
                    scrollSnapType: 'x mandatory',
                  }}
                >
                  {pois.map(p=>(
                    <div
                      key={p.id}
                      style={{
                        flex: '0 0 auto',
                        minWidth: 180,
                        background: '#111f3a',
                        border: '1px solid #2a3c60',
                        borderRadius: 10,
                        padding: '10px 12px',
                        scrollSnapAlign: 'start',
                        boxShadow: '0 4px 10px rgba(0,0,0,0.25)',
                      }}
                    >
                      <div style={{fontWeight:600, marginBottom:4}}>{p.name}</div>
                      <div className="muted" style={{fontSize:12, marginBottom:4}}>{p.category}</div>
                      <div className="muted" style={{fontSize:11}}>
                        {p.lat.toFixed(4)}, {p.lon.toFixed(4)}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Air Quality */}
            <div className="pill">
              <div className="muted">Air Quality (US AQI)</div>
              {!air&&<div className="muted">(loading...)</div>}
              {air?.now&&(
                <div className="kv" style={{marginTop:6}}>
                  <div><b>Now</b> · AQI {air.now.us_aqi??'—'}</div>
                  <div className="muted" style={{fontSize:12}}>
                    PM2.5 {air.now.pm2_5??'—'} · PM10 {air.now.pm10??'—'} · O₃ {air.now.ozone??'—'}
                  </div>
                </div>
              )}
            </div>

            {/* Sunrise / Sunset */}
            <div className="pill">
              <div className="muted">Sunrise & Sunset (local)</div>
              {!astro&&<div className="muted">(loading...)</div>}
              {astro&&(
                <div className="kv">
                  <div><b>Sunrise</b> {new Date(astro.sunrise).toLocaleTimeString()}</div>
                  <div><b>Sunset</b> {new Date(astro.sunset).toLocaleTimeString()}</div>
                  <div className="muted" style={{fontSize:12}}>Solar noon: {new Date(astro.solar_noon).toLocaleTimeString()}</div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ===== CRUD + Export ===== */}
      <div className="card">
        <div className="title">Assessment 2 · CRUD + Export</div>
        <div className="row" style={{marginBottom:8}}>
          <input className="date" type="date" value={range.start} onChange={e=>setRange(r=>({...r,start:e.target.value}))}/>
          <input className="date" type="date" value={range.end} onChange={e=>setRange(r=>({...r,end:e.target.value}))}/>
          <button className="btn primary" onClick={onCreate}>Create (Save)</button>
          <button className="btn" onClick={onUpdate} disabled={!selectedId}>Update</button>
          <button className="btn danger" onClick={onDelete} disabled={!selectedId}>Delete</button>
        </div>
        <div className="row" style={{marginBottom:8}}>
          <button className="btn" onClick={()=>onExport('json')}>Export JSON</button>
          <button className="btn" onClick={()=>onExport('csv')}>Export CSV</button>
          <button className="btn" onClick={()=>onExport('xml')}>Export XML</button>
          <button className="btn" onClick={()=>onExport('md')}>Export MD</button>
        </div>
        <div className="pill">
          <div className="muted" style={{marginBottom:6}}>Saved Records</div>
          <div className="list">
            {records.length===0&&<div className="muted">(none yet)</div>}
            {records.map(r=>(
              <div key={r.id}>
                <label style={{display:'flex',alignItems:'center',gap:8}}>
                  <input type="radio" name="sel" checked={selectedId===r.id} onChange={()=>setSelectedId(r.id)}/>
                  <span>#{r.id} · {r.resolved_name} · {r.start_date} → {r.end_date}</span>
                </label>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="footer">Built by Jay Patel — AI Engineer Intern Candidate</div>
    </div>
  )
}

function cleanErr(e){
  const s=String(e)
  try{const m=s.match(/\{.*\}/s);if(m){const j=JSON.parse(m[0]);if(j?.detail)return typeof j.detail==='string'?j.detail:JSON.stringify(j.detail)}}catch{}
  return s.replace(/^Error:\s*/,'')
}
