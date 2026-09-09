"""CLI: push the latest Garmin activity (and daily steps) to Sund Cup."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta

from . import config, picker
from .garmin import GarminActivity, GarminClient
from .sundcup import ActivityType, Competition, SundCup, SundCupError

EMOJI = re.compile(r"[^\wÆØÅæøå ]+", re.UNICODE)


def warn(msg: str) -> None:
    print(f"WARNING: {msg}", file=sys.stderr)


def check_stale(gc: GarminClient, day: date, cfg: dict) -> None:
    """Warn if Garmin's cloud data for today lags behind the wall clock.

    Garmin only has what the watch has uploaded, so a stale watermark means we
    would log a step count the user can already see is too low on their watch.
    """
    if day != date.today():
        return
    limit = int(cfg["stale_after_minutes"])
    if limit <= 0:
        return
    try:
        last = gc.last_sample(day)
    except Exception:
        return
    if last is None:
        warn(f"Garmin has no step data yet for {day} - sync your watch")
        return
    lag = datetime.now() - last
    if lag > timedelta(minutes=limit):
        hours, minutes = divmod(int(lag.total_seconds()) // 60, 60)
        warn(
            f"Garmin's newest data is from {last:%H:%M} "
            f"({hours}h{minutes:02d}m ago) - sync your watch, "
            f"today's step count is probably too low"
        )


def _norm(name: str) -> str:
    return EMOJI.sub("", name).strip().casefold()


def resolve_type(types: list[ActivityType], wanted: str) -> ActivityType:
    want = _norm(wanted)
    for t in types:
        if want in {_norm(t.label), _norm(t.key), _norm(t.key.split(".")[-1])}:
            return t
    for t in types:
        if want and want in _norm(t.label):
            return t
    raise SundCupError(
        f"Unknown activity type {wanted!r}; available: {', '.join(t.label for t in types)}"
    )


def connect_sundcup(cfg: dict) -> tuple[SundCup, Competition]:
    sc = SundCup(cfg["sundcup_base_url"], cfg["ca_bundle"])
    user = cfg["sundcup_username"]
    sc.login(user, config.get_password("sundcup", user))
    return sc, sc.current_competition()


def describe(
    a: GarminActivity,
    atype: ActivityType | None = None,
    distance: float | None = None,
    outdoor: bool | None = None,
) -> str:
    label = atype.label if atype else a.sundcup_type
    dist = distance if atype else a.effective_distance_km()
    out = a.is_outdoor if outdoor is None else outdoor
    return (
        f"{a.start:%Y-%m-%d %H:%M}  {label:<14} "
        f"{a.duration_minutes:>4} min  "
        f"{(f'{dist:.2f} km' if dist else '--'):>9}  "
        f"{'ude' if out else 'inde':<4}  {a.name} [{a.type_key}]"
    )


def choose_activities(acts: list[GarminActivity], cfg: dict, args, state: dict) -> list[GarminActivity]:
    """Narrow `acts` down to the ones to upload, remembering the answers.

    An activity the user unticks is written to state["skipped"], so it stays
    unticked (and, when running non-interactively, stays skipped) forever after.
    Anything Garmin has not shown us before starts out ticked.
    """
    pending = []
    for a in acts:
        if not args.force and a.id in state["activities"]:
            print(f"skip (already logged): {describe(a)}")
        else:
            pending.append(a)
    if not pending:
        return []

    want_pick = args.pick if args.pick is not None else bool(cfg["pick"])
    if not (want_pick and sys.stdin.isatty() and sys.stdout.isatty()):
        keep = [a for a in pending if a.id not in state["skipped"]]
        for a in pending:
            if a.id in state["skipped"]:
                print(f"skip (remembered): {describe(a)}")
        return keep

    choices = [
        picker.Choice(
            label=describe(a),
            selected=a.id not in state["skipped"],
            hint="tidligere fravalgt" if a.id in state["skipped"] else "",
        )
        for a in pending
    ]
    result = picker.select(
        "Vaelg aktiviteter (mellemrum = til/fra, a = alle, n = ingen, enter = ok, q = fortryd):",
        choices,
    )
    if result is None:
        sys.exit("cancelled")

    keep = []
    for a, choice in zip(pending, result):
        if choice.selected:
            state["skipped"].pop(a.id, None)
            keep.append(a)
        else:
            state["skipped"][a.id] = {
                "start": a.start.isoformat(),
                "type": a.sundcup_type,
                "name": a.name,
            }
            print(f"skip (deselected): {describe(a)}")
    return keep


def push_activity(
    sc: SundCup,
    comp: Competition,
    a: GarminActivity,
    cfg: dict,
    args,
    state: dict,
) -> bool:
    oldest = date.today() - timedelta(days=comp.entry_window_days - 1)
    if not args.ignore_window:
        if a.start.date() < oldest:
            print(f"skip (outside {comp.entry_window_days}-day window): {describe(a)}")
            return False
        if not (comp.start_date <= a.start.date() <= comp.end_date):
            print(f"skip (outside competition period): {describe(a)}")
            return False

    atype = resolve_type(sc.activity_types(comp.id), args.type or a.sundcup_type)
    distance = a.distance_km if atype.unit == "km" else None
    outdoor = a.is_outdoor if args.outdoor is None else args.outdoor
    note = args.note if args.note is not None else cfg["note_template"].format(
        name=a.name, type=a.type_key
    )

    print(("DRY-RUN " if args.dry_run else "logging ")
          + describe(a, atype=atype, distance=distance, outdoor=outdoor))
    if args.dry_run:
        return False

    result = sc.log_activity(
        competition_id=comp.id,
        activity_type_id=atype.id,
        when=a.start,
        duration_minutes=a.duration_minutes,
        distance_km=distance,
        note=note,
        visibility=args.visibility or cfg["visibility"],
        is_outdoor=outdoor,
        tagged_member_ids=args.tag or None,
    )
    state["activities"][a.id] = {
        "loggedAt": datetime.now().isoformat(timespec="seconds"),
        "sundcupId": result.get("id"),
        "type": atype.label,
        "start": a.start.isoformat(),
    }
    points = result.get("points") or result.get("pointsAwarded")
    print(f"  -> ok{f' ({points} point)' if points else ''}")
    return True


def push_steps(gc: GarminClient, sc: SundCup, comp: Competition, day: date, args, cfg: dict,
               state: dict) -> bool:
    check_stale(gc, day, cfg)
    steps = gc.steps(day)
    if steps is None:
        print(f"{day}: no step data from Garmin")
        return False
    if not (comp.start_date <= day <= comp.end_date) and not args.ignore_window:
        print(f"{day}: {steps} skridt - outside competition period, skipped")
        return False

    current = None
    try:
        current = (sc.get_steps(day, comp.id) or {}).get("stepCount")
    except SundCupError:
        pass
    if current == steps and not args.force:
        print(f"{day}: {steps} skridt - already up to date")
        return False

    print(("DRY-RUN " if args.dry_run else "logging ") + f"{day}: {steps} skridt"
          + (f" (was {current})" if current is not None else ""))
    if args.dry_run:
        return False
    sc.put_steps(day, comp.id, steps)
    state["steps"][day.isoformat()] = steps
    print("  -> ok")
    return True


def cmd_status(cfg, args) -> None:
    gc = GarminClient(cfg["garmin_email"], lambda: config.get_password("garmin", cfg["garmin_email"]))
    sc, comp = connect_sundcup(cfg)
    me = sc.me()
    print(f"Sund Cup : {me['displayName']} (@{me['username']})")
    print(f"Konkurrence: {comp.name} [{comp.status}] {comp.start_date} - {comp.end_date}, "
          f"vindue {comp.entry_window_days} dage, ude x{comp.outdoor_multiplier}")
    last = gc.last_activity()
    print(f"Garmin   : {describe(last) if last else 'no activities'}")
    today = date.today()
    last_sample = gc.last_sample(today)
    print(f"Skridt   : {gc.steps(today)} i dag ({today})"
          + (f", nyeste data {last_sample:%H:%M}" if last_sample else ""))
    print("Typer    : " + ", ".join(
        f"{t.label} ({t.base_points}/{t.unit})" for t in sc.activity_types(comp.id)
    ))
    check_stale(gc, today, cfg)


def cmd_sync(cfg, args) -> None:
    gc = GarminClient(cfg["garmin_email"], lambda: config.get_password("garmin", cfg["garmin_email"]))
    sc, comp = connect_sundcup(cfg)
    state = config.load_state()
    changed = False

    if args.forget_skips:
        print(f"forgetting {len(state['skipped'])} remembered deselection(s)")
        state["skipped"] = {}
        changed = True

    if comp.status != "Active" and not (args.dry_run or args.ignore_window):
        sys.exit(f"Competition {comp.name!r} is {comp.status}, not Active - "
                 f"writes are rejected until {comp.start_date}. Use --dry-run to preview, "
                 f"or --ignore-window to send anyway and let the server decide.")

    if not args.steps_only:
        if args.since_days:
            since = date.today() - timedelta(days=args.since_days - 1)
            acts = sorted(gc.activities_since(since), key=lambda a: a.start)
        else:
            last = gc.last_activity()
            acts = [last] if last else []
        if not acts:
            print("No Garmin activities found")
        before = json.dumps(state["skipped"], sort_keys=True)
        acts = choose_activities(acts, cfg, args, state)
        changed |= json.dumps(state["skipped"], sort_keys=True) != before
        for a in acts:
            changed |= push_activity(sc, comp, a, cfg, args, state)

    if not args.activity_only:
        days = [date.today() - timedelta(days=i) for i in range(args.step_days)]
        for day in sorted(days):
            changed |= push_steps(gc, sc, comp, day, args, cfg, state)

    if changed and not args.dry_run:  # a dry run never touches the state file
        config.save_state(state)


def cmd_set_password(cfg, args) -> None:
    account = cfg["garmin_email"] if args.kind == "garmin" else cfg["sundcup_username"]
    config.set_password(args.kind, account)
    print(f"stored {args.kind} password for {account}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="garmin-to-sundcup", description=__doc__)
    sub = p.add_subparsers(dest="cmd")

    def add_common(sp):
        sp.add_argument("--dry-run", action="store_true", help="show what would be sent")
        sp.add_argument("--force", action="store_true", help="ignore dedupe state")
        sp.add_argument("--type", help="override Sund Cup activity type (e.g. Løb)")
        sp.add_argument("--note", help="override the note text")
        sp.add_argument("--visibility", choices=["TeamOnly", "Public"])
        sp.add_argument("--tag", action="append", metavar="MEMBER_ID", help="tag a teammate (repeatable)")
        sp.add_argument("--outdoor", dest="outdoor", action="store_true", default=None)
        sp.add_argument("--indoor", dest="outdoor", action="store_false")
        sp.add_argument("--since-days", type=int, metavar="N",
                        help="sync all Garmin activities from the last N days instead of just the latest")
        sp.add_argument("--step-days", type=int, default=1, metavar="N",
                        help="how many days of steps to sync (default 1 = today)")
        sp.add_argument("--pick", dest="pick", action="store_true", default=None,
                        help="tick which activities to upload (default when interactive)")
        sp.add_argument("--no-pick", dest="pick", action="store_false",
                        help="upload everything not previously deselected")
        sp.add_argument("--forget-skips", action="store_true",
                        help="clear the remembered deselections and start over")
        sp.add_argument("--activity-only", action="store_true")
        sp.add_argument("--steps-only", action="store_true")
        sp.add_argument("--ignore-window", action="store_true",
                        help="skip the local period/status guards and let the server decide")

    sync = sub.add_parser("sync", help="log latest activity + today's steps (default)")
    add_common(sync)
    status = sub.add_parser("status", help="show accounts, competition and latest Garmin data")
    add_common(status)
    sp = sub.add_parser("set-password", help="store a password in the system keyring")
    sp.add_argument("kind", choices=["garmin", "sundcup"])

    raw = list(argv if argv is not None else sys.argv[1:])
    if not raw or (raw[0] not in {"sync", "status", "set-password"} and raw[0] not in {"-h", "--help"}):
        raw = ["sync", *raw]  # sync is the default command

    args = p.parse_args(raw)
    cfg = config.load_config()

    if args.cmd == "status":
        cmd_status(cfg, args)
    elif args.cmd == "set-password":
        cmd_set_password(cfg, args)
    else:
        cmd_sync(cfg, args)


if __name__ == "__main__":
    main()
