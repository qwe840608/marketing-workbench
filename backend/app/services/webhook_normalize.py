"""Byte-exact platform verification and normalization, independent of HTTP routing."""

import base64
import hashlib
import hmac
import json
import re
import time
from datetime import UTC, datetime


class GatewayError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


def secret(settings, name, session=None):
    from app.services import credentials

    value = (credentials.resolve(name.upper(), settings, session)
             if name.upper() in credentials.NAMES else getattr(settings, name, None))
    return value.get_secret_value() if value else ""


def dump(value, *, canonical=False):
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=canonical, allow_nan=False
    )


def digest(value, *, canonical=False):
    return hashlib.sha256(dump(value, canonical=canonical).encode()).hexdigest()


def valid_id(value):
    return isinstance(value, str) and bool(re.fullmatch(r"\S{1,255}", value))


def instant(value, milliseconds=False):
    try:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                return None
            date = value.astimezone(UTC)
        elif isinstance(value, (int, float)):
            date = datetime.fromtimestamp(
                value / (1000 if milliseconds or value >= 1e12 else 1), UTC
            )
        else:
            date = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
        return date.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except (ValueError, TypeError, AttributeError, OverflowError, OSError):
        return None


def verify_signature(raw, supplied, key, platform):
    if not isinstance(supplied, str) or not key:
        return False
    expected = hmac.digest(key.encode(), raw, "sha256")
    if platform == "meta":
        return bool(re.fullmatch(r"sha256=[a-fA-F0-9]{64}", supplied)) and hmac.compare_digest(
            expected, bytes.fromhex(supplied[7:])
        )
    return bool(re.fullmatch(r"[A-Za-z0-9+/]{43}=", supplied)) and hmac.compare_digest(
        expected, base64.b64decode(supplied)
    )


def verify_control(headers, key, path, raw=None, now=None):
    probe = path == "/webhook/mwb-gateway-probe"
    prefix = "x-mwb-probe-" if probe else "x-mwb-sync-"
    stamp, signature = headers.get(prefix + "time"), headers.get(prefix + "signature")
    if (
        not key
        or len(key) < 32
        or not isinstance(stamp, str)
        or not re.fullmatch(r"\d{10}", stamp)
        or not isinstance(signature, str)
        or not re.fullmatch(r"[a-f0-9]{64}", signature)
    ):
        return False
    if abs((time.time() if now is None else now) - int(stamp)) > (60 if probe else 300):
        return False
    material = ("GET" if probe else "POST") + "\n" + path + "\n" + stamp
    if raw is not None:
        material += "\n" + hashlib.sha256(raw).hexdigest()
    return hmac.compare_digest(
        hmac.new(key.encode(), material.encode(), hashlib.sha256).hexdigest(), signature
    )


def verify_challenge(query, key):
    supplied, challenge = query.get("hub.verify_token"), query.get("hub.challenge")
    return bool(
        key
        and len(key) >= 32
        and isinstance(supplied, str)
        and hmac.compare_digest(key.encode(), supplied.encode())
        and query.get("hub.mode") == "subscribe"
        and isinstance(challenge, str)
        and re.fullmatch(r"\d{1,100}", challenge)
    )


def parse(raw):
    if len(raw) > 1024 * 1024:
        raise GatewayError(413, "payload_too_large")
    try:
        value = json.loads(
            raw.decode("utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError())
        )
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise GatewayError(400, "invalid_json") from None


def meta_message(event, entry, kind, platform, account):
    value = event.get("value") or {}
    facebook = platform == "facebook"
    comment = event.get("field") == ("feed" if facebook else "comments") and (
        not facebook or value.get("item") == "comment"
    )
    if not comment or (facebook and value.get("verb") not in ("add", "edited")):
        return []
    identity = value.get("comment_id" if facebook else "id")
    post = value.get("post_id") if facebook else (value.get("media") or {}).get("id")
    author = value.get("from") or {}
    text = value.get("message" if facebook else "text")
    stamp = instant(
        next(
            (
                v
                for v in (value.get("created_time"), value.get("timestamp"), entry.get("time"))
                if v is not None
            ),
            None,
        )
    )
    if (
        not all(valid_id(v) for v in (identity, post, author.get("id")))
        or not isinstance(text, str)
        or not stamp
    ):
        return None
    own = author["id"] == account
    contact = {"external_id": author["id"]}
    name = author.get("name") or author.get("username")
    if isinstance(name, str):
        contact["display_name"] = name[:200]
    reference = {"post_external_id": post}
    if "parent_id" in value:
        reference.update(
            parent_known=True, parent_id=None if value["parent_id"] == post else value["parent_id"]
        )
    return [
        dict(
            external_id=identity,
            thread_external_id=post,
            kind="comment_thread",
            post_external_id=post,
            contact=contact,
            direction="out" if own else "in",
            author_type="brand" if own else "fan",
            text=text,
            sent_at=stamp,
            **(
                {"edited_at": instant(entry.get("time")) or stamp}
                if value.get("verb") == "edited"
                else {}
            ),
            source_ref_json=reference,
        )
    ]


def iter_meta_envelopes(payload, page, instagram):
    if (
        payload.get("object") not in ("page", "instagram")
        or not isinstance(payload.get("entry"), list)
        or len(payload["entry"]) > 100
    ):
        raise GatewayError(400, "invalid_entries")
    platform = "facebook" if payload["object"] == "page" else "instagram"
    account = page if platform == "facebook" else instagram
    if any(not isinstance(e, dict) or str(e.get("id")) != account for e in payload["entry"]):
        raise GatewayError(403, "account_mismatch")
    for entry in payload["entry"]:
        if any(k in entry and not isinstance(entry[k], list) for k in ("messaging", "changes")):
            raise GatewayError(400, "invalid_events")
        events = [(k, e) for k in ("messaging", "changes") for e in entry.get(k, [])]
        if len(events) > 200:
            raise GatewayError(413, "too_many_events")
        for kind, event in events:
            if kind == "messaging":
                continue
            try:
                messages = meta_message(event, entry, kind, platform, account)
            except (TypeError, AttributeError, KeyError):
                messages = None
            material = {"account": account, "kind": kind, "event": event}
            if "time" in entry:
                material["time"] = entry["time"]
            identity = "change:" + digest(material, canonical=True)
            envelope = dict(
                platform=platform,
                account_external_id=account,
                external_id=identity,
                signature_ok=True,
                payload={
                    "object": payload["object"],
                    "entry": [
                        {
                            **{k: v for k, v in entry.items() if k not in ("messaging", "changes")},
                            kind: [event],
                        }
                    ],
                },
                messages=messages,
            )
            envelope["observed_at"] = (
                instant(entry.get("time")) or instant(event.get("timestamp"), True)
                if isinstance(event, dict)
                else None
            )
            yield envelope

