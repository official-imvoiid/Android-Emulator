import { useCallback, useEffect, useState } from 'react'
import { api, formatBytes } from '../api.js'

const PLACES = [
  { path: '/sdcard/Download', name: 'Downloads' },
  { path: '/sdcard/Pictures', name: 'Pictures' },
  { path: '/sdcard/DCIM', name: 'Camera' },
  { path: '/sdcard/Music', name: 'Music' },
  { path: '/sdcard', name: 'All storage' },
]

export default function FilesView({ device, adbAvailable, onError, onInfo }) {
  const [pc, setPc] = useState(null)
  const [pcPick, setPcPick] = useState(null)
  const [phone, setPhone] = useState(null)
  const [phonePick, setPhonePick] = useState(null)
  const [busy, setBusy] = useState(false)

  const usable = Boolean(device?.booted && adbAvailable)

  const loadPc = useCallback(async (path) => {
    try {
      setPc(await api.listHost(path))
      setPcPick(null)
    } catch (err) { onError(err.message) }
  }, [onError])

  const loadPhone = useCallback(async (path) => {
    if (!usable) return
    try {
      setPhone(await api.listDevice(path))
      setPhonePick(null)
    } catch (err) { onError(err.message) }
  }, [usable, onError])

  useEffect(() => { loadPc() }, [loadPc])
  useEffect(() => { if (usable) loadPhone('/sdcard/Download') }, [usable, loadPhone])

  const move = async (fn, message) => {
    setBusy(true)
    try {
      await fn()
      onInfo(message)
      await Promise.all([loadPc(pc?.path), loadPhone(phone?.path || '/sdcard/Download')])
    } catch (err) {
      onError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (!usable) {
    return (
      <div className="panel">
        <header>
          <h2>Move files between this PC and the device</h2>
          <p>
            The Android device is sealed off from your PC — it cannot see your files, and your PC
            cannot see its storage. This page is the doorway between the two.
          </p>
        </header>
        <div className="body">
          {!device && (
            <div className="notice">
              <span className="mark">i</span>
              <div>
                <h4>Start a device first</h4>
                <p>Once a device is running, its storage will appear here next to your own files.</p>
              </div>
            </div>
          )}
          {device && !device.booted && (
            <div className="notice warn">
              <span className="mark">!</span>
              <div>
                <h4>The device is still starting</h4>
                <p>File transfer becomes available once Android has finished booting.</p>
              </div>
            </div>
          )}
          {device && !adbAvailable && (
            <div className="notice warn">
              <span className="mark">!</span>
              <div>
                <h4>A missing package blocks file transfer</h4>
                <p>Install <code>platform-tools</code> from the Storage tab and try again.</p>
              </div>
            </div>
          )}
        </div>
      </div>
    )
  }

  return (
    <>
      <div className="panel">
        <header>
          <h2>Move files between this PC and the device</h2>
          <p>
            Pick a file on one side, then use the arrows in the middle to copy it across.
            Double-click a folder to open it.
          </p>
        </header>

        <div className="body">
          <div className="two-up">
            <div className="browser">
              <header>
                <b>This PC</b>
                <span className="where" title={pc?.path}>{pc?.path || '…'}</span>
                <button className="btn quiet sm" disabled={!pc?.parent}
                        title="Go to the folder above" onClick={() => loadPc(pc.parent)}>
                  Up
                </button>
              </header>
              <div className="items">
                {(pc?.entries ?? []).map((e) => (
                  <button key={e.path} className="item" aria-pressed={pcPick === e.path}
                          onClick={() => (e.isDir ? loadPc(e.path) : setPcPick(e.path))}>
                    <span className="kind">{e.isDir ? '📁' : '📄'}</span>
                    <span className="nm">{e.name}</span>
                    <span className="sz">{e.isDir ? '' : formatBytes(e.size)}</span>
                  </button>
                ))}
                {pc?.entries?.length === 0 && <div className="blank">This folder is empty</div>}
              </div>
            </div>

            <div className="transfer-arrows">
              <button className="btn go" disabled={busy || !pcPick}
                      title={pcPick ? `Copy ${pcPick} to the device` : 'Select a file on the left first'}
                      onClick={() => move(
                        () => api.push(pcPick, phone?.path || '/sdcard/Download'),
                        'File copied to the device.',
                      )}>
                {busy ? <span className="spin" /> : '→'}
              </button>
              <button className="btn go" disabled={busy || !phonePick}
                      title={phonePick ? `Copy ${phonePick} to this PC` : 'Select a file on the right first'}
                      onClick={() => move(
                        () => api.pull(phonePick, pc?.path),
                        'File copied to this PC.',
                      )}>
                {busy ? <span className="spin" /> : '←'}
              </button>
            </div>

            <div className="browser">
              <header>
                <b>{device.name}</b>
                <span className="where" title={phone?.path}>{phone?.path || '…'}</span>
                <button className="btn quiet sm" disabled={!phone?.parent}
                        title="Go to the folder above" onClick={() => loadPhone(phone.parent)}>
                  Up
                </button>
              </header>
              <div className="items">
                {(phone?.entries ?? []).map((e) => (
                  <button key={e.path} className="item" aria-pressed={phonePick === e.path}
                          onClick={() => (e.isDir ? loadPhone(e.path) : setPhonePick(e.path))}>
                    <span className="kind">{e.isDir ? '📁' : '📄'}</span>
                    <span className="nm">{e.name}</span>
                    <span className="sz">{e.isDir ? '' : formatBytes(e.size)}</span>
                  </button>
                ))}
                {phone?.entries?.length === 0 && <div className="blank">This folder is empty</div>}
              </div>
            </div>
          </div>

          <div className="row">
            <span className="subtle tiny">Jump to:</span>
            <div className="filters">
              {PLACES.map((p) => (
                <button key={p.path} aria-pressed={phone?.path === p.path}
                        onClick={() => loadPhone(p.path)}>
                  {p.name}
                </button>
              ))}
            </div>
          </div>

          <p className="lead tiny">
            {pcPick ? <>Ready to send: <code>{pcPick}</code></> : 'Nothing selected on this PC.'}
            {' · '}
            {phonePick ? <>Ready to fetch: <code>{phonePick}</code></> : 'Nothing selected on the device.'}
          </p>
        </div>
      </div>

      <div className="notice">
        <span className="mark">i</span>
        <div>
          <h4>Why some folders are off limits</h4>
          <p>
            You can browse and write to the device's normal storage. Android's own system files are
            read-only on Play Store devices — that is what keeps the Play Store working properly, so
            this app does not let you write there.
          </p>
        </div>
      </div>
    </>
  )
}
