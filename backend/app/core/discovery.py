"""Runtime discovery of Google's repository layout.

This is what makes the app survive Google renaming things. There are three tiers,
each probed by schema version from high to low so a newer schema is preferred the
day it appears:

  addons_list-N.xml       -> the list of every sub-repository (system image sites)
  repository2-N.xml       -> tools: emulator, platform-tools, cmdline-tools
  <site>/sys-img2-N.xml   -> system images for one form factor

Note addons_list currently points at `sys-img2-3.xml` while `-4` and `-5` already
exist, so the site *directory* is taken from addons_list but the schema version is
probed independently. New form factors (Google XR, Android Desktop) therefore show
up on their own with no code change.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from .. import settings
from ..events import bus
from . import manifest


@dataclass
class Site:
    display_name: str
    url: str          # absolute URL of the resolved manifest
    directory: str    # absolute URL of the directory holding it


_cache: dict[str, object] = {}
_lock = asyncio.Lock()


async def _highest_schema(client: httpx.AsyncClient, directory: str, stem: str, max_n: int) -> str | None:
    """Find the newest `<directory>/<stem>-N.xml`.

    All candidates are probed concurrently and the highest hit wins. Probing
    sequentially from max_n downwards costs one round-trip per miss, and since
    the live values sit well below max_n that added tens of seconds to the first
    catalog load. Resolved values are cached so later runs skip the probe.
    """
    cache_key = f"schema:{directory}{stem}"
    cached = _cache.get(cache_key)
    if cached:
        return cached  # type: ignore[return-value]

    candidates = [(n, urljoin(directory, f"{stem}-{n}.xml")) for n in range(max_n, 0, -1)]
    results = await asyncio.gather(
        *(manifest.url_exists(client, url) for _, url in candidates),
        return_exceptions=True,
    )
    for (_, url), found in zip(candidates, results):
        if found is True:
            _cache[cache_key] = url
            return url
    return None


async def discover_sites(client: httpx.AsyncClient) -> list[Site]:
    """Resolve every sub-repository, newest schema first."""
    cached = _cache.get("sites")
    if cached:
        return cached  # type: ignore[return-value]

    async with _lock:
        cached = _cache.get("sites")
        if cached:
            return cached  # type: ignore[return-value]

        addons_url = await _highest_schema(client, settings.REPO_BASE, "addons_list", settings.MAX_ADDONS_LIST)
        sites: list[Site] = []

        if addons_url:
            bus.log(f"Discovered site index: {addons_url.rsplit('/', 1)[-1]}")
            text = await manifest.fetch_text(client, addons_url)
            if text:
                sites = await _parse_sites(client, text, addons_url)

        if not sites:
            # Last-resort fallback so the app still works if addons_list moves.
            # These are recovered by probing, not trusted as final URLs.
            bus.log("Site index unavailable; falling back to known system-image sites", "warn")
            for slug, label in (
                ("google_apis_playstore", "Google API with Playstore System Images"),
                ("google_apis", "Google API add-on System Images"),
                ("android", "Android System Images"),
            ):
                directory = urljoin(settings.REPO_BASE, f"sys-img/{slug}/")
                resolved = await _highest_schema(client, directory, "sys-img2", settings.MAX_SYSIMG_SCHEMA)
                if resolved:
                    sites.append(Site(display_name=label, url=resolved, directory=directory))

        _cache["sites"] = sites
        return sites


async def _parse_sites(client: httpx.AsyncClient, xml_text: str, addons_url: str) -> list[Site]:
    """Read site entries, then re-probe each for its newest schema version."""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    raw: list[tuple[str, str]] = []
    for node in root.iter():
        if node.tag.rpartition("}")[2] != "site":
            continue
        name = url = None
        for child in node:
            tag = child.tag.rpartition("}")[2]
            if tag == "displayName":
                name = (child.text or "").strip()
            elif tag == "url":
                url = (child.text or "").strip()
        if url:
            raw.append((name or url, url))

    async def resolve(name: str, rel_url: str) -> Site | None:
        absolute = urljoin(addons_url, rel_url)
        directory = absolute.rsplit("/", 1)[0] + "/"
        filename = absolute.rsplit("/", 1)[-1]
        # Split "sys-img2-3.xml" into stem + version so we can probe for newer.
        m = re.match(r"^(?P<stem>.+?)-(?P<n>\d+)\.xml$", filename)
        if m:
            newest = await _highest_schema(client, directory, m.group("stem"), settings.MAX_SYSIMG_SCHEMA)
            if newest:
                return Site(display_name=name, url=newest, directory=directory)
        if await manifest.url_exists(client, absolute):
            return Site(display_name=name, url=absolute, directory=directory)
        return None

    resolved = await asyncio.gather(*(resolve(n, u) for n, u in raw))
    return [s for s in resolved if s]


async def tools_manifest_url(client: httpx.AsyncClient) -> str | None:
    """The repository2-N.xml holding emulator / platform-tools / cmdline-tools."""
    cached = _cache.get("tools_url")
    if cached:
        return cached  # type: ignore[return-value]
    url = await _highest_schema(client, settings.REPO_BASE, "repository2", settings.MAX_REPO_SCHEMA)
    if url:
        bus.log(f"Discovered tools manifest: {url.rsplit('/', 1)[-1]}")
        _cache["tools_url"] = url
    return url


async def load_tools(client: httpx.AsyncClient) -> list[manifest.Package]:
    url = await tools_manifest_url(client)
    if not url:
        return []
    text = await manifest.fetch_text(client, url)
    return manifest.parse_packages(text, url) if text else []


async def load_system_images(client: httpx.AsyncClient, site_filter: str | None = None) -> list[manifest.Package]:
    """Load system images from every discovered site (or one, by slug)."""
    sites = await discover_sites(client)
    if site_filter:
        sites = [s for s in sites if site_filter in s.url]

    async def one(site: Site) -> list[manifest.Package]:
        text = await manifest.fetch_text(client, site.url)
        return manifest.parse_packages(text, site.url) if text else []

    results = await asyncio.gather(*(one(s) for s in sites), return_exceptions=True)
    packages: list[manifest.Package] = []
    for r in results:
        if isinstance(r, list):
            packages.extend(r)
    return packages


def invalidate() -> None:
    _cache.clear()
