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
default visibility, note template).
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
ExecStart=/home/smd/Documents/garmin_to_sundcup/g2s --since-days 2 --step-days 2
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
