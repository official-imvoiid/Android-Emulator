import { useEffect, useRef } from 'react'

/* The activity log used to sit in a permanent sidebar competing with the thing
   you were actually doing. It is now one quiet line at the bottom that expands
   only when you want the detail. */
export default function StatusBar({ logs, progress, connected, open, setOpen, toast }) {
  const endRef = useRef(null)
  const boxRef = useRef(null)

  useEffect(() => {
    if (!open) return
    const box = boxRef.current
    if (!box) return
    const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 120
    if (nearBottom) endRef.current?.scrollIntoView({ block: 'end' })
  }, [logs, open])

  const busy = progress && progress.stage !== 'done'
  const latest = logs[logs.length - 1]

  let message = 'Ready'
  let tone = ''
  if (toast) {
    message = toast.message
    tone = toast.level === 'bad' ? 'bad' : 'good'
  } else if (busy) {
    const verb = progress.stage === 'downloading' ? 'Downloading'
      : progress.stage === 'extracting' ? 'Unpacking'
      : progress.stage === 'verifying' ? 'Checking the download' : progress.stage
    message = `${verb}…`
  } else if (latest) {
    message = latest.message
    tone = latest.level === 'error' ? 'bad' : ''
  }

  return (
    <div className="statusbar">
      {open && (
        <div className="logdrawer" ref={boxRef}>
          {logs.length === 0 && <div className="l">Nothing has happened yet.</div>}
          {logs.map((l, i) => (
            <div key={i} className={`l ${l.level || ''}`}>
              <span className="t">{l.time}</span>{l.message}
            </div>
          ))}
          <div ref={endRef} />
        </div>
      )}

      <div className="strip">
        {busy && <span className="spin" />}
        <span className={`msg ${tone}`}>{message}</span>

        {busy && (
          <span className="meter">
            <span className="track">
              <span style={{ width: `${progress.percent || 0}%` }} />
            </span>
            <span className="cap">
              <span>{(progress.percent ?? 0).toFixed(0)}%</span>
              <span>{progress.stage}</span>
            </span>
          </span>
        )}

        {!connected && <span className="badge warn">Reconnecting</span>}

        <button className="btn quiet sm" onClick={() => setOpen(!open)}
                title={open ? 'Hide the detailed activity log' : 'Show the detailed activity log'}>
          {open ? 'Hide details' : 'Show details'}
        </button>
      </div>
    </div>
  )
}
