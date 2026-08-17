import { useCallback, useEffect, useState } from 'react'
import { api, formatMb } from '../api.js'

export default function PackagesView({ systemInfo, accel, avds, onError, onInfo, onReloadAvds, deviceRunning }) {
  const [installed, setInstalled] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try { setInstalled(await api.installed()) } catch (err) { onError(err.message) }
  }, [onError])

  useEffect(() => { load() }, [load])

  const remove = async (path, label) => {
    setBusy(true)
    try {
      await api.uninstall(path)
      onInfo(`${label} was deleted.`)
      await load()
    } catch (err) { onError(err.message) } finally { setBusy(false) }
  }

  const removeDevice = async (name) => {
    setBusy(true)
    try {
      await api.deleteAvd(name)
      onInfo(`Device “${name}” was deleted.`)
      await onReloadAvds()
    } catch (err) { onError(err.message) } finally { setBusy(false) }
  }

  const friendly = (path) => {
    if (path === 'emulator') return 'The emulator itself'
    if (path === 'platform-tools') return 'Device tools (needed for controls and file transfer)'
    const m = path.match(/^system-images;android-([\d.]+)/)
    return m ? `Android system image (API ${m[1]})` : path
  }

  return (
    <>
      <div className="panel">
        <header>
          <h2>Downloaded Android versions</h2>
          <p>
            Deleting a version frees up disk space. You can download it again later at any time.
          </p>
        </header>
        <div className="body">
          <div className="row">
            <span className={`badge ${installed?.emulatorInstalled ? 'go' : 'warn'}`}>
              {installed?.emulatorInstalled ? 'Emulator installed' : 'Emulator not installed'}
            </span>
            <span className={`badge ${installed?.adbInstalled ? 'go' : 'warn'}`}>
              {installed?.adbInstalled ? 'Device tools installed' : 'Device tools missing'}
            </span>
            <span className="spacer" />
            <button className="btn quiet sm" onClick={load}>Refresh</button>
          </div>

          {installed?.packages?.length ? (
            <table className="grid">
              <thead>
                <tr><th>What it is</th><th>Version</th><th>Disk used</th><th /></tr>
              </thead>
              <tbody>
                {installed.packages.map((p) => (
                  <tr key={p.path}>
                    <td>
                      {friendly(p.path)}
                      <div className="mono faint tiny">{p.path}</div>
                    </td>
                    <td className="mono">{p.revision}</td>
                    <td className="mono">{formatMb(p.diskMb)}</td>
                    <td className="right">
                      <button className="btn stop sm" disabled={busy || deviceRunning}
                              title={deviceRunning ? 'Shut the running device down first' : 'Delete these files'}
                              onClick={() => remove(p.path, friendly(p.path))}>
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="blank">
              Nothing downloaded yet. Choose an Android version on the Set up tab.
            </div>
          )}
        </div>
      </div>

      <div className="panel">
        <header>
          <h2>Your saved devices</h2>
          <p>
            Devices set to keep their data are listed here. Ones set to start fresh are not saved —
            they disappear when you shut them down.
          </p>
        </header>
        <div className="body">
          {avds?.length ? (
            <table className="grid">
              <thead>
                <tr><th>Name</th><th>Memory</th><th>Cores</th><th>Storage</th><th>Screen</th><th /></tr>
              </thead>
              <tbody>
                {avds.map((a) => (
                  <tr key={a.name}>
                    <td>
                      <b>{a.name}</b>{' '}
                      {a.playStore && <span className="badge">Play Store</span>}
                    </td>
                    <td className="mono">{formatMb(a.ramMb)}</td>
                    <td className="mono">{a.cores}</td>
                    <td className="mono">{a.storage}</td>
                    <td className="mono">{a.resolution}</td>
                    <td className="right">
                      <button className="btn stop sm" disabled={busy}
                              onClick={() => removeDevice(a.name)}>
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="blank">No saved devices yet.</div>
          )}
        </div>
      </div>

      <div className="panel">
        <header>
          <h2>Where things are kept</h2>
          <p>
            Everything this app downloads lives in one folder. Your existing Android tools, if you
            have any, are never touched or changed.
          </p>
        </header>
        <div className="body">
          <table className="grid">
            <tbody>
              <tr><td className="k">Everything is here</td><td className="mono">{systemInfo?.paths.home}</td></tr>
              <tr><td className="k">Free space left</td><td>{formatMb(systemInfo?.host.freeDiskMb)}</td></tr>
              <tr>
                <td className="k">Your PC</td>
                <td>
                  {systemInfo?.host.logicalCpus} processor cores ·{' '}
                  {formatMb(systemInfo?.host.totalRamMb)} memory
                </td>
              </tr>
              <tr>
                <td className="k">Speed boost</td>
                <td>
                  {accel?.accelerated === true && <span className="badge go">Working</span>}
                  {accel?.accelerated === false && <span className="badge bad">Switched off</span>}
                  {accel?.accelerated == null && <span className="badge warn">Unknown</span>}
                  {accel?.detail && <div className="subtle tiny" style={{ marginTop: 6 }}>{accel.detail}</div>}
                  {accel?.fixCommand && (
                    <pre className="mono" style={{
                      marginTop: 8, padding: '9px 11px', borderRadius: 5,
                      background: 'var(--sunken)', overflowX: 'auto',
                    }}>{accel.fixCommand}</pre>
                  )}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </>
  )
}
