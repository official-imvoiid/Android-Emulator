import { useCallback, useEffect, useRef, useState } from 'react'
import { api, connectEvents, formatMb } from './api.js'
import SetupView from './components/SetupView.jsx'
import DeviceView from './components/DeviceView.jsx'
import FilesView from './components/FilesView.jsx'
import PackagesView from './components/PackagesView.jsx'
import StatusBar from './components/StatusBar.jsx'

const TABS = [
  { id: 'setup', label: 'Set up' },
  { id: 'device', label: 'Device' },
  { id: 'files', label: 'Files' },
  { id: 'packages', label: 'Storage' },
]

const BASE_SPEC = {
  name: 'My_Android',
  ramMb: 4096,
  cores: 4,
  storageGb: 16,
  gpuMode: 'auto',
  deviceProfile: 'phone',
  persistent: true,
  playStore: true,
  headless: false,
}

export default function App() {
  const [tab, setTab] = useState('setup')
  const [systemInfo, setSystemInfo] = useState(null)
  const [accel, setAccel] = useState(null)
  const [options, setOptions] = useState(null)

  const [catalog, setCatalog] = useState(null)
  const [catalogLoading, setCatalogLoading] = useState(false)
  const [catalogError, setCatalogError] = useState(null)
  const [filters, setFilters] = useState({ formFactor: 'phone', previews: false })

  const [selected, setSelected] = useState(null)
  const [spec, setSpec] = useState(BASE_SPEC)

  const [status, setStatus] = useState({ device: null, adbAvailable: false })
  const [avds, setAvds] = useState([])
  const [starting, setStarting] = useState(false)
  const [stopping, setStopping] = useState(false)

  const [logs, setLogs] = useState([])
  const [progress, setProgress] = useState(null)
  const [connected, setConnected] = useState(false)
  const [logOpen, setLogOpen] = useState(false)
  const [toast, setToast] = useState(null)
  const bootSeen = useRef(false)

  const addLog = useCallback((message, level = 'info') => {
    setLogs((prev) => [...prev.slice(-400), { message, level, time: new Date().toLocaleTimeString() }])
  }, [])

  const fail = useCallback((message) => {
    setToast({ level: 'bad', message })
    addLog(message, 'error')
  }, [addLog])

  const done = useCallback((message) => {
    setToast({ level: 'good', message })
    addLog(message)
  }, [addLog])

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 6000)
    return () => clearTimeout(t)
  }, [toast])

  useEffect(() => {
    api.systemInfo().then(setSystemInfo).catch((e) => fail(e.message))
    api.options().then((o) => {
      setOptions(o)
      setSpec((s) => ({ ...s, ramMb: o.ram.default, cores: o.cores.default }))
    }).catch((e) => fail(e.message))
    api.accel().then(setAccel).catch(() => {})
  }, [fail])

  useEffect(() => connectEvents((evt) => {
    if (evt.kind === 'connection') setConnected(evt.state === 'open')
    else if (evt.kind === 'log') addLog(evt.message, evt.level)
    else if (evt.kind === 'progress') setProgress(evt)
    else if (evt.kind === 'device') {
      addLog(`Device ${evt.state}${evt.name ? `: ${evt.name}` : ''}`,
        evt.state === 'stopped' ? 'warn' : 'info')
    }
  }), [addLog])

  const loadCatalog = useCallback(async () => {
    setCatalogLoading(true)
    setCatalogError(null)
    try {
      const data = await api.catalog(filters)
      setCatalog(data)
      setSelected((prev) => {
        if (prev && data.entries.some((e) => e.packagePath === prev)) return prev
        return data.latestStable || data.entries[0]?.packagePath || null
      })
    } catch (err) {
      setCatalogError(err.message)
    } finally {
      setCatalogLoading(false)
    }
  }, [filters])

  useEffect(() => { loadCatalog() }, [loadCatalog])

  const refresh = async () => {
    try { await api.refreshCatalog() } catch { /* reload surfaces real errors */ }
    await loadCatalog()
  }

  const loadAvds = useCallback(async () => {
    try { setAvds((await api.avds()).avds) } catch { /* non-fatal */ }
  }, [])
  useEffect(() => { loadAvds() }, [loadAvds])

  useEffect(() => {
    let alive = true
    const poll = async () => {
      try {
        const s = await api.deviceStatus()
        if (!alive) return
        setStatus(s)
        if (s.device?.booted && !bootSeen.current) {
          bootSeen.current = true
          done('Your device has finished starting up.')
          setTab('device')
        }
        if (!s.device) bootSeen.current = false
      } catch { /* backend restarting */ }
    }
    poll()
    const id = setInterval(poll, 2500)
    return () => { alive = false; clearInterval(id) }
  }, [done])

  const start = async (full) => {
    setStarting(true)
    try {
      await api.start(full)
      setTab('device')
      done('Starting the device. The first start on a new Android version can take a few minutes.')
      await loadAvds()
    } catch (err) {
      fail(err.message)
    } finally {
      setStarting(false)
    }
  }

  const stop = async () => {
    setStopping(true)
    try {
      await api.stop()
      done('The device has been shut down.')
      await loadAvds()
    } catch (err) {
      fail(err.message)
    } finally {
      setStopping(false)
    }
  }

  const device = status.device
  const noAccel = accel?.accelerated === false

  return (
    <div className="app">
      <header className="masthead">
        <div className="wordmark">
          <span className="glyph" aria-hidden="true">A</span>
          <b>Android Emulator Hub</b>
        </div>

        <nav className="nav" role="tablist">
          {TABS.map((t) => (
            <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}>
              {t.label}
              {t.id === 'device' && device && <span className="live" aria-label="running" />}
            </button>
          ))}
        </nav>

        <div className="right">
          {device
            ? <span className="badge go">{device.name} running</span>
            : <span className="badge">No device running</span>}
        </div>
      </header>

      <main className="content">
        <div className="page">
          {noAccel && tab === 'setup' && (
            <div className="notice bad">
              <span className="mark">!</span>
              <div>
                <h4>Your PC needs one setting changed first</h4>
                <p>
                  Windows' virtualisation feature is switched off, so Android would run far too
                  slowly to use. You can still download versions now, but turn this on before
                  starting a device.
                </p>
                {accel.fixCommand && (
                  <>
                    <p>Open Command Prompt <b>as administrator</b>, run this, then restart your PC:</p>
                    <pre>{accel.fixCommand}</pre>
                  </>
                )}
              </div>
            </div>
          )}

          {tab === 'setup' && (
            <SetupView
              catalog={catalog} catalogLoading={catalogLoading} catalogError={catalogError}
              options={options} support={systemInfo?.support}
              filters={filters} setFilters={setFilters} onRefresh={refresh}
              spec={spec} setSpec={setSpec}
              selected={selected} setSelected={setSelected}
              onStart={start} starting={starting} deviceRunning={Boolean(device)}
            />
          )}

          {tab === 'device' && (
            <DeviceView device={device} adbAvailable={status.adbAvailable}
                        onStop={stop} stopping={stopping} onError={fail} />
          )}

          {tab === 'files' && (
            <FilesView device={device} adbAvailable={status.adbAvailable}
                       onError={fail} onInfo={done} />
          )}

          {tab === 'packages' && (
            <PackagesView systemInfo={systemInfo} accel={accel} avds={avds}
                          onError={fail} onInfo={done} onReloadAvds={loadAvds}
                          deviceRunning={Boolean(device)} formatMb={formatMb} />
          )}
        </div>
      </main>

      <StatusBar logs={logs} progress={progress} connected={connected}
                 open={logOpen} setOpen={setLogOpen} toast={toast} />
    </div>
  )
}
