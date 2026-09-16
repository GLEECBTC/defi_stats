# Coins repository monitoring (temporary workaround)

`coins_monitoring.py` checks `GLEECBTC/coins`, branch `master`, using GitHub's API. It saves the coin identifiers from the repository's `coins` file for each observed commit, compares snapshots, and includes every added and removed coin in Telegram notifications. It requires Linux and Python 3.8+ (standard library only), Docker Compose v2, and HTTPS access to GitHub and Telegram. No local clone of the coins repository is required.

The configuration must be beside the script with the same basename: `coins_monitoring.ini`. Renaming the script also changes its expected configuration, state, and lock filenames.

## Production setup

1. Copy the `coins_monitoring` directory into `/home/tech/defi_stats`, so the script is located at `/home/tech/defi_stats/coins_monitoring/coins_monitoring.py`. If deploying through Git, create `coins_monitoring.ini` beside the script from the versionable `coins_monitoring.ini.example` template instead. Keep `docker.project_dir = /home/tech/defi_stats`: the Compose project remains in the parent directory.
2. Set `telegram.bot_token` in the INI file. Keep `bot_username = gleec_monitor_bot` and `chat_id = -5100391257`, or edit them as needed. The script verifies that the token belongs to the configured bot. Add the bot to the group and grant it permission to send messages.
3. Check the Docker executable path with `command -v docker`, and update the absolute `docker.executable` setting if necessary.
4. Use the same Unix account and Docker environment that can successfully run `docker compose restart defi_stats` inside `/home/tech/defi_stats`. The account must also be able to write state and lock files beside the script.
5. Protect the INI file, check the planned action, and optionally send a test notification:

```bash
chmod 600 /home/tech/defi_stats/coins_monitoring/coins_monitoring.ini
/usr/bin/python3 /home/tech/defi_stats/coins_monitoring/coins_monitoring.py --dry-run
/usr/bin/python3 /home/tech/defi_stats/coins_monitoring/coins_monitoring.py --test-telegram
```

`--dry-run` reads GitHub and any existing state, downloads missing coin snapshots, and logs additions and removals when a previous baseline exists. It does not write files, restart Docker, or contact Telegram. It works before the bot token has been filled in. `--test-telegram` sends a real test message, without changing the baseline or restarting the service.

Run once normally to initialize the baseline:

```bash
/usr/bin/python3 /home/tech/defi_stats/coins_monitoring/coins_monitoring.py
```

The first normal run records the current SHA and its coin snapshot without restarting or notifying. Existing coins are not reported as newly added on initialization. It does not repair an already stale running process. Subsequent changes trigger restarts. State is kept in `coins_monitoring.state.json`; do not delete it between cron runs.

Add this entry to the deployment account's crontab (`crontab -e`):

```cron
*/30 * * * * /usr/bin/python3 /home/tech/defi_stats/coins_monitoring/coins_monitoring.py >> /home/tech/defi_stats/coins_monitoring/coins_monitoring.log 2>&1
```

Cron runs at minute 0 and minute 30. Configure log rotation for `coins_monitoring.log` if keeping the workaround long term. Application messages, comments, help, and Telegram messages are in English. Docker is invoked with the C locale.

The local INI containing credentials, runtime state, lock file, and logs are ignored by Git. Copy the INI separately when deploying; it will not be included by a normal `git add` / commit. An optional GitHub token is supported in `[github]`; the public repository does not require one.

If migrating an existing installation from the repository root, move its INI and `coins_monitoring.state.json` into this directory while the monitor is not running, and update the crontab path. Preserving the state file preserves the previous baseline and queued notifications. The script creates its lock file beside itself.

## Behavior

- Every branch-head SHA change triggers one `docker compose restart defi_stats` from the configured project directory. This includes unrelated commits and force-pushes, not only edits to `coins_config.json`. Multiple commits between checks result in one restart. A change that is reverted to exactly the previous SHA between checks cannot be observed by polling.
- A file lock prevents overlapping normal runs of this script at the same path.
- If GitHub or a required coin snapshot cannot be read and validated, the script leaves the baseline unchanged and does not restart. Already queued notifications can still be delivered before this check.
- If Docker fails or times out, the old SHA remains the baseline. A failure notification is queued and the next cron run retries the restart. A timeout means the eventual Docker outcome is unknown.
- On successful restart, the SHA and notification are saved atomically before Telegram is contacted. A Telegram failure therefore retries the notification on a later invocation without repeating a successful restart for that SHA. Pending notifications are also retried when the branch has not changed.
- Telegram failures do not prevent restarts for later branch changes. Notification delivery is at least once: if Telegram accepts a message but its response is lost, or the process exits before saving delivery, a duplicate message is possible.
- A crash after Docker succeeds but before state is saved can cause a repeated restart on the next invocation. A file and Docker cannot be updated as one transaction.
- Corrupt state or a state/config target mismatch produces an error instead of silently establishing a new baseline. Inspect and intentionally archive/reset the old state when changing the target; a missing state file starts a new baseline.
- Exit code is 0 for success, initialization, unchanged branch, or an overlapping run being skipped; 1 indicates a monitoring, restart, or notification failure. Argument errors use argparse's exit code 2.

## Coin snapshots and comparison

Snapshots are stored inside `coins_monitoring.state.json` as a dictionary keyed by full commit SHA. For example, the following is an illustrative fragment of the state:

```json
{
  "coins_by_commit": {
    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa": ["BTC", "LTC", "OLDCOIN"],
    "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb": ["BTC", "LTC", "USDS-BASE", "USDS-ERC20"]
  }
}
```

The script reads the root-level [`coins` file](https://github.com/GLEECBTC/coins/blob/master/coins) at the exact SHA returned by the branch check, through GitHub's [repository contents API](https://docs.github.com/en/rest/repos/contents#get-repository-content). It extracts the full `coin` strings from the JSON array. Platform suffixes and case are preserved; for example, `USDS-BASE` and `USDS-ERC20` are distinct. Lists are sorted and deduplicated. Reordering entries, duplicate entries, and changes to other properties do not count as additions or removals.

Previously saved snapshots are retained and reused, including after a failed restart or a force-push back to an already seen commit. No automatic history pruning is performed. The state file therefore grows with the number of observed commits.

The comparison is between the previous successfully processed SHA and the current branch head. This is a snapshot for each commit observed by polling, not a traversal of every intermediate Git commit. If several commits occur between checks, the notification reports their net effect. A coin added and removed entirely between checks is not reported.

On upgrade from the earlier script, keep the existing state file. If it has no `coins_by_commit` field, the script loads the `coins` file at the saved `last_sha` and then at the current SHA. If the branch is unchanged, it just saves the missing snapshot without restarting or sending a new notification. Existing queued notifications are preserved. If the old commit can no longer be downloaded, the script reports an error and retries on the next run; it does not treat the missing snapshot as an empty coin list. No INI or cron changes are required for this upgrade.

Notifications retain the repository, SHA, host, service, time, restart status, and compare link. The new section looks like this for the example above:

```text
Coins in file: 3 -> 4

Added coins (2):
+ USDS-BASE
+ USDS-ERC20

Removed coins (1):
- OLDCOIN
```

An empty section says `Added coins (0):` or `Removed coins (0):`, followed by `None`. A branch change still triggers a restart and a notification when coin membership is unchanged, preserving the existing restart policy.

Long notifications are split into numbered messages below Telegram's [sendMessage length limit](https://core.telegram.org/bots/api#sendmessage), without truncating the coin list. Each part is saved separately in the notification queue. After successful delivery, that part is removed and state is saved; a later failure retries only the remaining parts. Telegram rate limits can delay those remaining parts until a later cron run.

## Limitation of the workaround

A successful Docker command is not an application health check and does not prove that a particular trade is now visible. The script does not alter the application's cache files, memcache, or MM2 nodes.

Restarting resets the Python singleton, but a singleton can still latch an old memcache value if the application reads it before refreshing `coins_config`. The current code has startup cache refresh tasks, but no guarantee that the first singleton read happens after a successful refresh. Therefore this is a best-effort temporary workaround, not a replacement for fixing the singleton. Verify the relevant API response after deployment using a time window that contains the trade.

## Verification without production side effects

The standalone unittest suite mocks GitHub, Docker, and Telegram and writes only to temporary directories. Run it from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s coins_monitoring/tests -v
```

Do not substitute the API project's pytest suite for this check: its existing session cleanup mutates caches.

## API references

- [GitHub: Get a reference](https://docs.github.com/en/rest/git/refs#get-a-reference)
- [GitHub: Get repository content](https://docs.github.com/en/rest/repos/contents#get-repository-content)
- [Telegram Bot API: getMe](https://core.telegram.org/bots/api#getme)
- [Telegram Bot API: sendMessage](https://core.telegram.org/bots/api#sendmessage)
