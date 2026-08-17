const BASE = ''

async function request(path, options = {}) {
  const resp = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`
    try {
      const body = await resp.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail)
  }
  if (resp.status === 204) return null
  return resp.json()
}

const post = (path, body) =>
  request(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

export const api = {
  health: () => request('/api/health'),

  // system
  systemInfo: () => request('/api/system/info'),
  accel: () => request('/api/system/accel'),
  options: () => request('/api/system/options'),
  cleanup: () => post('/api/system/cleanup'),

  // sdk
  catalog: ({ previews = false, formFactor = 'phone', extensions = false } = {}) =>
    request(
      `/api/sdk/catalog?previews=${previews}&formFactor=${encodeURIComponent(formFactor)}&extensions=${extensions}`,
    ),
  refreshCatalog: () => post('/api/sdk/refresh'),
  installed: () => request('/api/sdk/installed'),
  plan: (packagePath, includePlatformTools = true) =>
    post('/api/sdk/plan', { packagePath, includePlatformTools }),
  install: (packagePath, includePlatformTools = true) =>
    post('/api/sdk/install', { packagePath, includePlatformTools }),
  job: (jobId) => request(`/api/sdk/install/${jobId}`),
  cancelJob: (jobId) => post(`/api/sdk/install/${jobId}/cancel`),
  uninstall: (packagePath) => request(`/api/sdk/installed/${packagePath}`, { method: 'DELETE' }),

  // avd + device
  avds: () => request('/api/avd'),
  deleteAvd: (name) => request(`/api/avd/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  start: (spec) => post('/api/device/start', spec),
  stop: () => post('/api/device/stop'),
  deviceStatus: () => request('/api/device/status'),
  controls: () => request('/api/device/controls'),
  pressKey: (name) => post('/api/device/key', { name }),
  rotate: (orientation) => post('/api/device/rotate', { orientation }),
  typeText: (text) => post('/api/device/text', { text }),
  battery: (level, reset = false) => post('/api/device/battery', { level, reset }),
  shell: (command) => post('/api/device/shell', { command }),
  installApk: (localPath) => post('/api/device/install-apk', { localPath }),
  screenshotUrl: () => `/api/device/screenshot?t=${Date.now()}`,

  // files
  listDevice: (path) => request(`/api/files/device?path=${encodeURIComponent(path)}`),
  listHost: (path) => request(`/api/files/host${path ? `?path=${encodeURIComponent(path)}` : ''}`),
  push: (localPath, devicePath) => post('/api/files/push', { localPath, devicePath }),
  pull: (devicePath, localPath) => post('/api/files/pull', { devicePath, localPath }),
}

/** Live log / progress / device-state stream. Reconnects on drop. */
export function connectEvents(onEvent) {
  let socket = null
  let closed = false
  let retry = 1000

  const open = () => {
    if (closed) return
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    socket = new WebSocket(`${proto}//${window.location.host}/ws`)

    socket.onopen = () => {
      retry = 1000
      onEvent({ kind: 'connection', state: 'open' })
    }
    socket.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data)
        if (data.kind !== 'ping') onEvent(data)
      } catch {
        /* ignore malformed frame */
      }
    }
    socket.onclose = () => {
      if (closed) return
      onEvent({ kind: 'connection', state: 'closed' })
      setTimeout(open, retry)
      retry = Math.min(retry * 2, 15000)
    }
    socket.onerror = () => socket?.close()
  }

  open()
  return () => {
    closed = true
    socket?.close()
  }
}

export function formatMb(mb) {
  if (mb == null) return '—'
  if (mb >= 1024) return `${(mb / 1024).toFixed(2)} GB`
  return `${Math.round(mb)} MB`
}

export function formatBytes(bytes) {
  if (!bytes) return '—'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(value < 10 && unit > 0 ? 1 : 0)} ${units[unit]}`
}
