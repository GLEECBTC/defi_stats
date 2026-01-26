#!/usr/bin/env python3
import os
from typing import Dict, Optional

import requests

from util.cron import cron
from util.logger import logger
import util.memcache as memcache


class GitHubReleasesClient:
    def __init__(self, owner: str, repo: str) -> None:
        self.owner = owner
        self.repo = repo
        self.base_url = f"https://api.github.com/repos/{owner}/{repo}"
        self.session = requests.Session()
        self._configure_auth()

    def _configure_auth(self):
        user = os.getenv("GH_USER")
        token = os.getenv("GH_TOKEN")
        if user and token:
            self.session.auth = (user, token)

    def get_latest_release(self) -> Optional[Dict]:
        url = f"{self.base_url}/releases/latest"
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            resp = self.session.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
        except requests.RequestException as exc:  # pragma: no cover - network failure
            logger.warning(f"Failed to fetch latest release from GitHub: {exc}")
            return None
        return resp.json()


class DexVersionService:
    CHANGELOG_URL = "https://github.com/GLEECBTC/gleec-wallet/blob/main/CHANGELOG.md"
    OWNER = "GLEECBTC"
    REPO = "gleec-wallet"

    def __init__(self, client: GitHubReleasesClient | None = None) -> None:
        self.client = client or GitHubReleasesClient(self.OWNER, self.REPO)

    def _normalize_tag(self, tag_name: str) -> str:
        if tag_name.lower().startswith("v"):
            return tag_name[1:]
        return tag_name

    def _status_for_version(self, version: str) -> str:
        try:
            parts = [int(p) for p in version.split(".")]
            patch = parts[2] if len(parts) > 2 else 0
            if patch == 0:
                return "required"
        except Exception:
            logger.warning(f"Unable to derive patch info from version '{version}'")
        return "recommended"

    def _build_payload(self, version: str, download_url: str) -> Dict:
        data = {
            "status": self._status_for_version(version),
            "new_version": version,
            "changelog": self.CHANGELOG_URL,
            "download_url": download_url,
        }
        return {"last_synced": int(cron.now_utc()), "data": data}

    def refresh(self) -> Optional[Dict]:
        release = self.client.get_latest_release()
        if not release:
            return None
        tag_name = release.get("tag_name")
        html_url = release.get("html_url")
        if not tag_name:
            logger.warning("GitHub release missing tag_name")
            return None
        normalized = self._normalize_tag(tag_name)
        download_url = html_url or f"https://github.com/{self.OWNER}/{self.REPO}/releases/tag/{tag_name}"
        payload = self._build_payload(normalized, download_url)
        memcache.set_dex_version(payload)
        return payload

    def get_cached_payload(self) -> Optional[Dict]:
        cached = memcache.get_dex_version()
        if cached and isinstance(cached, dict) and "data" in cached:
            return cached
        return None

    def get_version_info(self) -> Optional[Dict]:
        cached = self.get_cached_payload()
        if cached:
            return cached["data"]
        refreshed = self.refresh()
        if refreshed:
            return refreshed["data"]
        return None


