# garmin_to_sundcup

Pushes your latest Garmin Connect activity **and** your daily step count to
NSK Sund Cup (`https://sundcup.nc3.politi.dk`). API details in `API.md`.

## Setup (one time)

```bash
./g2s set-password garmin     # your Garmin Connect password
./g2s set-password sundcup    # your Sund Cup password
```

Passwords go into the system keyring (gnome-keyring/SecretService) — never to disk.
Garmin session tokens are cached in `~/.config/garmin_to_sundcup/garth`, so the
password (and any MFA code) is normally only needed once.

Config: `~/.config/garmin_to_sundcup/config.toml` (email, Sund Cup username,
default visibility, note template, `pick`, `stale_after_minutes`).
The site serves an incomplete cert chain, so `certs/sundcup-ca-bundle.pem`
(certifi + the DigiCert EU intermediate) is used for TLS verification.

## Use

```bash
./g2s status                  # accounts, competition, latest Garmin activity, today's steps
./g2s --dry-run               # show what would be logged, write nothing
./g2s                         # log latest activity + today's steps
./g2s --steps-only --step-days 4
./g2s --since-days 4          # log every Garmin activity from the last 4 days
./g2s --type Roning --indoor  # override mapping for this run
```

Flags: `--force` (re-log despite dedupe), `--visibility Public|TeamOnly`,
`--note "..."`, `--tag <memberId>`, `--activity-only`,
`--ignore-window` (skip the local period/status guards and let the server decide).

Already-logged Garmin activity ids are remembered in
`~/.local/state/garmin_to_sundcup/synced.json`; steps are upserted, so
re-running is safe.

### Picking activities

Run interactively and you get a checkbox list before anything is uploaded:

```
Vaelg aktiviteter (mellemrum = til/fra, a = alle, n = ingen, enter = ok, q = fortryd):
>[ ] 2026-09-09 06:38  Løb        31 min   5.40 km  ude   Morning run [running]   tidligere fravalgt
 [x] 2026-09-09 07:12  Cykling    22 min   8.10 km  ude   Ride to work [cycling]
```

Arrow keys (or `j`/`k`) move, space toggles, enter uploads the ticked ones.
Whatever you untick is remembered in the `skipped` section of the state file:
that activity stays unticked next time and is never uploaded, while anything
new — tomorrow's swim — turns up ticked by default, ready for you to untick if
you want. Re-ticking an activity forgets the deselection.

Deselections are also honoured non-interactively, so the systemd timer below
will not upload a run you said no to. Options: `--no-pick` (upload everything
not previously deselected), `--pick` (force the list on), `pick = false` in
`config.toml` (turn the default off), `--forget-skips` (clear the memory).
A dry run never writes to the state file.

### Stale Garmin data

Garmin's cloud only holds what your watch has uploaded. If the newest step
sample is more than `stale_after_minutes` old (default 120), you get a warning
on stderr before the steps are logged, because the count is probably too low:

```
WARNING: Garmin's newest data is from 18:01 (3h25m ago) - sync your watch, today's step count is probably too low
```

`./g2s status` also prints the time of the newest sample.

## Notes

- The competition must be `Active`. "NSK Sund Cup Afd. 5" starts **2026-09-07**;
  until then the API rejects writes with `400 Competition not found.` and the
  tool stops with that message (`--dry-run` still works).
- Only the last 4 days can be logged (`activityEntryWindowDays`).
- Indoor/outdoor is derived from the Garmin type key plus whether the activity
  has GPS coordinates; outdoor gets the ×1.10 bonus. Override with
  `--indoor`/`--outdoor`.
- Type mapping lives in `TYPE_MAP` in `garmin_to_sundcup/garmin.py`. The API returns
  i18n keys (`activity.running`), mapped to Danish labels by `TYPE_LABELS` in `sundcup.py`.
  Distance is only sent for types measured in km; the minutes-based ones
  (Styrketræning, Yoga, Holdsport, Andet) get duration only.

## Optional: run it daily

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/g2s.service <<'EOF'
[Unit]
Description=Sync Garmin to Sund Cup
[Service]
Type=oneshot
ExecStart=/home/smd/Documents/garmin_to_sundcup/g2s --since-days 2 --step-days 2 --no-pick
EOF
cat > ~/.config/systemd/user/g2s.timer <<'EOF'
[Unit]
Description=Sync Garmin to Sund Cup twice daily
[Timer]
OnCalendar=*-*-* 12,21:30
Persistent=true
[Install]
WantedBy=timers.target
EOF
systemctl --user enable --now g2s.timer
```
