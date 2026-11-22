"""Uppdatera Cloudflare Tunnel och Fail2ban via Docker Compose."""

import os
from pathlib import Path
import subprocess

PROJECT_DIR = Path(__file__).resolve().parent


def update():
    subprocess.run(["git", "pull", "--ff-only"], cwd=PROJECT_DIR, check=True)

    environment = os.environ.copy()
    if not environment.get("FAIL2BAN_JOURNAL_DIR"):
        machine_id = Path("/etc/machine-id").read_text(encoding="ascii").strip()
        journal_times = {}
        for journal_dir in (Path("/var/log/journal"), Path("/run/log/journal")):
            try:
                journal_times[journal_dir] = (
                    journal_dir / machine_id / "system.journal"
                ).stat().st_mtime_ns
            except FileNotFoundError:
                continue

        if not journal_times:
            raise SystemExit(
                "Hittade ingen aktiv systemd-journal för värdservern. "
                "Ange FAIL2BAN_JOURNAL_DIR om journalen ligger på en annan sökväg."
            )
        environment["FAIL2BAN_JOURNAL_DIR"] = str(max(journal_times, key=journal_times.get))

    for arguments in (
        ("pull",),
        ("up", "--wait", "--wait-timeout", "60"),
        ("exec", "-T", "fail2ban", "fail2ban-client", "reload", "sshd"),
        ("exec", "-T", "fail2ban", "fail2ban-client", "status", "sshd"),
    ):
        subprocess.run(
            ["docker", "compose", *arguments],
            cwd=PROJECT_DIR,
            env=environment,
            check=True,
        )

    print("Cloudflare Tunnel och Fail2ban har uppdaterats.")


if __name__ == "__main__":
    update()
