"""Client for the Sund Cup API (see API.md)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import requests


class SundCupError(RuntimeError):
    pass


# The API returns i18n keys; the Danish labels live in the frontend bundle.
TYPE_LABELS = {
    "Elcykel": "Elcykel",
    "activity.walking": "Gåtur",
    "activity.running": "Løb",
    "activity.cycling": "Cykling",
    "activity.swimming": "Svømning",
    "activity.rowing": "Roning",
    "activity.strength": "Styrketræning",
    "activity.yoga": "Yoga",
    "activity.teamSport": "Holdsport",
    "activity.other": "Andet",
}


@dataclass
class ActivityType:
    id: str
    key: str
    label: str
    unit: str
    base_points: float
    category: str
    icon: str

    @classmethod
    def from_json(cls, d: dict) -> "ActivityType":
        key = d.get("translationKey") or d.get("name") or ""
        return cls(
            id=d["id"],
            key=key,
            label=TYPE_LABELS.get(key, key.split(".")[-1]),
            unit=d.get("unitOfMeasurement", ""),
            base_points=float(d.get("basePointValue") or 0),
            category=d.get("category", ""),
            icon=d.get("icon", ""),
        )


@dataclass
class Competition:
    id: str
    name: str
    status: str
    start_date: date
    end_date: date
    entry_window_days: int
    outdoor_multiplier: float

    @classmethod
    def from_json(cls, d: dict) -> "Competition":
        return cls(
            id=d["id"],
            name=d["name"],
            status=d["status"],
            start_date=datetime.fromisoformat(d["startDate"].replace("Z", "+00:00")).date(),
            end_date=datetime.fromisoformat(d["endDate"].replace("Z", "+00:00")).date(),
            entry_window_days=d.get("activityEntryWindowDays", 4),
            outdoor_multiplier=float(d.get("outdoorMultiplier", 1)),
        )


class SundCup:
    def __init__(self, base_url: str, ca_bundle: str | None = None):
        self.base = base_url.rstrip("/")
        self.s = requests.Session()
        if ca_bundle and Path(ca_bundle).exists():
            self.s.verify = ca_bundle
        self.s.headers["User-Agent"] = "garmin-to-sundcup/1.0"

    # --- plumbing ---------------------------------------------------------
    def _url(self, path: str) -> str:
        return f"{self.base}{path}"

    def _check(self, r: requests.Response) -> requests.Response:
        if r.status_code >= 400:
            body = r.text.strip()[:400]
            raise SundCupError(f"{r.request.method} {r.request.url} -> {r.status_code}: {body}")
        return r

    # --- api --------------------------------------------------------------
    def login(self, username: str, password: str) -> dict:
        self._check(
            self.s.post(
                self._url("/api/auth/login"),
                json={"Username": username, "Password": password},
                timeout=30,
            )
        )
        return self.me()

    def me(self) -> dict:
        return self._check(self.s.get(self._url("/api/users/me"), timeout=30)).json()

    def competitions(self) -> list[Competition]:
        data = self._check(self.s.get(self._url("/api/competitions"), timeout=30)).json()
        return [Competition.from_json(c) for c in data]

    def current_competition(self) -> Competition:
        comps = self.competitions()
        if not comps:
            raise SundCupError("No competitions available")
        for c in comps:
            if c.status == "Active":
                return c
        return comps[0]

    def activity_types(self, competition_id: str) -> list[ActivityType]:
        data = self._check(
            self.s.get(
                self._url(f"/api/competitions/{competition_id}/activity-types"),
                timeout=30,
            )
        ).json()
        return [ActivityType.from_json(t) for t in data]

    def activities(self, competition_id: str) -> list[dict]:
        return self._check(
            self.s.get(
                self._url("/api/activities"),
                params={"competitionId": competition_id},
                timeout=30,
            )
        ).json()

    def log_activity(
        self,
        competition_id: str,
        activity_type_id: str,
        when: datetime,
        duration_minutes: int,
        distance_km: float | None = None,
        note: str = "",
        visibility: str = "TeamOnly",
        is_outdoor: bool = True,
        tagged_member_ids: list[str] | None = None,
        image: Path | None = None,
    ) -> dict:
        fields: list[tuple[str, tuple[None, str] | tuple[str, bytes, str]]] = [
            ("competitionId", (None, competition_id)),
            ("activityTypeId", (None, activity_type_id)),
            ("activityDateTime", (None, when.strftime("%Y-%m-%dT%H:%M"))),
            ("durationMinutes", (None, str(int(duration_minutes)))),
            ("visibility", (None, visibility)),
            ("isOutdoor", (None, "true" if is_outdoor else "false")),
        ]
        if distance_km is not None:
            fields.append(("distanceKm", (None, f"{distance_km:.2f}")))
        if note:
            fields.append(("note", (None, note)))
        for mid in tagged_member_ids or []:
            fields.append(("taggedMemberIds", (None, mid)))
        if image:
            fields.append(("image", (image.name, image.read_bytes(), "image/jpeg")))

        r = self._check(self.s.post(self._url("/api/activities"), files=fields, timeout=60))
        return r.json() if r.content else {}

    def delete_activity(self, activity_id: str) -> None:
        self._check(self.s.delete(self._url(f"/api/activities/{activity_id}"), timeout=30))

    def get_steps(self, day: date, competition_id: str) -> dict:
        r = self._check(
            self.s.get(
                self._url(f"/api/steps/{day.isoformat()}"),
                params={"competitionId": competition_id},
                timeout=30,
            )
        )
        if not r.content:
            return {}  # no entry logged for that day yet
        try:
            return r.json()
        except ValueError:
            return {}

    def put_steps(self, day: date, competition_id: str, step_count: int) -> dict:
        r = self._check(
            self.s.put(
                self._url(f"/api/steps/{day.isoformat()}"),
                params={"competitionId": competition_id},
                json={"competitionId": competition_id, "stepCount": int(step_count)},
                timeout=30,
            )
        )
        return r.json() if r.content else {}
