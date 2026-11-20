"""Names for the signed-in drill-down view.

Only an allowlisted Windows session can ask for names, only for the IDs it asks about, and names live only in this
process's memory for a short time: they are never written to a snapshot, a file, or the log.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Callable, Dict, Iterable, List, Mapping, Optional

ID_PATTERN = re.compile(r"[0-9A-Za-z_-]{1,32}")
MAX_IDS = 300
TTL_SECONDS = 600
STALE_SECONDS = 3600


class RosterUnavailable(RuntimeError):
    """The names lookup is not available right now."""


def clean_ids(values: Iterable[str]) -> List[str]:
    seen: Dict[str, None] = {}
    for value in values:
        text = str(value).strip()
        if text and text.lower() != "unassigned" and ID_PATTERN.fullmatch(text):
            seen.setdefault(text, None)
        if len(seen) >= MAX_IDS:
            break
    return list(seen)


def roster_from_rows(rows: Iterable[Mapping[str, object]]) -> Dict[str, str]:
    people: Dict[str, str] = {}
    for row in rows:
        person_id = str(row.get("person_id") or "").strip()
        name = " ".join(str(row.get("display_name") or "").split())
        if person_id and name and person_id not in people:
            people[person_id] = name[:120]
    return people


class RosterService:
    def __init__(self, fetch: Callable[[], Dict[str, str]], clock: Callable[[], float] = time.time) -> None:
        self._fetch = fetch
        self._clock = clock
        self._lock = threading.Lock()
        self._people: Dict[str, str] = {}
        self._loaded_at: Optional[float] = None

    def _current(self) -> Dict[str, str]:
        now = self._clock()
        with self._lock:
            if self._loaded_at is not None and now - self._loaded_at < TTL_SECONDS:
                return self._people
            try:
                self._people = self._fetch()
                self._loaded_at = now
            except Exception as exc:  # noqa: BLE001 - bounded, user-presentable failure
                if self._loaded_at is not None and now - self._loaded_at < STALE_SECONDS:
                    return self._people
                raise RosterUnavailable("The names lookup is unavailable right now.") from exc
            return self._people

    def names_for(self, ids: Iterable[str]) -> Dict[str, str]:
        wanted = clean_ids(ids)
        people = self._current()
        return {person_id: people[person_id] for person_id in wanted if person_id in people}
