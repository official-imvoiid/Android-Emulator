"""Turning raw manifest packages into the catalog the UI shows.

Three jobs:
  * filter to images that can actually run on this host, with Play Store
  * de-duplicate (the same package path appears once *per channel*)
  * attach the minimum emulator revision each image declares, so we never
    install an image the installed emulator cannot boot
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from .. import settings
from . import discovery, installed, manifest, versions

# Image variants that ship Google Play. `_ps16k` is the newer 16 KB page-size
# build, which matches how modern real devices are configured.
PLAYSTORE_TAGS = {"google_apis_playstore"}
PAGE_SIZE_16KB_TAG = "page_size_16kb"

CHANNEL_RANK = {"stable": 0, "beta": 1, "dev": 2, "canary": 3}

# The Play Store tag alone is not enough to identify a phone image: XR headset,
# automotive-display and tablet images all carry `google_apis_playstore` too.
# Offering them under a bare "Android 14" label would boot a car dashboard for
# someone who asked for a phone, so form factor is classified separately from
# the tag and the UI defaults to phone.
FORM_FACTORS = [
    {"id": "phone", "name": "Phone"},
    {"id": "tablet", "name": "Tablet"},
    {"id": "tv", "name": "Android TV"},
    {"id": "wear", "name": "Wear OS"},
    {"id": "automotive", "name": "Automotive"},
    {"id": "xr", "name": "Google XR"},
    {"id": "desktop", "name": "Android Desktop"},
    {"id": "other", "name": "Other"},
]


def classify_form_factor(package_path: str, tags: list[str]) -> str:
    """Derive form factor from the package path's variant segment.

    Matched most-specific-first: an automotive *distant display* image is still
    automotive, and an XR preview playstore image is still XR.
    """
    parts = package_path.split(";")
    variant = (parts[2] if len(parts) >= 3 else "").lower()
    text = f"{variant} {' '.join(tags)}".lower()
    # Split on both separators so "android-xr-preview" and "google_apis_tablet"
    # both tokenise cleanly. Short tokens like "tv" and "xr" must match whole
    # tokens, or "tv" would fire on unrelated substrings.
    tokens = set(text.replace("_", "-").replace(" ", "-").split("-"))

    for needle, factor in (("automotive", "automotive"), ("wear", "wear"),
                           ("desktop", "desktop"), ("tablet", "tablet")):
        if needle in text:
            return factor
    if "xr" in tokens:
        return "xr"
    if "tv" in tokens or "googletv" in tokens:
        return "tv"
    if variant.startswith(("google_apis", "android", "aosp", "default")):
        return "phone"
    return "other"


@dataclass
class CatalogEntry:
    package_path: str
    label: str                  # "Android 16"
    api_level: str              # raw, e.g. "36" or "37.1"
    api_major: int | None
    codename: str | None
    channel: str
    revision: str
    abi: str
    size_bytes: int
    download_mb: int
    tags: list[str]
    page_size_16kb: bool
    is_preview: bool
    label_guessed: bool
    min_emulator_revision: str | None
    installed: bool
    installed_revision: str | None
    upgradable: bool
    display_name: str
    form_factor: str = "phone"
    preferred: bool = False
    extension_level: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "packagePath": self.package_path,
            "formFactor": self.form_factor,
            "preferred": self.preferred,
            "label": self.label,
            "apiLevel": self.api_level,
            "apiMajor": self.api_major,
            "codename": self.codename,
            "channel": self.channel,
            "revision": self.revision,
            "abi": self.abi,
            "sizeBytes": self.size_bytes,
            "downloadMb": self.download_mb,
            "tags": self.tags,
            "pageSize16kb": self.page_size_16kb,
            "isPreview": self.is_preview,
            "labelGuessed": self.label_guessed,
            "minEmulatorRevision": self.min_emulator_revision,
            "installed": self.installed,
            "installedRevision": self.installed_revision,
            "upgradable": self.upgradable,
            "displayName": self.display_name,
            "extensionLevel": self.extension_level,
        }


@dataclass
class Catalog:
    entries: list[CatalogEntry] = field(default_factory=list)
    latest_stable: str | None = None
    host_abi: str = ""
    warnings: list[str] = field(default_factory=list)
    form_factors: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "latestStable": self.latest_stable,
            "hostAbi": self.host_abi,
            "warnings": self.warnings,
            "formFactors": self.form_factors,
            "support": versions.support_summary(),
        }


def _best_per_path(packages: list[manifest.Package]) -> list[manifest.Package]:
    """The same path appears once per channel; keep the highest revision of each.

    Verified in live manifests: `emulator` x2 (stable + dev), `ndk-bundle` x25.
    Assuming path uniqueness silently installs a dev build.
    """
    best: dict[tuple[str, str], manifest.Package] = {}
    for p in packages:
        key = (p.path, p.channel)
        current = best.get(key)
        if current is None or p.revision > current.revision:
            best[key] = p
    return list(best.values())


async def build_catalog(
    client: httpx.AsyncClient,
    *,
    include_previews: bool = False,
    playstore_only: bool = True,
    include_extensions: bool = False,
    form_factor: str | None = "phone",
) -> Catalog:
    images = await discovery.load_system_images(client)
    tools = await discovery.load_tools(client)

    emulator_pkgs = [p for p in tools if p.path == "emulator"]
    emulator_pkgs = _best_per_path(emulator_pkgs)

    catalog = Catalog(host_abi=settings.host_abi())
    if not images:
        catalog.warnings.append(
            "Could not reach Google's SDK repository. Check your connection — the "
            "catalog is read live so new Android versions appear automatically."
        )
        return catalog

    want_abi = settings.host_abi()
    entries: list[CatalogEntry] = []

    for pkg in _best_per_path(images):
        if pkg.abi != want_abi:
            continue
        if playstore_only and not (PLAYSTORE_TAGS & set(pkg.tags)):
            continue
        if not include_extensions and not pkg.base_extension:
            # Extension-level images are a developer concern and would only
            # confuse someone choosing "Android 12".
            continue
        if not include_previews and pkg.is_preview:
            continue

        archive = pkg.archive_for_host()
        if archive is None:
            continue

        api = versions.parse_api_level(pkg.api_level_raw)
        if not include_extensions and api.is_extension:
            continue

        factor = classify_form_factor(pkg.path, pkg.tags)
        marker = installed.info(pkg.path)
        installed_rev = marker.get("revision") if marker else None

        entries.append(
            CatalogEntry(
                form_factor=factor,
                package_path=pkg.path,
                label=versions.android_version(api),
                api_level=api.raw,
                api_major=api.major,
                codename=pkg.codename or versions.codename(api),
                channel=pkg.channel,
                revision=pkg.revision_str,
                abi=pkg.abi or want_abi,
                size_bytes=archive.size,
                download_mb=round(archive.size / (1024 * 1024)),
                tags=pkg.tags,
                page_size_16kb=PAGE_SIZE_16KB_TAG in pkg.tags,
                is_preview=pkg.is_preview,
                label_guessed=versions.is_label_guessed(api),
                min_emulator_revision=(
                    ".".join(str(x) for x in pkg.dependencies["emulator"])
                    if "emulator" in pkg.dependencies
                    else None
                ),
                installed=marker is not None,
                installed_revision=installed_rev,
                upgradable=bool(installed_rev and installed_rev != pkg.revision_str),
                display_name=pkg.display_name,
                extension_level=pkg.extension_level,
            )
        )

    # Newest first, with 16 KB variants preferred at the same API level.
    def sort_key(e: CatalogEntry) -> tuple:
        api = versions.parse_api_level(e.api_level)
        return (
            -(api.sort_key[0]),
            -(api.sort_key[1]),
            CHANNEL_RANK.get(e.channel, 9),
            0 if e.page_size_16kb else 1,
        )

    entries.sort(key=sort_key)

    # One recommended row per Android version, so a non-developer sees
    # "Android 16" once rather than a 4 KB and a 16 KB variant side by side.
    # 16 KB page size wins where it exists — it matches how modern physical
    # devices are configured. Computed per form factor, before filtering.
    seen: set[tuple[str, str, str]] = set()
    for e in entries:
        key = (e.form_factor, e.api_level, e.channel)
        if key not in seen:
            seen.add(key)
            e.preferred = True

    # Counts cover every form factor so the UI can offer the filter, even though
    # only the selected one is returned.
    catalog.form_factors = [
        {**f, "count": sum(1 for e in entries if e.form_factor == f["id"])}
        for f in FORM_FACTORS
    ]
    catalog.form_factors = [f for f in catalog.form_factors if f["count"]]

    if form_factor:
        entries = [e for e in entries if e.form_factor == form_factor]
    catalog.entries = entries

    # "Latest" needs no version table at all: an empty codename means publicly
    # released, so the highest such api-level is the newest stable Android.
    stable = [e for e in entries if not e.is_preview and e.preferred]
    if stable:
        catalog.latest_stable = stable[0].package_path

    if not emulator_pkgs:
        catalog.warnings.append("Emulator package not found in the tools manifest.")

    return catalog


def pick_emulator(tools: list[manifest.Package], min_revision: tuple[int, ...] | None) -> manifest.Package | None:
    """Newest stable emulator meeting the image's declared minimum.

    Falls back to preview channels only if no stable build is new enough.
    """
    candidates = _best_per_path([p for p in tools if p.path == "emulator"])
    candidates = [p for p in candidates if p.archive_for_host() is not None]
    if not candidates:
        return None

    def ok(p: manifest.Package) -> bool:
        return min_revision is None or p.revision >= min_revision

    for channel in ("stable", "beta", "dev", "canary"):
        pool = [p for p in candidates if p.channel == channel and ok(p)]
        if pool:
            return max(pool, key=lambda p: p.revision)

    # Nothing satisfies the minimum; hand back the newest we have and let the
    # caller warn rather than silently installing an unusable pair.
    return max(candidates, key=lambda p: p.revision)


def find_package(packages: list[manifest.Package], path: str) -> manifest.Package | None:
    matches = [p for p in packages if p.path == path]
    if not matches:
        return None
    return max(matches, key=lambda p: p.revision)


def parse_revision(text: str | None) -> tuple[int, ...] | None:
    if not text:
        return None
    parts: list[int] = []
    for chunk in text.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            break
    return tuple(parts) or None
