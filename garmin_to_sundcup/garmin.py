"""Garmin Connect side: last activity, daily steps, type mapping."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from garminconnect import Garmin

from .config import GARMIN_TOKENS

# Garmin typeKey (or a prefix of it) -> Sund Cup activity type name.
# Longest matching prefix wins, so "e_bike" beats "cycling"-ish generics.
TYPE_MAP: dict[str, str] = {
    "running": "Løb",
    "treadmill_running": "Løb",
    "indoor_running": "Løb",
    "trail_running": "Løb",
    "track_running": "Løb",
    "virtual_run": "Løb",
    "obstacle_run": "Løb",
    "walking": "Gåtur",
    "casual_walking": "Gåtur",
    "speed_walking": "Gåtur",
    "indoor_walking": "Gåtur",
    "hiking": "Gåtur",
    "cycling": "Cykling",
    "road_biking": "Cykling",
    "mountain_biking": "Cykling",
    "gravel_cycling": "Cykling",
    "cyclocross": "Cykling",
    "indoor_cycling": "Cykling",
    "virtual_ride": "Cykling",
    "track_cycling": "Cykling",
    "bmx": "Cykling",
    "e_bike_fitness": "Elcykel",
    "e_bike_mountain": "Elcykel",
    "ebiking": "Elcykel",
    "swimming": "Svømning",
    "lap_swimming": "Svømning",
    "open_water_swimming": "Svømning",
    "rowing": "Roning",
    "indoor_rowing": "Roning",
    "rowing_v2": "Roning",
    "kayaking": "Roning",
    "kayaking_v2": "Roning",
    "stand_up_paddleboarding": "Roning",
    "strength_training": "Styrketræning",
    "indoor_cardio": "Styrketræning",
    "hiit": "Styrketræning",
    "fitness_equipment": "Styrketræning",
    "elliptical": "Styrketræning",
    "stair_climbing": "Styrketræning",
    "bouldering": "Styrketræning",
    "indoor_climbing": "Styrketræning",
    "rock_climbing": "Styrketræning",
    "yoga": "Yoga",
    "pilates": "Yoga",
    "breathwork": "Yoga",
    "meditation": "Yoga",
    "soccer": "Holdsport",
    "football": "Holdsport",
    "american_football": "Holdsport",
    "basketball": "Holdsport",
    "handball": "Holdsport",
    "volleyball": "Holdsport",
    "floorball": "Holdsport",
    "hockey": "Holdsport",
    "ice_hockey": "Holdsport",
    "tennis": "Holdsport",
    "table_tennis": "Holdsport",
    "badminton": "Holdsport",
    "padel": "Holdsport",
    "pickleball": "Holdsport",
    "squash": "Holdsport",
    "racket_sports": "Holdsport",
    "cricket": "Holdsport",
    "rugby": "Holdsport",
    "ultimate_disc": "Holdsport",
}

INDOOR_HINTS = (
    "indoor",
    "treadmill",
    "virtual",
    "lap_swimming",
    "fitness_equipment",
    "elliptical",
    "stair",
    "strength",
    "yoga",
    "pilates",
    "hiit",
    "breathwork",
    "meditation",
    "table_tennis",
    "squash",
    "badminton",
)

# Sund Cup types where a distance makes no sense.
NO_DISTANCE = {"Styrketræning", "Yoga", "Holdsport"}


@dataclass
class GarminActivity:
    id: str
    name: str
    type_key: str
    start: datetime
    duration_minutes: int
    distance_km: float | None
    has_gps: bool
    raw: dict

    @property
    def sundcup_type(self) -> str:
        key = self.type_key or ""
        if key in TYPE_MAP:
            return TYPE_MAP[key]
        best = ""
        for candidate in TYPE_MAP:
            if (key.startswith(candidate) or candidate in key) and len(candidate) > len(best):
                best = candidate
        return TYPE_MAP.get(best, "Andet")

    @property
    def is_outdoor(self) -> bool:
        if any(h in (self.type_key or "") for h in INDOOR_HINTS):
            return False
        return self.has_gps

    def effective_distance_km(self) -> float | None:
        if self.sundcup_type in NO_DISTANCE:
            return None
        return self.distance_km


def _parse_start(a: dict) -> datetime:
    raw = a.get("startTimeLocal") or a.get("startTimeGMT")
    return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")


def to_activity(a: dict) -> GarminActivity:
    seconds = a.get("duration") or a.get("elapsedDuration") or 0
    meters = a.get("distance") or 0
    return GarminActivity(
        id=str(a.get("activityId")),
        name=a.get("activityName") or "Aktivitet",
        type_key=(a.get("activityType") or {}).get("typeKey", ""),
        start=_parse_start(a),
        duration_minutes=max(1, round(seconds / 60)),
        distance_km=round(meters / 1000, 2) if meters else None,
        has_gps=a.get("startLatitude") is not None,
        raw=a,
    )


class GarminClient:
    def __init__(self, email: str, password_cb):
        self.email = email
        self._password_cb = password_cb
        self.api: Garmin | None = None

    def connect(self) -> Garmin:
        if self.api:
            return self.api
        GARMIN_TOKENS.parent.mkdir(parents=True, exist_ok=True)
        api = Garmin(email=self.email, password=None, prompt_mfa=_prompt_mfa)
        try:
            api.login(str(GARMIN_TOKENS))
        except Exception:
            api = Garmin(
                email=self.email,
                password=self._password_cb(),
                prompt_mfa=_prompt_mfa,
            )
            api.login(str(GARMIN_TOKENS))
        self.api = api
        return api

    def last_activity(self) -> GarminActivity | None:
        activities = self.connect().get_activities(0, 1)
        return to_activity(activities[0]) if activities else None

    def activities_since(self, day: date, limit: int = 20) -> list[GarminActivity]:
        acts = [to_activity(a) for a in self.connect().get_activities(0, limit)]
        return [a for a in acts if a.start.date() >= day]

    def steps(self, day: date) -> int | None:
        stats = self.connect().get_stats(day.isoformat()) or {}
        total = stats.get("totalSteps")
        if total is None:
            for row in self.connect().get_daily_steps(day.isoformat(), day.isoformat()) or []:
                if row.get("calendarDate") == day.isoformat():
                    total = row.get("totalSteps")
        return int(total) if total is not None else None


def _prompt_mfa() -> str:
    return input("Garmin MFA code: ").strip()
