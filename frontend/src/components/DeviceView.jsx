import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api.js'

/* Two very different layouts, because the emulator may already be showing you
   the device:

   - Emulator has its own window  -> do NOT mirror the screen again. That window
     already has power, volume, rotate, screenshot and the nav bar. This tab
     gives you the things that window makes awkward instead.
   - Emulator started hidden      -> this app is the only way to see the device,
     so the handset and its keys are shown here. */

const NAV_KEYS = [
  { key: 'back', glyph: '◁', name: 'Back', doc: 'Go back one screen.' },
  { key: 'home', glyph: '○', name: 'Home', doc: 'Return to the home screen.' },
  { key: 'recents', glyph: '□', name: 'Recent apps', doc: 'Open the app switcher.' },
]

const EXTRA_KEYS = [
  { key: 'notifications', name: 'Notification shade', doc: 'Pulls down the notification panel, the same as swiping from the top of the screen.' },
  { key: 'search', name: 'Search / assistant', doc: 'Opens device search.' },
  { key: 'menu', name: 'Legacy menu', doc: 'The old menu key. Only older apps still react to it.' },
  { key: 'brightness_up', name: 'Brighter', doc: 'Raises screen brightness by one step.' },
  { key: 'brightness_down', name: 'Dimmer', doc: 'Lowers screen brightness by one step.' },
  { key: 'mute', name: 'Mute audio', doc: 'Silences the device.' },
  { key: 'media_play_pause', name: 'Play / pause', doc: 'Controls whatever media is playing.' },
  { key: 'delete', name: 'Backspace', doc: 'Deletes one character in the focused text field.' },
]

/* Examples that actually print something, so the first thing anyone tries
   produces visible output rather than an empty box. */
const EXAMPLES = [
  { name: 'Android version', cmd: 'getprop ro.build.version.release', doc: 'Prints the Android version running on the device.' },
  { name: 'Device model', cmd: 'getprop ro.product.model', doc: 'Prints the model name Android reports to apps.' },
  { name: 'Storage free', cmd: 'df -h /data', doc: 'Shows how much of the device storage is used.' },
  { name: 'Memory', cmd: 'cat /proc/meminfo | head -3', doc: 'Shows total and free memory inside the device.' },
  { name: 'Apps you installed', cmd: 'pm list packages -3', doc: 'Lists only apps you installed yourself — empty on a fresh device.' },
  { name: 'All apps', cmd: 'pm list packages', doc: 'Lists every package on the device, including system apps.' },
]

const ORIENTATIONS = [
  { value: 0, name: 'Portrait' },
  { value: 1, name: 'Landscape' },
  { value: 2, name: 'Upside down' },
  { value: 3, name: 'Landscape ⟲' },
]

export default function DeviceView({ device, adbAvailable, onStop, onError, stopping }) {
  const [frame, setFrame] = useState(null)
  const [mirror, setMirror] = useState(true)
  const [orientation, setOrientation] = useState(0)
  const [busy, setBusy] = useState(false)
  const [typed, setTyped] = useState('')
  const [command, setCommand] = useState('')
  const [output, setOutput] = useState('')
  const [ran, setRan] = useState('')
  const [apk, setApk] = useState('')
  const [charge, setCharge] = useState(100)
  const [showKeys, setShowKeys] = useState(false)
  const tick = useRef(null)

  const usable = Boolean(device?.booted && adbAvailable)
  const embedded = Boolean(device?.headless)   // no native window -> mirror here

  const grab = useCallback(async () => {
    if (!usable) return
    try {
      const resp = await fetch(api.screenshotUrl())
      if (!resp.ok) return
      const blob = await resp.blob()
      setFrame((old) => {
        if (old) URL.revokeObjectURL(old)
        return URL.createObjectURL(blob)
      })
    } catch { /* transient */ }
  }, [usable])

  useEffect(() => {
    if (!usable || !mirror || !embedded) {
      clearInterval(tick.current)
      return
    }
    grab()
    tick.current = setInterval(grab, 1600)
    return () => clearInterval(tick.current)
  }, [usable, mirror, embedded, grab])

  const send = async (fn) => {
    setBusy(true)
    try {
      await fn()
      if (embedded) setTimeout(grab, 350)
    } catch (err) {
      onError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const runCommand = async (cmd) => {
    const text = (cmd || '').trim()
    if (!usable || busy || !text) return
    await send(async () => {
      const res = await api.shell(text)
      setRan(text)
      setOutput((res.output || '').trimEnd())
    })
  }

  if (!device) {
    return (
      <div className="panel">
        <header>
          <h2>No device is running</h2>
          <p>Choose an Android version on the Set up tab and start a device.</p>
        </header>
      </div>
    )
  }

  const summary = (
    <div className="panel">
      <header className="row">
        <div style={{ minWidth: 0 }}>
          <h2>{device.name}</h2>
          <p>
            Android API {device.apiLevel} · {device.ramMb} MB memory · {device.cores} cores ·{' '}
            {device.storageGb} GB storage
          </p>
        </div>
        <span className="spacer" />
        <div className="row">
          {device.booted
            ? <span className="badge go">Ready</span>
            : <span className="badge warn"><span className="spin" /> Starting up</span>}
          {device.ephemeral && <span className="badge">Temporary</span>}
          {device.playStore && <span className="badge">Play Store</span>}
          <button className="btn stop sm" onClick={onStop} disabled={stopping}>
            {stopping ? <><span className="spin" /> Shutting down</> : 'Shut down'}
          </button>
        </div>
      </header>
    </div>
  )

  return (
    <>
      {summary}

      {!adbAvailable && (
        <div className="notice warn">
          <span className="mark">!</span>
          <div>
            <h4>These tools need one more package</h4>
            <p>
              Install <code>platform-tools</code> from the Storage tab. Without it this app cannot
              talk to the device at all.
            </p>
          </div>
        </div>
      )}

      {/* ============ mirrored handset, only when there is no native window ==== */}
      {embedded && (
        <div className="panel">
          <div className="body">
            <div className="bench">
              <div>
                <div className="chassis">
                  <div className="handset">
                    <span className="speaker" aria-hidden="true" />
                    <button className="sidekey power" title="Power — sleep or wake the screen"
                            aria-label="Power" disabled={!usable || busy}
                            onClick={() => send(() => api.pressKey('power'))} />
                    <button className="sidekey vol-up" title="Volume up" aria-label="Volume up"
                            disabled={!usable || busy}
                            onClick={() => send(() => api.pressKey('volume_up'))} />
                    <button className="sidekey vol-dn" title="Volume down" aria-label="Volume down"
                            disabled={!usable || busy}
                            onClick={() => send(() => api.pressKey('volume_down'))} />
                    <div className="glass">
                      {frame
                        ? <img src={frame} alt={`Screen of ${device.name}`} />
                        : <p className="idle">
                            {device.booted ? 'Waiting for the first frame…'
                              : 'Android is starting. The first boot on a new version takes a few minutes.'}
                          </p>}
                    </div>
                    <div className="navbar">
                      {NAV_KEYS.map((k) => (
                        <button key={k.key} title={`${k.name} — ${k.doc}`} aria-label={k.name}
                                disabled={!usable || busy}
                                onClick={() => send(() => api.pressKey(k.key))}>
                          {k.glyph}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
                <p className="chassis-caption">
                  The keys on the right edge are power and volume, where a real phone has them.
                </p>
              </div>

              <div className="stack">
                <div className="row">
                  <button className="btn sm" disabled={!usable} onClick={() => setMirror((m) => !m)}>
                    {mirror ? 'Pause mirroring' : 'Resume mirroring'}
                  </button>
                  <button className="btn sm" disabled={!usable} onClick={grab}>Refresh now</button>
                </div>
                <p className="lead tiny">
                  The device is running hidden, so this is the only view of it. Mirroring refreshes
                  about once a second — it is a live picture, not a video stream.
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ==== when the emulator owns a window, explain the split of duties ===== */}
      {!embedded && (
        <div className="notice">
          <span className="mark">i</span>
          <div>
            <h4>Tap and swipe in the emulator's own window</h4>
            <p>
              That window has its own side bar for power, volume, rotate, screenshots and the
              navigation buttons, so this tab does not repeat them. What is below are the things
              that window makes awkward — installing an app from your PC, typing long text, faking
              the battery level, and running commands.
            </p>
            <p className="tiny">
              Prefer everything in one place? Start the device again with <b>“Show it inside this
              app”</b> on the Set up tab and the screen appears here instead.
            </p>
          </div>
        </div>
      )}

      {/* ========================= tools, in a grid so space is actually used == */}
      <div className="toolgrid">
        <div className="panel">
          <header>
            <h2>Install an app from this PC</h2>
            <p>Point at an <code>.apk</code> file and it is installed on the device, replacing any earlier version.</p>
          </header>
          <div className="body">
            <div className="row">
              <input type="text" value={apk} disabled={!usable}
                     placeholder="C:\Users\you\Downloads\app.apk"
                     onChange={(e) => setApk(e.target.value)} style={{ flex: 1 }} />
              <button className="btn go" disabled={!usable || busy || !apk.trim()}
                      onClick={() => send(async () => {
                        const res = await api.installApk(apk.trim())
                        setRan(`install ${apk.trim()}`)
                        setOutput((res.output || 'Installed.').trimEnd())
                      })}>
                {busy ? <span className="spin" /> : 'Install'}
              </button>
            </div>
          </div>
        </div>

        <div className="panel">
          <header>
            <h2>Type on the device</h2>
            <p>Sends text straight to the field that has focus — handy for long passwords or links.</p>
          </header>
          <div className="body">
            <div className="row">
              <input type="text" value={typed} disabled={!usable}
                     placeholder="Text to send"
                     onChange={(e) => setTyped(e.target.value)} style={{ flex: 1 }} />
              <button className="btn go" disabled={!usable || busy || !typed}
                      onClick={() => send(async () => { await api.typeText(typed); setTyped('') })}>
                Send
              </button>
            </div>
          </div>
        </div>

        <div className="panel">
          <header>
            <h2>Fake the battery level</h2>
            <p>Tells Android the battery is this low, so you can see how apps react. Reset gives control back.</p>
          </header>
          <div className="body">
            <div className="f">
              <label>Battery <span className="amount">{charge}%</span></label>
              <div className="row">
                <input type="range" min={0} max={100} value={charge} disabled={!usable}
                       onChange={(e) => setCharge(Number(e.target.value))}
                       onMouseUp={() => send(() => api.battery(charge))}
                       onTouchEnd={() => send(() => api.battery(charge))}
                       style={{ flex: 1 }} />
                <button className="btn sm" disabled={!usable || busy}
                        onClick={() => send(async () => { await api.battery(null, true); setCharge(100) })}>
                  Reset
                </button>
              </div>
            </div>
          </div>
        </div>

        <div className="panel">
          <header>
            <h2>Screen orientation</h2>
            <p>Automatic rotation is switched off first, or the simulated sensor turns it straight back.</p>
          </header>
          <div className="body">
            <div className="switch">
              {ORIENTATIONS.map((o) => (
                <button key={o.value} aria-pressed={orientation === o.value}
                        disabled={!usable || busy}
                        onClick={() => { setOrientation(o.value); send(() => api.rotate(o.value)) }}>
                  {o.name}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* ------------------------------------------------- command line + keys */}
      <div className="panel">
        <header>
          <h2>Run a command on the device</h2>
          <p>
            Runs inside the emulated Android only — it cannot see or change anything on this PC.
            Pick an example below, or type your own.
          </p>
        </header>
        <div className="body">
          <div className="filters">
            {EXAMPLES.map((ex) => (
              <button key={ex.cmd} title={ex.doc} disabled={!usable || busy}
                      onClick={() => { setCommand(ex.cmd); runCommand(ex.cmd) }}>
                {ex.name}
              </button>
            ))}
          </div>

          <div className="row">
            <input type="text" value={command} disabled={!usable}
                   placeholder="Type a command, e.g. getprop ro.product.model"
                   style={{ flex: 1, fontFamily: 'var(--mono)' }}
                   onChange={(e) => setCommand(e.target.value)}
                   onKeyDown={(e) => { if (e.key === 'Enter') runCommand(command) }} />
            <button className="btn" disabled={!usable || busy || !command.trim()}
                    onClick={() => runCommand(command)}>
              {busy ? <span className="spin" /> : 'Run'}
            </button>
          </div>

          {ran && (
            <div>
              <p className="tiny faint" style={{ margin: '0 0 6px' }}>
                Ran <code>{ran}</code>
              </p>
              {output
                ? <pre className="output">{output}</pre>
                : <pre className="output empty-out">
                    The command finished successfully and printed nothing.
                    {ran.includes('-3') && ' “-3” asks only for apps you installed yourself, and there are none yet.'}
                  </pre>}
            </div>
          )}
        </div>
      </div>

      <div>
        <button className="disclose" aria-expanded={showKeys} onClick={() => setShowKeys((v) => !v)}>
          <span className="caret">{showKeys ? '▾' : '▸'}</span>
          More buttons, and what each one does
          <span className="spacer" />
          <span className="faint tiny">{EXTRA_KEYS.length} controls</span>
        </button>
        {showKeys && (
          <div className="controls-doc" style={{ marginTop: 10 }}>
            {EXTRA_KEYS.map((k) => (
              <div className="ctl" key={k.key}>
                <div className="act">
                  <button className="btn sm" disabled={!usable || busy}
                          onClick={() => send(() => api.pressKey(k.key))}>
                    {k.name}
                  </button>
                </div>
                <div className="doc">
                  <b>{k.name}</b>
                  <span>{k.doc}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  )
}
