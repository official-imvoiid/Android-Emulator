import { useEffect, useMemo, useState } from 'react'
import { api, formatMb } from '../api.js'

const STEPS = [
  { title: 'Android version', hint: 'Which release to run' },
  { title: 'Device power', hint: 'Memory, cores, storage' },
  { title: 'Confirm', hint: 'Review, then start' },
]

/* Most people should never have to think about megabytes. Three presets sized
   from the host cover the real cases, and the sliders stay available for anyone
   who wants them. */
function buildPresets(options) {
  if (!options) return []
  const cap = (n, lo, hi) => Math.max(lo, Math.min(hi, n))
  const cores = options.cores
  const ram = options.ram
  return [
    {
      id: 'light',
      name: 'Light',
      why: 'Gentlest on your PC. Good for simple apps and browsing.',
      ramMb: cap(2048, ram.min, ram.max),
      cores: cap(2, cores.min, cores.max),
      storageGb: 8,
    },
    {
      id: 'balanced',
      name: 'Balanced',
      why: 'A sensible everyday device. Start here if you are unsure.',
      ramMb: cap(4096, ram.min, ram.max),
      cores: cap(4, cores.min, cores.max),
      storageGb: 16,
    },
    {
      id: 'performance',
      name: 'Fast',
      why: 'Uses more of your PC. Best for games and heavy apps.',
      ramMb: cap(8192, ram.min, ram.max),
      cores: cap(cores.max, cores.min, cores.max),
      storageGb: 32,
    },
  ]
}

export default function SetupView({
  catalog, catalogLoading, catalogError, options, support,
  filters, setFilters, onRefresh,
  spec, setSpec, selected, setSelected,
  onStart, starting, deviceRunning,
}) {
  const [step, setStep] = useState(0)
  const [plan, setPlan] = useState(null)
  const [planError, setPlanError] = useState(null)
  const [planning, setPlanning] = useState(false)
  const [installing, setInstalling] = useState(false)
  const [tuning, setTuning] = useState(false)
  const [preset, setPreset] = useState('balanced')
  const [showEveryBuild, setShowEveryBuild] = useState(false)

  const presets = useMemo(() => buildPresets(options), [options])

  const rows = useMemo(() => {
    const all = catalog?.entries ?? []
    return showEveryBuild ? all : all.filter((e) => e.preferred)
  }, [catalog, showEveryBuild])

  const chosen = useMemo(
    () => (catalog?.entries ?? []).find((e) => e.packagePath === selected) || null,
    [catalog, selected],
  )

  const applyPreset = (p) => {
    setPreset(p.id)
    setSpec({ ...spec, ramMb: p.ramMb, cores: p.cores, storageGb: p.storageGb })
  }

  useEffect(() => {
    if (!selected || step !== 2) return
    let dead = false
    setPlanning(true)
    setPlanError(null)
    api.plan(selected)
      .then((p) => !dead && setPlan(p))
      .catch((e) => !dead && setPlanError(e.message))
      .finally(() => !dead && setPlanning(false))
    return () => { dead = true }
  }, [selected, step, installing])

  const download = async () => {
    if (!selected) return
    setInstalling(true)
    setPlanError(null)
    try {
      const { jobId } = await api.install(selected)
      for (;;) {
        await new Promise((r) => setTimeout(r, 1200))
        const job = await api.job(jobId)
        if (job.state === 'done') break
        if (job.state === 'error') throw new Error(job.error || 'The download did not finish.')
        if (job.state === 'cancelled') throw new Error('The download was cancelled.')
      }
      setPlan(await api.plan(selected))
    } catch (err) {
      setPlanError(err.message)
    } finally {
      setInstalling(false)
    }
  }

  const ready = plan?.alreadyInstalled === true

  return (
    <>
      <div className="progress-steps">
        {STEPS.map((s, i) => (
          <div key={s.title} className={i === step ? 'now' : i < step ? 'was' : ''}>
            <span className="num">{i < step ? '✓' : i + 1}</span>
            <span className="txt">
              <b>{s.title}</b>
              <span>{s.hint}</span>
            </span>
          </div>
        ))}
      </div>

      {/* =============================================== step 1 — the version */}
      {step === 0 && (
        <div className="panel">
          <header>
            <h2>Which version of Android do you want?</h2>
            <p>
              This list comes straight from Google each time you open it, so a newly released
              Android shows up here on its own. Larger downloads are newer versions.
            </p>
          </header>

          <div className="body">
            <div className="row">
              <div className="filters">
                {(catalog?.formFactors ?? []).map((f) => (
                  <button key={f.id} aria-pressed={filters.formFactor === f.id}
                          title={`Show ${f.name.toLowerCase()} system images`}
                          onClick={() => setFilters({ ...filters, formFactor: f.id })}>
                    {f.name}
                  </button>
                ))}
              </div>
              <span className="spacer" />
              <button className="btn quiet sm" onClick={onRefresh} disabled={catalogLoading}
                      title="Re-read the list from Google">
                {catalogLoading ? <><span className="spin" /> Checking</> : 'Check for new versions'}
              </button>
            </div>

            {catalogError && (
              <div className="notice bad">
                <span className="mark">!</span>
                <div>
                  <h4>The version list could not be loaded</h4>
                  <p>{catalogError}</p>
                </div>
              </div>
            )}

            {catalogLoading && !catalog && (
              <div className="blank"><span className="spin" /> Reading the list from Google…</div>
            )}

            {rows.length > 0 && (
              <div className="picker">
                {rows.map((e) => (
                  <button key={e.packagePath} className="pick"
                          aria-pressed={selected === e.packagePath}
                          onClick={() => setSelected(e.packagePath)}>
                    <span className="mark" aria-hidden="true" />
                    <span style={{ minWidth: 0 }}>
                      <span className="title">
                        {e.label}
                        {e.packagePath === catalog?.latestStable && <span className="badge go">Newest</span>}
                        {e.installed && !e.upgradable && <span className="badge">Already downloaded</span>}
                        {e.upgradable && <span className="badge warn">Update available</span>}
                        {e.isPreview && <span className="badge warn">Preview build</span>}
                      </span>
                      <span className="detail">
                        API level {e.apiLevel}
                        {e.codename ? ` · ${e.codename}` : ''}
                        {e.pageSize16kb ? ' · matches modern phones (16 KB pages)' : ''}
                      </span>
                    </span>
                    <span className="weight">
                      <b>{formatMb(e.downloadMb)}</b>
                      <span>{e.installed ? 'on disk' : 'to download'}</span>
                    </span>
                  </button>
                ))}
              </div>
            )}

            {!catalogLoading && rows.length === 0 && !catalogError && (
              <div className="blank">Nothing matches these filters.</div>
            )}

            <div className="row">
              <button className="btn quiet sm" aria-pressed={filters.previews}
                      title="Beta and developer-preview builds. Not recommended for everyday use."
                      onClick={() => setFilters({ ...filters, previews: !filters.previews })}>
                {filters.previews ? '✓ ' : ''}Include unfinished preview builds
              </button>
              <button className="btn quiet sm" aria-pressed={showEveryBuild}
                      title="Google publishes more than one build per version; normally the best one is picked for you."
                      onClick={() => setShowEveryBuild((v) => !v)}>
                {showEveryBuild ? '✓ ' : ''}Show every build
              </button>
            </div>
          </div>

          <footer>
            <span className="subtle tiny">
              {chosen ? <>Selected: <b>{chosen.label}</b></> : 'Pick a version to continue'}
            </span>
            <span className="spacer" />
            <button className="btn go" disabled={!selected} onClick={() => setStep(1)}>Next</button>
          </footer>
        </div>
      )}

      {/* ============================================== step 2 — device power */}
      {step === 1 && options && (
        <>
          <div className="panel">
            <header>
              <h2>How powerful should the device be?</h2>
              <p>
                A stronger device runs apps faster but takes more from your PC. You can change
                any of this later by making a new device.
              </p>
            </header>

            <div className="body">
              <div className="tiles three">
                {presets.map((p) => (
                  <button key={p.id} className="tile" aria-pressed={preset === p.id}
                          onClick={() => applyPreset(p)}>
                    <b>{p.name}</b>
                    <span className="why">{p.why}</span>
                    <span className="spec">
                      {formatMb(p.ramMb)} memory · {p.cores} cores · {p.storageGb} GB
                    </span>
                  </button>
                ))}
              </div>

              <p className="lead tiny">
                Your PC has {formatMb(options.ram.hostTotalMb)} of memory and{' '}
                {options.cores.hostLogicalCpus} processor cores. The device only uses what it needs.
              </p>

              <button className="disclose" aria-expanded={tuning} onClick={() => setTuning((v) => !v)}>
                <span className="caret">{tuning ? '▾' : '▸'}</span>
                Set the exact numbers myself
                <span className="spacer" />
                <span className="faint tiny">optional</span>
              </button>

              {tuning && (
                <div className="settings" style={{ paddingTop: 4 }}>
                  <div className="f">
                    <label>Memory <span className="amount">{formatMb(spec.ramMb)}</span></label>
                    <span className="explain">
                      How much RAM the device gets. Android 17 will not start with less than 4 GB.
                    </span>
                    <input type="range" min={options.ram.min} max={options.ram.max}
                           step={options.ram.step} value={spec.ramMb}
                           onChange={(e) => { setPreset('custom'); setSpec({ ...spec, ramMb: Number(e.target.value) }) }} />
                    <span className="ends">
                      <span>{formatMb(options.ram.min)}</span><span>{formatMb(options.ram.max)}</span>
                    </span>
                  </div>

                  <div className="f">
                    <label>Processor cores <span className="amount">{spec.cores}</span></label>
                    <span className="explain">
                      More cores make the device faster but leave less for the rest of your PC.
                    </span>
                    <input type="range" min={options.cores.min} max={options.cores.max} step={1}
                           value={spec.cores}
                           onChange={(e) => { setPreset('custom'); setSpec({ ...spec, cores: Number(e.target.value) }) }} />
                    <span className="ends">
                      <span>{options.cores.min}</span><span>{options.cores.max}</span>
                    </span>
                  </div>

                  <div className="f">
                    <label>Storage <span className="amount">{spec.storageGb} GB</span></label>
                    <span className="explain">
                      Room for apps and files. Space is only used as the device fills up, not
                      reserved straight away.
                    </span>
                    <input type="range" min={options.storage.min} max={options.storage.max}
                           step={options.storage.step} value={spec.storageGb}
                           onChange={(e) => { setPreset('custom'); setSpec({ ...spec, storageGb: Number(e.target.value) }) }} />
                    <span className="ends">
                      <span>{options.storage.min} GB</span><span>{options.storage.max} GB</span>
                    </span>
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="panel">
            <header>
              <h2>How should it behave?</h2>
            </header>
            <div className="body">
              <div className="settings">
                <div className="f">
                  <label>Keep files between sessions</label>
                  <span className="explain">
                    {spec.persistent
                      ? 'Apps you install and files you save will still be there next time.'
                      : 'The device resets to factory-fresh every time it starts. The downloaded Android is reused, so nothing is downloaded again.'}
                  </span>
                  <div className="switch">
                    <button aria-pressed={spec.persistent} onClick={() => setSpec({ ...spec, persistent: true })}>
                      Keep my data
                    </button>
                    <button aria-pressed={!spec.persistent} onClick={() => setSpec({ ...spec, persistent: false })}>
                      Start fresh each time
                    </button>
                  </div>
                </div>

                <div className="f">
                  <label>Where the screen appears</label>
                  <span className="explain">
                    {spec.headless
                      ? 'The device runs hidden and its screen is mirrored inside this app, so everything is in one window. You tap using the buttons here.'
                      : "The emulator opens its own window, which you can tap and swipe directly. That window brings its own power, volume and rotate controls."}
                  </span>
                  <div className="switch">
                    <button aria-pressed={!spec.headless} onClick={() => setSpec({ ...spec, headless: false })}>
                      Its own window
                    </button>
                    <button aria-pressed={spec.headless} onClick={() => setSpec({ ...spec, headless: true })}>
                      Inside this app
                    </button>
                  </div>
                </div>

                <div className="f">
                  <label>Screen size</label>
                  <span className="explain">The shape and resolution of the simulated display.</span>
                  <select value={spec.deviceProfile}
                          onChange={(e) => setSpec({ ...spec, deviceProfile: e.target.value })}>
                    {options.deviceProfiles.map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                </div>

                <div className="f">
                  <label>Graphics</label>
                  <span className="explain">
                    {options.gpuModes.find((g) => g.id === spec.gpuMode)?.detail}
                  </span>
                  <select value={spec.gpuMode} onChange={(e) => setSpec({ ...spec, gpuMode: e.target.value })}>
                    {options.gpuModes.map((g) => (
                      <option key={g.id} value={g.id}>{g.name}</option>
                    ))}
                  </select>
                  <span className="after">
                    If apps look wrong or the screen flickers, try “Software” — it is slower but
                    works on any graphics card.
                  </span>
                </div>

                <div className="f">
                  <label>Device name</label>
                  <span className="explain">Only used to tell your saved devices apart.</span>
                  <input type="text" value={spec.name} maxLength={40}
                         onChange={(e) => setSpec({ ...spec, name: e.target.value.replace(/[^A-Za-z0-9_.-]/g, '_') })} />
                </div>
              </div>
            </div>
            <footer>
              <button className="btn" onClick={() => setStep(0)}>Back</button>
              <span className="spacer" />
              <button className="btn go" onClick={() => setStep(2)}>Next</button>
            </footer>
          </div>
        </>
      )}

      {/* ==================================================== step 3 — confirm */}
      {step === 2 && (
        <>
          <div className="panel">
            <header>
              <h2>Ready to go?</h2>
              <p>Nothing is downloaded until you press the button at the bottom.</p>
            </header>

            <div className="body">
              {planning && <div className="blank"><span className="spin" /> Working out what is needed…</div>}

              {planError && (
                <div className="notice bad">
                  <span className="mark">!</span>
                  <div>
                    <h4>Something went wrong</h4>
                    <p>{planError}</p>
                  </div>
                </div>
              )}

              {plan && !planning && (
                <>
                  <table className="grid">
                    <tbody>
                      <tr>
                        <td className="k">Android version</td>
                        <td><b>{chosen?.label}</b> · API level {plan.image.apiLevel}</td>
                      </tr>
                      <tr>
                        <td className="k">Device power</td>
                        <td>
                          {formatMb(spec.ramMb)} memory · {spec.cores} cores · {spec.storageGb} GB storage
                        </td>
                      </tr>
                      <tr>
                        <td className="k">Your data</td>
                        <td>{spec.persistent ? 'Kept between sessions' : 'Wiped every time it starts'}</td>
                      </tr>
                      <tr>
                        <td className="k">Google Play Store</td>
                        <td>{spec.playStore ? 'Included and ready to sign in' : 'Not included'}</td>
                      </tr>
                      <tr>
                        <td className="k">Screen appears</td>
                        <td>{spec.headless ? 'Inside this app' : "In the emulator's own window"}</td>
                      </tr>
                      <tr>
                        <td className="k">To download now</td>
                        <td>
                          <b>{formatMb(plan.downloadMb)}</b>{' '}
                          <span className="subtle">
                            — about {formatMb(plan.estimatedDiskMb)} once unpacked,
                            and you have {formatMb(plan.freeDiskMb)} free
                          </span>
                        </td>
                      </tr>
                    </tbody>
                  </table>

                  {plan.warnings.map((w) => (
                    <div className="notice warn" key={w}>
                      <span className="mark">!</span>
                      <div><h4>Worth knowing</h4><p>{w}</p></div>
                    </div>
                  ))}

                  {ready ? (
                    <div className="notice good">
                      <span className="mark">✓</span>
                      <div>
                        <h4>Everything is already downloaded</h4>
                        <p>Starting the device will not use any data.</p>
                      </div>
                    </div>
                  ) : (
                    <div className="notice">
                      <span className="mark">i</span>
                      <div>
                        <h4>What gets downloaded</h4>
                        <p>
                          These files come directly from Google and are checked against Google's own
                          fingerprint after downloading. If your connection drops, the download
                          picks up where it left off.
                        </p>
                        <table className="grid" style={{ marginTop: 10 }}>
                          <tbody>
                            {plan.packages.map((p) => (
                              <tr key={p.path}>
                                <td className="mono">{p.path}</td>
                                <td className="right mono">{formatMb(p.sizeMb)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>

            <footer>
              <button className="btn" onClick={() => setStep(1)} disabled={installing}>Back</button>
              <span className="spacer" />
              {plan && !ready && (
                <button className="btn go lg" onClick={download} disabled={installing}>
                  {installing
                    ? <><span className="spin" /> Downloading… you can watch progress below</>
                    : <>Download {formatMb(plan.downloadMb)} and continue</>}
                </button>
              )}
              {plan && ready && (
                <button className="btn go lg" disabled={starting || deviceRunning}
                        onClick={() => onStart({ ...spec, packagePath: selected, apiLevel: plan.image.apiLevel })}>
                  {starting ? <><span className="spin" /> Starting…</>
                    : deviceRunning ? 'Another device is already running'
                    : 'Start the device'}
                </button>
              )}
            </footer>
          </div>

          {support && (
            <div className="panel">
              <header>
                <h2>Which Android versions this app supports</h2>
              </header>
              <div className="body">
                <table className="grid">
                  <tbody>
                    <tr>
                      <td className="k">Newest</td>
                      <td>{support.highest_known_android} — the latest Google has released</td>
                    </tr>
                    <tr>
                      <td className="k">Oldest</td>
                      <td>Android 7, and everything in between</td>
                    </tr>
                    <tr>
                      <td className="k">Versions not out yet</td>
                      <td>
                        Appear automatically. The list is read from Google, not built into this app,
                        so you do not need to update anything.
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </>
  )
}
