<h1 align="center">Android Emulator Hub</h1>

<p align="center">
  Choose an Android version, set how powerful the device should be, and run it —
  with the Google Play Store working.
</p>

<p align="center">
  <strong>Python backend · React frontend · no Java, no JDK, no Android Studio</strong>
</p>

---

## What it does

1. **Pick an Android version** from a list read live from Google's own SDK servers.
2. **Choose how powerful** the device is — Light, Balanced or Fast, or set memory, cores
   and storage yourself.
3. **It downloads only what is needed**, checks it against Google's own fingerprint, and
   starts the device with the Play Store ready to sign in to.
4. **Use it** — run it in its own window or mirrored inside the app, move files to and from
   your PC, install APKs, and run commands.

Everything is kept in one folder. Your existing Android tools, `PATH` and system settings are
never touched.

---

## Android version support

**Checked against Google's live repository on 17 August 2026.**

| | |
|---|---|
| **Newest available** | **Android 17** (API 37), plus Android 17 QPR1 (API 37.1) |
| **Oldest available** | **Android 9** (API 28) 64-bit, back to **Android 7.0** (API 24) 32-bit |
| **Named versions built in** | API 14 – 37 |
| **Versions not released yet** | Appear on their own — no update needed |

### What you can install right now

| Version | API level | Codename | Download |
|---|---|---|---|
| Android 17 QPR1 | 37.1 | Cinnamon Bun | 2.05 GB |
| Android 17 | 37.0 | Cinnamon Bun | 2.15 GB |
| Android 16 QPR1 | 36.1 | Baklava | 1.86 GB |
| Android 16 | 36 | Baklava | 1.80 GB |
| Android 15 | 35 | Vanilla Ice Cream | 1.41 GB |
| Android 14 | 34 | Upside Down Cake | 1.41 GB |
| Android 13 | 33 | Tiramisu | 1.56 GB |
| Android 12L | 32 | Snow Cone v2 | 1.40 GB |
| Android 12 | 31 | Snow Cone | 1.33 GB |
| Android 11 | 30 | Red Velvet Cake | 1.31 GB |
| Android 10 | 29 | Quince Tart | 1.24 GB |
| Android 9 | 28 | Pie | 990 MB |

Preview and beta builds are hidden behind a toggle. Tablet, Automotive and Google XR images
are discovered too, under the form-factor filter.

### Why new Android versions just work

Nothing about a new release requires updating this app:

| When Google ships a new Android | Update needed? |
|---|---|
| It appears in the version list | **No** — read from Google |
| The download link is correct | **No** — resolved at runtime |
| Size and fingerprint shown before downloading | **No** |
| A compatible emulator build is chosen | **No** — the image declares what it needs |
| "Newest" points at the new release | **No** — worked out, not hardcoded |
| It boots | **No** |
| The name "Android 18" is shown | A one-line rule handles it |

Only the human-readable *name* lives locally. API levels are never renumbered — API 31 is
Android 12 permanently — and from API 33 upward the name follows `Android = API − 20`, which has
held for five releases running. An unreleased API 38 will simply read "Android 18". Even if that
rule ever broke, only the label would be wrong: the download, the checksum and the boot all come
from Google's data.

---

## Why there is no Java

Google's official `sdkmanager` and `avdmanager` are Java programs. Using them would mean about
150 MB of command-line tools plus a 180 MB JDK — and `avdmanager` has no way to set memory,
CPU cores or storage, which is the whole point of this app.

So the backend does the same work directly in Python: it reads the same repository files
`sdkmanager` reads, resolves the download for your machine, fetches it with resume support,
verifies the checksum, and writes the device configuration itself.

**Result: no JDK, no extra tooling, roughly 330 MB less to download.**

---

## Requirements

| | Needed | Verified with |
|---|---|---|
| **Windows** | 10 or 11, 64-bit | Windows 11 Pro |
| **Python** | 3.10 or newer | 3.10.6 |
| **Node.js** | 18 or newer | 22.19.0 |
| **Disk** | ~5 GB per Android version | — |
| **CPU** | Intel or AMD with virtualisation enabled in BIOS | — |

### Dependencies

Python packages — [`backend/requirements.txt`](backend/requirements.txt), installed into a
virtual environment inside this project, never into your system Python:

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
httpx==0.28.1
```

Node packages — [`frontend/package.json`](frontend/package.json), with exact versions locked in
`frontend/package-lock.json`:

```
react 18.3.1 · react-dom 18.3.1
vite 6.x · @vitejs/plugin-react 4.x
```

Nothing else is required. No JDK, no Android Studio, no global npm installs.

### One Windows setting

Android needs Windows' virtualisation feature to run at usable speed. The app checks this and
tells you if it is off. To turn it on, open **Command Prompt as administrator**, run this, and
restart your PC:

```bash
dism /online /enable-feature /featurename:HypervisorPlatform /all /norestart
```

> The older AEHD driver stops being supported on 31 December 2026, and HAXM was removed from the
> emulator in version 36.2.11. WHPX is the only Windows option with a future, so this app uses it
> and never installs a kernel driver.

---

## Setup

Run once:

```bash
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

This creates `.venv`, installs the Python packages into it, then installs and builds the web
interface. Safe to run again at any time.

## Running it

```bash
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

Opens <http://127.0.0.1:8765>. It listens on this machine only — nothing is exposed to your
network. Press `Ctrl+C` to stop.

### Starting it manually

If you would rather not use the scripts:

```bash
cd /d C:\Users\voiid\Downloads\Android-Emulator\backend
```

```bash
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Then open <http://127.0.0.1:8765> yourself.

### While changing the code

```bash
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1
```

Backend reloads on save at `:8765`, frontend hot-reloads at `:5173`. Open
<http://localhost:5173>. The plain `start.ps1` serves the pre-built files and will not pick up
source changes until you rebuild.

---

## Using the device

### Where the screen appears

Two choices when you set the device up:

**Its own window** *(default)* — the emulator opens a real window you can tap, swipe, drag and
scroll in directly. That window comes with its own side bar for power, volume, rotation,
screenshots and the navigation buttons.

**Inside this app** — the emulator runs hidden and its screen is mirrored on the Device tab, so
everything is in one place. You interact using the on-screen buttons rather than by clicking the
screen.

### What the Device tab gives you

Whichever mode you pick, the Device tab covers the things the emulator window makes awkward:

| Control | What it does |
|---|---|
| **Install an app from this PC** | Point at an `.apk` file and it is installed, replacing any earlier version |
| **Type on the device** | Sends text straight to whichever field has focus — handy for long passwords and links |
| **Fake the battery level** | Tells Android the battery is low so you can see how apps react |
| **Screen orientation** | Portrait, landscape and both upside-down variants |
| **Run a command** | Runs inside the emulated Android only. Six ready-made examples are one click away |

Screen mirroring, buttons and file transfer all need the `platform-tools` package, which is
installed alongside your first Android version by default.

---

## Moving files in and out

The Android device is sealed off from your PC — it cannot see your files, and your PC cannot see
its storage. The **Files** tab is the doorway: your PC on one side, the device on the other, and
arrows in the middle to copy either way.

Transfers are limited to the device's normal storage (`/sdcard` and `/data/local/tmp`). Android's
own system files are read-only on Play Store devices — that is what keeps the Play Store working
properly — so the app does not let you write there.

---

## Keeping data, or starting fresh

**Keep my data** — apps you install and files you save are still there next time.

**Start fresh each time** — the device resets to factory condition on every start. Only the small
user-data area is thrown away; the multi-gigabyte Android download is shared, so nothing is ever
downloaded twice.

---

## Google Play Store

The app uses Google's Play Store images, which are certified as shipped — no sideloading of Google
apps and nothing to work around. They are downloaded from Google onto your machine under the
Android SDK licence; nothing is redistributed here.

These images are deliberately locked: the system partition is read-only and root is not available.
That is exactly what keeps Play certification intact.

---

## Where everything is kept

```
C:\AndroidEmulatorHub\
  sdk\          the Android SDK (emulator, system images, device tools)
  avd\          devices set to keep their data
  tmp\          temporary devices, deleted when they shut down
  cache\        Google's package lists
  downloads\    part-finished downloads, so they can resume
```

Set the `EMUHUB_HOME` environment variable to move it. The default is deliberately short —
Android system images nest deeply, and Windows' 260-character path limit is a real problem under
a long path like `Downloads`.

---

## Project layout

```
backend/
  requirements.txt         Python dependencies
  app/
    settings.py            isolated paths, host detection
    events.py              live log and progress feed
    core/
      discovery.py         finds Google's package lists at runtime
      manifest.py          reads them without hardcoding any names
      resolve.py           builds the version list, matches emulator versions
      download.py          resumable download, checksum, unpack
      versions.py          API level to Android name
      avd.py               writes the device configuration
      emulator.py          starting and stopping devices
      adb.py               buttons, file transfer, commands
      installed.py         what is already on disk
      accel.py             virtualisation check
    api/                   the HTTP endpoints
frontend/
  package.json             Node dependencies
  src/
    App.jsx                layout, tabs, live updates
    components/            SetupView, DeviceView, FilesView, PackagesView, StatusBar
scripts/
  setup.ps1  start.ps1  dev.ps1
RESEARCH.md                the research this is built on
```

While the app is running, full API documentation is generated at
<http://127.0.0.1:8765/docs>.

---

## Licence

This project is MIT licensed — see [LICENSE](LICENSE).

The Android packages it downloads are Google's, covered by the
[Android Software Development Kit License Agreement](https://developer.android.com/studio/terms)
and fetched directly from Google onto your machine.
