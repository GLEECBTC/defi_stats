#!/usr/bin/env python3
"""Check a GitHub branch once; restart a Compose service when its SHA changes."""

import argparse
import configparser
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import logging
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request


LOG = logging.getLogger("coins_monitoring")
SCRIPT = Path(__file__).resolve()
SHA = re.compile(r"[0-9a-f]{40}")


class MonitorError(Exception):
    """An actionable failure whose message is safe to log."""


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_config(path, require_token=True):
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with path.open(encoding="utf-8") as handle:
            parser.read_file(handle)
        cfg = {
            "repository": parser.get("github", "repository").strip(),
            "branch": parser.get("github", "branch").strip(),
            "github_token": parser.get("github", "token", fallback="").strip(),
            "project_dir": parser.get("docker", "project_dir").strip(),
            "executable": parser.get("docker", "executable", fallback="/usr/bin/docker").strip(),
            "service": parser.get("docker", "service").strip(),
            "restart_timeout": parser.getint("docker", "restart_timeout", fallback=180),
            "bot_username": parser.get("telegram", "bot_username").strip().lstrip("@"),
            "bot_token": parser.get("telegram", "bot_token").strip(),
            "chat_id": parser.get("telegram", "chat_id").strip(),
            "http_timeout": parser.getint("monitor", "http_timeout", fallback=30),
        }
    except (OSError, configparser.Error, ValueError):
        raise MonitorError("Cannot read configuration; check the INI file and required settings.") from None
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", cfg["repository"]):
        raise MonitorError("github.repository must use the owner/repository format.")
    if not cfg["branch"] or not re.fullmatch(r"[A-Za-z0-9_.-]+", cfg["service"]):
        raise MonitorError("The branch or Compose service name is invalid.")
    if not Path(cfg["project_dir"]).is_absolute() or not Path(cfg["executable"]).is_absolute():
        raise MonitorError("Docker project_dir and executable must be absolute paths.")
    if not re.fullmatch(r"-?\d+", cfg["chat_id"]):
        raise MonitorError("telegram.chat_id must be a numeric chat ID.")
    if not re.fullmatch(r"[A-Za-z0-9_]+", cfg["bot_username"]):
        raise MonitorError("telegram.bot_username is invalid.")
    if require_token and not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", cfg["bot_token"]):
        raise MonitorError("Set a valid telegram.bot_token in the INI file.")
    if not 1 <= cfg["http_timeout"] <= 120 or not 1 <= cfg["restart_timeout"] <= 900:
        raise MonitorError("HTTP timeout must be 1-120 seconds; restart timeout must be 1-900 seconds.")
    return cfg


def request_json(url, timeout, label, payload=None, headers=None, expected_type=dict):
    request_headers = {"User-Agent": "coins-monitoring/1.0", **(headers or {})}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        # Never print the URL: Telegram URLs contain the bot token.
        raise MonitorError(f"{label} returned HTTP {exc.code}.") from None
    except (OSError, urllib.error.URLError, ValueError):
        raise MonitorError(f"{label} failed: network, timeout, or invalid JSON response.") from None
    if not isinstance(result, expected_type):
        raise MonitorError(f"{label} returned an unexpected response.")
    return result


def github_headers(cfg, accept="application/vnd.github+json"):
    headers = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}
    if cfg["github_token"]:
        headers["Authorization"] = f'Bearer {cfg["github_token"]}'
    return headers


def get_head(cfg):
    branch = urllib.parse.quote(cfg["branch"], safe="")
    url = f'https://api.github.com/repos/{cfg["repository"]}/git/ref/heads/{branch}'
    data = request_json(url, cfg["http_timeout"], "GitHub", headers=github_headers(cfg))
    obj = data.get("object", {})
    if (data.get("ref") != f'refs/heads/{cfg["branch"]}'
            or not isinstance(obj, dict) or obj.get("type") != "commit"
            or not isinstance(obj.get("sha"), str) or not SHA.fullmatch(obj["sha"])):
        raise MonitorError("GitHub did not return the requested branch commit.")
    return obj["sha"]


def valid_coin(coin):
    return isinstance(coin, str) and bool(coin) and coin == coin.strip() and coin.isprintable()


def get_coins(cfg, sha):
    """Read full coin identifiers from the immutable commit, never from master."""
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise MonitorError("Cannot load coins without a valid commit SHA.")
    url = f'https://api.github.com/repos/{cfg["repository"]}/contents/coins?ref={sha}'
    data = request_json(
        url, cfg["http_timeout"], "GitHub coins file",
        headers=github_headers(cfg, "application/vnd.github.raw+json"), expected_type=list,
    )
    if not isinstance(data, list) or not all(
        isinstance(item, dict) and valid_coin(item.get("coin")) for item in data
    ):
        raise MonitorError("The coins file must be an array of objects with valid coin identifiers.")
    # Ordering, repeated entries, and metadata changes do not change coin membership.
    coins = sorted({item["coin"] for item in data})
    LOG.info("Loaded %d unique coin identifiers at commit %s.", len(coins), sha)
    return coins


def split_message(message):
    """Keep all text, prefer line boundaries, and reserve space for part labels."""
    limit = 3800
    parts, current, size = [], [], 0
    for line in message.splitlines(keepends=True):
        line_size = len(line.encode("utf-16-le")) // 2
        # Count UTF-16 units conservatively for Telegram, including non-BMP text.
        pieces = [line] if line_size <= limit else list(line)
        for piece in pieces:
            piece_size = len(piece.encode("utf-16-le")) // 2
            if size + piece_size > limit:
                parts.append("".join(current))
                current, size = [], 0
            current.append(piece)
            size += piece_size
    if current:
        parts.append("".join(current))
    if len(parts) <= 1:
        return parts
    return [f"Coins repository update (part {i}/{len(parts)})\n{part}"
            for i, part in enumerate(parts, start=1)]


def change_messages(cfg, state, old, head, status):
    previous = set(state["coins_by_commit"][old])
    current = set(state["coins_by_commit"][head])
    added, removed = sorted(current - previous), sorted(previous - current)
    lines = [
        "Coins repository changed", f'Repository: {cfg["repository"]}',
        f'Branch: {cfg["branch"]}', f"Previous SHA: {old}", f"New SHA: {head}",
        f"Host: {socket.gethostname()}", f'Service: {cfg["service"]}',
        f'Time (UTC): {state["updated_at"]}', f"Status: {status}",
        f"Coins in file: {len(previous)} -> {len(current)}", "",
        f"Added coins ({len(added)}):",
        *([f"+ {coin}" for coin in added] or ["None"]), "",
        f"Removed coins ({len(removed)}):",
        *([f"- {coin}" for coin in removed] or ["None"]), "",
        f'https://github.com/{cfg["repository"]}/compare/{old}...{head}',
    ]
    return split_message("\n".join(lines))


def send_telegram(cfg, message):
    base = f'https://api.telegram.org/bot{cfg["bot_token"]}'
    identity = request_json(base + "/getMe", cfg["http_timeout"], "Telegram getMe")
    bot = identity.get("result", {})
    if (identity.get("ok") is not True or not isinstance(bot, dict)
            or bot.get("username", "").lower() != cfg["bot_username"].lower()):
        raise MonitorError("Telegram token does not identify the configured bot username.")
    result = request_json(
        base + "/sendMessage", cfg["http_timeout"], "Telegram sendMessage",
        payload={"chat_id": cfg["chat_id"], "text": message,
                 "link_preview_options": {"is_disabled": True}},
    )
    if result.get("ok") is not True:
        raise MonitorError("Telegram rejected the notification.")
    LOG.info("Telegram notification sent by @%s to chat %s.", cfg["bot_username"], cfg["chat_id"])


def target_identity(cfg):
    return {key: cfg[key] for key in ("repository", "branch", "project_dir", "service")}


def read_state(path, cfg):
    if not path.exists():
        return {"version": 1, "target": target_identity(cfg), "last_sha": None,
                "pending": [], "coins_by_commit": {}}
    try:
        with path.open(encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError):
        raise MonitorError("Cannot read state file; refusing to replace an unreadable baseline.") from None
    if (not isinstance(state, dict) or state.get("version") != 1
            or state.get("target") != target_identity(cfg)
            or not isinstance(state.get("last_sha"), str)
            or not SHA.fullmatch(state["last_sha"])
            or not isinstance(state.get("pending"), list)
            or not all(isinstance(item, str) and len(item) <= 4096 for item in state["pending"])):
        raise MonitorError("State is invalid or belongs to another target; inspect it before proceeding.")
    # Backward-compatible extension: old installations only stored last_sha and pending.
    snapshots = state.setdefault("coins_by_commit", {})
    if not isinstance(snapshots, dict) or not all(
        SHA.fullmatch(sha) and isinstance(coins, list) and all(valid_coin(coin) for coin in coins)
        and coins == sorted(set(coins)) for sha, coins in snapshots.items()
    ):
        raise MonitorError("Coin snapshots in the state file are invalid; inspect them before proceeding.")
    return state


def save_state(path, state):
    # Same-directory rename keeps readers from observing a partially written file.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(state, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def single_instance(path):
    with path.open("a", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def restart_service(cfg):
    command = [cfg["executable"], "compose", "restart", cfg["service"]]
    LOG.info("Running docker compose restart %s in %s.", cfg["service"], cfg["project_dir"])
    try:
        result = subprocess.run(
            command, cwd=cfg["project_dir"], timeout=cfg["restart_timeout"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**os.environ, "LANG": "C", "LC_ALL": "C"}, check=False,
        )
    except subprocess.TimeoutExpired:
        raise MonitorError("Docker restart timed out; its final outcome is unknown. The next run will retry.") from None
    except OSError:
        raise MonitorError("Cannot execute Docker; check the executable, project directory, and permissions.") from None
    output = (result.stdout + "\n" + result.stderr).strip()
    # Bound output and redact configured credentials before logging subprocess diagnostics.
    for token in (cfg["bot_token"], cfg["github_token"]):
        if token:
            output = output.replace(token, "[REDACTED]")
    if output:
        LOG.info("Docker output: %s", output[-4000:])
    if result.returncode:
        raise MonitorError(f"Docker restart failed with exit code {result.returncode}; the next run will retry.")
    LOG.info("Docker restart command completed successfully.")


def deliver_pending(cfg, state, state_path):
    while state["pending"]:
        try:
            send_telegram(cfg, state["pending"][0])
        except MonitorError as exc:
            LOG.error("%s Notification remains queued for the next run.", exc)
            return False
        state["pending"].pop(0)
        save_state(state_path, state)
    return True


def run_check(cfg, state_path, dry_run=False):
    state = read_state(state_path, cfg)
    notifications_ok = True
    if not dry_run:
        notifications_ok = deliver_pending(cfg, state, state_path)
    head = get_head(cfg)
    old = state["last_sha"]
    LOG.info("Repository %s branch %s: %s.", cfg["repository"], cfg["branch"], head)
    snapshots = state["coins_by_commit"]
    snapshots_added = False
    for sha in (old, head):
        if sha is not None and sha not in snapshots:
            # Migration loads the old commit as well; never mistake a missing snapshot for [].
            snapshots[sha] = get_coins(cfg, sha)
            snapshots_added = True
    if old is not None:
        added = sorted(set(snapshots[head]) - set(snapshots[old]))
        removed = sorted(set(snapshots[old]) - set(snapshots[head]))
        LOG.info("Coin membership changes: %d added, %d removed.", len(added), len(removed))
    if dry_run:
        action = "initialize the baseline" if old is None else ("restart the service" if old != head else "take no action")
        LOG.info("Dry run: would %s. No state changes, restart, or Telegram messages.", action)
        if old is not None:
            LOG.info("Added coins: %s", ", ".join(added) or "None")
            LOG.info("Removed coins: %s", ", ".join(removed) or "None")
        return 0
    if old is None:
        state.update(last_sha=head, updated_at=utc_now())
        save_state(state_path, state)
        LOG.info("Baseline initialized. No restart or notification on the first run.")
        return 0
    if old == head:
        if snapshots_added:
            save_state(state_path, state)
        LOG.info("No branch changes; no restart required.")
        return 0 if notifications_ok else 1
    LOG.info("Branch changed: %s -> %s.", old, head)
    # Verify state persistence before invoking an external side effect.
    save_state(state_path, state)
    restart_ok = True
    try:
        restart_service(cfg)
        status = "Docker Compose restart completed successfully (application readiness not checked)."
        state["last_sha"] = head
    except MonitorError as exc:
        restart_ok = False
        status = str(exc)
        LOG.error("%s", status)
    state["updated_at"] = utc_now()
    state["pending"].extend(change_messages(cfg, state, old, head, status))
    # Persist restart success before notifying: Telegram failures must not repeat the restart.
    save_state(state_path, state)
    if notifications_ok:
        notifications_ok = deliver_pending(cfg, state, state_path)
    return 0 if restart_ok and notifications_ok else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Read GitHub and state without writing, restarting, or sending messages.")
    mode.add_argument("--test-telegram", action="store_true", help="Send a test message only; do not restart or change state.")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    os.umask(0o077)
    try:
        cfg = load_config(SCRIPT.with_suffix(".ini"), require_token=not args.dry_run)
        if args.test_telegram:
            send_telegram(cfg, f"Coins monitoring test\nHost: {socket.gethostname()}\nTime (UTC): {utc_now()}")
            return 0
        state_path = SCRIPT.with_suffix(".state.json")
        if args.dry_run:
            return run_check(cfg, state_path, dry_run=True)
        with single_instance(SCRIPT.with_suffix(".lock")) as acquired:
            if not acquired:
                LOG.info("Another monitoring process is running; skipping this invocation.")
                return 0
            return run_check(cfg, state_path)
    except MonitorError as exc:
        LOG.error("%s", exc)
        return 1
    except OSError:
        LOG.error("Local I/O failed; check directory permissions and available disk space.")
        return 1
    except Exception as exc:
        # Avoid leaking tokens through an unexpected exception containing a request URL.
        LOG.error("Unexpected %s; monitoring did not complete.", type(exc).__name__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
