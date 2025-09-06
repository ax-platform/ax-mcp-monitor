from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Dict, List, Optional

from mcp.client.session import ClientSession

from .handlers import HandlerContext, MessageHandler


@dataclass
class Rule:
    match: str
    reply: str
    once: bool = True
    tag: Optional[str] = None


def _load_rules(path: str) -> List[Rule]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    raw_rules = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(raw_rules, list):
        raise ValueError("Invalid rules file: expected { 'rules': [ ... ] }")
    rules: List[Rule] = []
    for r in raw_rules:
        if not isinstance(r, dict) or "match" not in r or "reply" not in r:
            continue
        rules.append(
            Rule(
                match=str(r["match"]),
                reply=str(r["reply"]),
                once=bool(r.get("once", True)),
                tag=r.get("tag"),
            )
        )
    return rules


class _State:
    def __init__(self, path: Optional[str]) -> None:
        self.path = os.path.expanduser(path) if path else None
        self.claimed: Dict[str, Any] = {}
        if self.path and os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.claimed = json.load(f) or {}
            except Exception:
                self.claimed = {}

    def save(self) -> None:
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.claimed, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def is_claimed(self, key: str) -> bool:
        return str(key) in self.claimed

    def mark_claimed(self, key: str, info: Any) -> None:
        self.claimed[str(key)] = info
        self.save()


class CodeQuestHandler(MessageHandler):
    """
    Match secret codes and reply with configured messages.

    Configuration via env:
      CODEQUEST_CONFIG=/path/to/rules.json   # required
      CODEQUEST_STATE=~/.codequest/state.json  # optional (tracks one-time claims)
      CODEQUEST_HMAC_SECRET=...  # optional HMAC key to verify signed codes

    Rules file format (JSON):
    {
      "rules": [
        {"match": "^INIT-(?P<code>[A-Z0-9]{6})$", "reply": "Welcome! Your code: {code}", "once": true, "tag": "init"}
      ]
    }

    A code is considered the first regex group or named group "code"; if HMAC is enabled,
    signed codes can be provided as CODE:HEX_SIG where HEX_SIG is HMAC-SHA256(secret, CODE).
    """

    def __init__(self) -> None:
        cfg = os.environ.get("CODEQUEST_CONFIG")
        if not cfg:
            raise RuntimeError("CODEQUEST_CONFIG is required for CodeQuestHandler")
        self.rules = _load_rules(cfg)
        self.state = _State(os.environ.get("CODEQUEST_STATE"))
        self.hmac_secret = os.environ.get("CODEQUEST_HMAC_SECRET")
        # Generic token pattern like !code XYZ or raw token at start of line
        self.token_patterns = [
            re.compile(r"^!code\s+([A-Za-z0-9:_-]{4,})\b"),
            re.compile(r"^([A-Za-z0-9:_-]{4,})\b"),
        ]

    async def handle(self, session: ClientSession, message: dict, ctx: HandlerContext) -> bool:
        raw = (message.get("content") or "").strip()
        if not raw:
            return False

        token = self._extract_token(raw)
        if not token:
            return False

        # Separate optional signature: CODE:SIG
        code, sig = self._split_sig(token)
        if self.hmac_secret and not self._verify_sig(code, sig):
            await self._reply(session, message, "Invalid code signature.")
            return True

        # Try each rule
        for rule in self.rules:
            m = re.search(rule.match, code)
            if not m:
                continue

            claim_key = f"{rule.tag or 'rule'}:{m.group(0)}"
            if rule.once and self.state.is_claimed(claim_key):
                await self._reply(session, message, "Code already used." )
                return True

            # Build reply with groupdict
            gd = m.groupdict() if hasattr(m, "groupdict") else {}
            # Also include 'code' as whole match if not present
            if "code" not in gd:
                gd["code"] = m.group(0)

            reply = rule.reply.format(**gd)
            await self._reply(session, message, reply)

            if rule.once:
                self.state.mark_claimed(claim_key, {"by": ctx.agent_name})
            return True

        # No rule matched the token
        return False

    def _extract_token(self, text: str) -> Optional[str]:
        for pat in self.token_patterns:
            m = pat.search(text)
            if m:
                return m.group(1)
        return None

    def _split_sig(self, token: str) -> tuple[str, Optional[str]]:
        if ":" in token:
            code, sig = token.split(":", 1)
            return code, sig
        return token, None

    def _verify_sig(self, code: str, sig: Optional[str]) -> bool:
        if not sig or not self.hmac_secret:
            return False
        try:
            mac = hmac.new(self.hmac_secret.encode("utf-8"), code.encode("utf-8"), sha256).hexdigest()
            return hmac.compare_digest(mac, sig)
        except Exception:
            return False

    async def _reply(self, session: ClientSession, message: dict, content: str) -> None:
        args = {"action": "send", "content": content}
        parent_id = message.get("id") or message.get("message_id")
        if parent_id:
            args["parent_message_id"] = parent_id
        await session.call_tool("messages", arguments=args)

