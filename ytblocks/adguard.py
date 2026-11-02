"""Ad omission, enforced at three points of the pipeline (not as a late filter):

1. DISCOVERY  - ``strip_ads`` removes promoted/ad renderers from every YouTube
   JSON payload *before* it is parsed into result rows.
2. RESOLUTION - ``clean_formats`` / ``assert_info_ok`` only let progressive HTTPS
   ``*.googlevideo.com`` media formats through.  Manifest-based protocols
   (HLS/DASH) and live streams are refused: they are the carriers of
   server-side-inserted ad segments.  We never load the YouTube web player or
   embeds, which is where pre/mid-roll ads are injected.
3. PLAYBACK   - ``assert_clean`` is re-checked on every URL right before it is
   handed to libmpv, which itself runs with ``ytdl=no`` and ``load-scripts=no``.

This module must stay free of Qt imports.
"""
from __future__ import annotations

from urllib.parse import urlparse

AD_KEYS = frozenset({
    "adSlotRenderer", "promotedSponsorRenderer", "searchPyvRenderer",
    "promotedVideoRenderer", "compactPromotedVideoRenderer", "displayAdRenderer",
    "inFeedAdLayoutRenderer", "adBreakServiceRenderer", "playerAds",
    "adPlacements", "adSlots", "adBreakHeartbeatParams",
    "instreamAdPlayerOverlayRenderer",
})
AD_LABELS = frozenset({"ad", "ads", "sponsored", "promoted"})
BLOCKED_HOSTS = ("doubleclick.net", "googlesyndication.com", "googleadservices.com",
                 "adservice.google.", "imasdk.googleapis.com", "2mdn.net", "pagead2.")
BLOCKED_PARTS = ("/pagead/", "/api/stats/ads", "/ptracking", "adformat=",
                 "ad_type=", "&oad=")
MEDIA_SUFFIX = ".googlevideo.com"


class AdBlocked(Exception):
    """Raised when something that could carry advertising is refused."""


def media_url_ok(url: str) -> bool:
    try:
        u = urlparse(url)
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not host.endswith(MEDIA_SUFFIX):
        return False
    low = url.lower()
    return not (any(h in host for h in BLOCKED_HOSTS) or any(p in low for p in BLOCKED_PARTS))


def assert_clean(url: str) -> None:
    if not media_url_ok(url):
        raise AdBlocked(f"refused non-media / ad-serving URL: {url[:80]}")


def _ad_badge(d: dict) -> bool:
    for v in d.values():
        if not isinstance(v, dict):
            continue
        if v.get("isAd") is True:
            return True
        for key in ("badges", "ownerBadges"):
            badges = v.get(key)
            if not isinstance(badges, list):
                continue
            for b in badges:
                r = b.get("metadataBadgeRenderer") if isinstance(b, dict) else None
                if r and str(r.get("label", "")).strip().lower() in AD_LABELS:
                    return True
    return False


def is_ad_element(el) -> bool:
    return isinstance(el, dict) and (bool(AD_KEYS & el.keys()) or _ad_badge(el))


def strip_ads(node):
    """Return a copy of a YouTube JSON payload with all ad/promoted items removed."""
    if isinstance(node, dict):
        return {k: strip_ads(v) for k, v in node.items() if k not in AD_KEYS}
    if isinstance(node, list):
        return [strip_ads(x) for x in node if not is_ad_element(x)]
    return node


def assert_info_ok(info: dict) -> None:
    status = info.get("live_status")
    if info.get("is_live") or status in ("is_live", "is_upcoming", "post_live"):
        raise AdBlocked("live/upcoming streams use server-side ad insertion; refused")


def clean_formats(formats: list[dict]) -> list[dict]:
    """Keep only direct progressive-HTTPS googlevideo formats."""
    return [f for f in formats
            if f.get("protocol") == "https" and f.get("url") and media_url_ok(f["url"])]
