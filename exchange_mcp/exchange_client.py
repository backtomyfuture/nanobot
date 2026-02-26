"""Exchange API HTTP client."""

from typing import Any
from urllib.parse import quote

import httpx


class ExchangeClient:
    """Thin HTTP client for the Exchange API gateway."""

    def __init__(self, api_url: str, api_key: str, account_id: int, ssl_verify: bool = False):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.account_id = account_id
        self.ssl_verify = ssl_verify

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-API-KEY": self.api_key} if self.api_key else {}

    async def get_email(self, email_id: str) -> dict[str, Any]:
        encoded = quote(email_id, safe="")
        async with httpx.AsyncClient(verify=self.ssl_verify, timeout=20.0) as client:
            resp = await client.get(
                f"{self.api_url}/{encoded}",
                params={"account_id": self.account_id},
                headers=self._headers,
            )
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                if data and "id" not in data:
                    data["id"] = email_id
                return data
        return {}

    async def reply_email(
        self, email_id: str, body: str, to: list[str] | None = None, cc: list[str] | None = None
    ) -> bool:
        payload: dict[str, Any] = {
            "account_id": self.account_id,
            "reference_item_id": email_id,
            "body": body,
            "body_type": "html",
        }
        if to:
            payload["to"] = to
        if cc:
            payload["cc"] = cc
        async with httpx.AsyncClient(verify=self.ssl_verify, timeout=15.0) as client:
            resp = await client.post(f"{self.api_url}/reply", json=payload, headers=self._headers)
            return resp.status_code == 200 and resp.json().get("code") == 200

    async def forward_email(self, email_id: str, to: list[str], body: str) -> bool:
        payload = {
            "account_id": self.account_id,
            "reference_item_id": email_id,
            "to": to,
            "body": body,
            "body_type": "html",
        }
        async with httpx.AsyncClient(verify=self.ssl_verify, timeout=15.0) as client:
            resp = await client.post(f"{self.api_url}/forward", json=payload, headers=self._headers)
            return resp.status_code == 200 and resp.json().get("code") == 200

    async def mark_as_read(self, email_id: str) -> bool:
        encoded = quote(email_id, safe="")
        async with httpx.AsyncClient(verify=self.ssl_verify, timeout=10.0) as client:
            resp = await client.put(
                f"{self.api_url}/{encoded}/read",
                params={"account_id": self.account_id, "is_read": True},
                headers=self._headers,
            )
            return resp.status_code == 200 and resp.json().get("code") == 200

    async def create_draft(
        self, to: list[str], subject: str, body: str, cc: list[str] | None = None
    ) -> bool:
        payload = {
            "account_id": self.account_id,
            "to": to,
            "cc": cc or [],
            "subject": subject,
            "body": body,
            "body_type": "html",
            "folder": "Drafts",
        }
        async with httpx.AsyncClient(verify=self.ssl_verify, timeout=10.0) as client:
            resp = await client.post(f"{self.api_url}/drafts", json=payload, headers=self._headers)
            return resp.status_code == 200

    async def get_recent_emails(self, limit: int = 10) -> list[dict[str, Any]]:
        params = {
            "account_id": self.account_id,
            "folder": "INBOX",
            "limit": limit,
            "unread_only": "True",
        }
        async with httpx.AsyncClient(verify=self.ssl_verify, timeout=15.0) as client:
            resp = await client.get(f"{self.api_url}/list", params=params, headers=self._headers)
            if resp.status_code != 200:
                return []
            items = resp.json().get("data", {}).get("items", [])
            results = []
            for item in items:
                eid = item.get("id")
                if eid:
                    detail = await self.get_email(eid)
                    if detail:
                        results.append(detail)
            return results
