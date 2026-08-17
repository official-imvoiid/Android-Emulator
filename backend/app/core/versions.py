"""API level to human Android version.

Google's repository manifests do NOT contain marketing version names — a system
image's display-name is "Google Play Intel x86_64 Atom System Image" and a platform
package is "Android SDK Platform 31". So the mapping has to live here.

Google's own tooling does exactly the same thing: sdklib's SdkVersionInfo.java is a
hardcoded switch beside a HIGHEST_KNOWN_API constant, and falls back to printing
"API %d" for anything newer. We follow that design, plus a forward rule that keeps
future releases labelled correctly with no code change.

TRAP: the SDK package "platforms;android-12" is API level 12 — Android 3.1
Honeycomb, from 2011. It is NOT Android 12 (which is API 31). Never build a package
path by concatenating a marketing version number. Always go through this table.
"""
from __future__ import annotations

from dataclasses import dataclass

# Verified against Google's <uses-sdk> API-level table.
# API levels are append-only: Google has never renumbered a released level, so
# every row below is frozen history. New releases are only ever appended.
_NAMES: dict[int, str] = {
    37: "17", 36: "16", 35: "15", 34: "14", 33: "13",
    32: "12L", 31: "12", 30: "11", 29: "10", 28: "9",
    27: "8.1", 26: "8.0", 25: "7.1", 24: "7.0", 23: "6.0",
    22: "5.1", 21: "5.0", 19: "4.4", 18: "4.3", 17: "4.2",
    16: "4.1", 15: "4.0.3", 14: "4.0",
}

_CODENAMES: dict[int, str] = {
    37: "Cinnamon Bun", 36: "Baklava", 35: "Vanilla Ice Cream",
    34: "Upside Down Cake", 33: "Tiramisu", 32: "Snow Cone v2",
    31: "Snow Cone", 30: "Red Velvet Cake", 29: "Quince Tart",
    28: "Pie", 27: "Oreo", 26: "Oreo", 25: "Nougat", 24: "Nougat",
    23: "Marshmallow", 22: "Lollipop", 21: "Lollipop", 19: "KitKat",
}

# Highest level we have a hand-written name for. Above this the forward rule runs.
HIGHEST_KNOWN_API = max(_NAMES)

# From API 33 onward the relationship is exactly `android = api - 20`
# (33->13, 34->14, 35->15, 36->16, 37->17). Below 33 it breaks (31 is Android 12,
# not 11), so the rule is only applied above the threshold.
_FORWARD_RULE_FLOOR = 33
_FORWARD_RULE_OFFSET = 20


@dataclass(frozen=True)
class ApiLevel:
    """A parsed api-level field.

    The raw value is NOT reliably an integer. Observed in live manifests:
      "36"     ordinary release
      "37.1"   minor SDK release (Google moved to fractional levels)
      "36x"    extension-level package
    So we keep the raw string and parse defensively.
    """
    raw: str
    major: int | None
    minor: int
    is_extension: bool

    @property
    def sort_key(self) -> tuple[int, int]:
        return (self.major if self.major is not None else -1, self.minor)


def parse_api_level(raw: str | None) -> ApiLevel:
    text = (raw or "").strip()
    is_ext = text.endswith("x")
    body = text[:-1] if is_ext else text

    major: int | None = None
    minor = 0
    if body:
        head, _, tail = body.partition(".")
        try:
            major = int(head)
        except ValueError:
            major = None
        if tail:
            try:
                minor = int(tail)
            except ValueError:
                minor = 0
    return ApiLevel(raw=text, major=major, minor=minor, is_extension=is_ext)


def android_version(api: ApiLevel) -> str:
    """The name a non-developer recognises, e.g. "Android 16"."""
    if api.major is None:
        return f"API {api.raw}" if api.raw else "Unknown"

    base = _NAMES.get(api.major)
    if base is None:
        if api.major >= _FORWARD_RULE_FLOOR:
            # Forward rule: an unreleased API 38 automatically reads "Android 18".
            base = str(api.major - _FORWARD_RULE_OFFSET)
        else:
            # Same graceful degradation Android Studio uses.
            return f"API {api.raw}"

    label = f"Android {base}"
    if api.minor:
        # Minor SDK releases (36.1, 37.1) are real, separate images.
        label += f" QPR{api.minor}"
    return label


def codename(api: ApiLevel) -> str | None:
    return _CODENAMES.get(api.major) if api.major is not None else None


def is_label_guessed(api: ApiLevel) -> bool:
    """True when the name came from the forward rule rather than the table.

    Surfaced in the UI so a guessed label is visibly provisional. Note the guess
    only affects the *label* — the download, checksum and boot all come from the
    manifest, so a wrong guess is cosmetic and never breaks anything.
    """
    return api.major is not None and api.major not in _NAMES


def support_summary() -> dict[str, object]:
    """What this build can label, for the UI's "supported versions" panel."""
    known = sorted(_NAMES)
    return {
        "highest_known_api": HIGHEST_KNOWN_API,
        "highest_known_android": f"Android {_NAMES[HIGHEST_KNOWN_API]}",
        "lowest_known_api": known[0],
        "named_api_levels": known,
        "forward_rule": f"API >= {_FORWARD_RULE_FLOOR} labels as Android (API - {_FORWARD_RULE_OFFSET})",
        "note": (
            "Version labels come from a local table plus a forward rule. Everything "
            "functional — the catalog, download URLs, checksums, emulator compatibility "
            "and boot — is read from Google's live manifests, so newly released Android "
            "versions appear here automatically without an update to this app."
        ),
    }
