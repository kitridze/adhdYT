"""Filter + sort model (Qt-free so it can be unit-tested)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

SORTS = (
    ("relevance", "Relevance"),
    ("date", "Date (newest)"),
    ("popularity", "Popularity (views)"),
    ("rating", "Rating"),
    ("length_desc", "Length (longest)"),
    ("length_asc", "Length (shortest)"),
)


@dataclass
class Filters:
    sort: str = "relevance"
    min_len: int = 0          # minutes, 0 = off
    max_len: int = 0          # minutes, 0 = off
    min_views: int = 0        # 0 = off
    types: dict = field(default_factory=lambda: {
        "video": True, "channel": True, "playlist": True, "short": False})
    seen: str = "both"        # both | seen | unseen

    @classmethod
    def from_dict(cls, d: dict) -> "Filters":
        f = cls()
        for k in ("sort", "min_len", "max_len", "min_views", "seen"):
            if k in d:
                setattr(f, k, d[k])
        f.types.update({k: bool(v) for k, v in (d.get("types") or {}).items() if k in f.types})
        return f

    def to_dict(self) -> dict:
        return asdict(self)

    # --- what YouTube can do for us server-side (ytfzf's `sp=` mechanism) ---
    def server_sort(self) -> str:
        return self.sort if self.sort in ("date", "popularity", "rating") else "relevance"

    def server_type(self):
        if self.types.get("short"):
            return None
        on = [k for k in ("video", "channel", "playlist") if self.types.get(k)]
        return on[0] if len(on) == 1 else None

    def server_sig(self):
        return (self.server_sort(), self.server_type())

    def client_sorts(self, feed_is_search: bool) -> bool:
        return self.sort.startswith("length") or (self.sort == "popularity" and not feed_is_search)

    # --- predicate ---
    def accept(self, it, seen_ids) -> bool:
        if not self.types.get(it.kind, False):
            return False
        if it.kind in ("video", "short"):
            lo, hi = self.min_len * 60, self.max_len * 60
            if lo or hi:
                if it.duration is None:
                    return False          # cannot verify the bound
                if (lo and it.duration < lo) or (hi and it.duration > hi):
                    return False
            if self.min_views and (it.views is None or it.views < self.min_views):
                return False
            s = it.id in seen_ids
            if (self.seen == "seen" and not s) or (self.seen == "unseen" and s):
                return False
        return True

    def sort_items(self, items: list) -> list:
        if self.sort.startswith("length"):
            known = [i for i in items if i.duration is not None]
            rest = [i for i in items if i.duration is None]
            known.sort(key=lambda i: i.duration, reverse=self.sort == "length_desc")
            return known + rest
        if self.sort == "popularity":
            return sorted(items, key=lambda i: -(i.views or 0))
        return list(items)
