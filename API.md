# Sund Cup API (reverse-engineered from https://sundcup.nc3.politi.dk)

Stack: Vite SPA + ASP.NET Core REST API under `/api`. Auth = HttpOnly session cookie
(the `teampulse-auth` localStorage entry is UI state, not the credential).

## Auth
```
POST /api/auth/login
Content-Type: application/json
{"Username": "...", "Password": "..."}
```
Sets session cookie. Reuse the cookie jar for all later calls.

## Context
```
GET /api/users/me
GET /api/competitions
GET /api/competitions/{competitionId}/activity-types
```
Current competition: `92a6e9e9-97e9-4d8a-ae25-d144c1de0367` — "NSK Sund Cup Afd. 5",
status `Registration`, start 2026-09-07, end 2026-10-04,
`activityEntryWindowDays: 4`, `outdoorMultiplier: 1.10`.
Writes only work while status is `Active` (empty/wrong competition -> 400 "Competition not found.").

## Log activity
```
POST /api/activities        (multipart/form-data)
```
Fields: `competitionId`, `activityTypeId`, `activityDateTime`, `durationMinutes`,
`distanceKm`, `note`, `visibility` (`TeamOnly` | `Public`), `isOutdoor` (`true`/`false`),
`image` (optional file), `taggedMemberIds` (repeatable).

`GET /api/activities?competitionId=...` lists own activities;
`/api/activities/{id}` allows GET, PUT, DELETE.

Server-side rejections (400, `messageKey` + Danish-ready payload):
`errors.activityOutsideCompetition` (date outside start/end) and
`errors.activityOutsideWindow` (date not within the last 4 days — so no future dates).

### Activity types
`GET /api/competitions/{id}/activity-types` returns
`{id, translationKey, icon, category, basePointValue, unitOfMeasurement}` —
no `name` field; labels are i18n keys resolved in the frontend bundle
(`/api/translations/da` only holds a couple of overrides).
Points: Gåtur 3.35/km, Løb 2/km, Cykling 1/km, Svømning 8/km, Roning 1.9/km,
Elcykel 0.5/km, Styrketræning 0.35/min, Yoga 0.35/min, Holdsport 0.4/min, Andet 0.35/min.


| Type | id |
| --- | --- |
| Elcykel | d395ccec-6c13-4bf7-baef-a6f761a919c3 |
| Gåtur | 6bb28626-cb86-44ba-8723-5b8f13e80262 |
| Løb | 9494a9d3-e8f0-481a-b95c-f79ce0eaaf2a |
| Cykling | 5cac3589-f628-4f06-8d37-6a3b6ddc3bdc |
| Svømning | 4ba4ac7b-9ab8-4e8d-848a-9585c359b48a |
| Roning | 3f3f2832-d10a-4eb7-abe0-e87308611f77 |
| Styrketræning | 611c6a90-2378-4429-964a-da924fa3b0ef |
| Yoga | cad993b3-2fc9-4e07-8e89-23cbd475bfb9 |
| Holdsport | 4318011a-a678-425c-84a6-9e0852977385 |
| Andet | 767769c6-b0de-4a45-91dc-57f8a33e6d4d |

## Log steps
```
GET /api/steps/{yyyy-MM-dd}?competitionId=...
PUT /api/steps/{yyyy-MM-dd}?competitionId=...   (JSON)
{"competitionId": "...", "stepCount": 8500}
```
UI allows the last 4 days (`activityEntryWindowDays`).

## Garmin side (planned)
`garminconnect` (garth) Python lib: last activity via `get_activities(0, 1)`
(type, start time, duration, distance), steps via `get_steps_data(date)` /
`get_stats(date)`. Map Garmin activityType -> activity type id above.
