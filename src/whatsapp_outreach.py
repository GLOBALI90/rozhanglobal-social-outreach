import os
import re
from urllib.parse import urljoin

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 ROZHAN-Global-Outreach/1.0"}


def _normalize(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("00"):
        digits = digits[2:]
    return digits if 8 <= len(digits) <= 15 else ""


def extract_phone(url: str) -> str:
    if not url or "linkedin.com" in url or "facebook.com" in url:
        return ""
    pages = [url, urljoin(url, "/contact"), urljoin(url, "/contact-us"), urljoin(url, "/contacts")]
    for page in dict.fromkeys(pages):
        try:
            r = requests.get(page, headers=HEADERS, timeout=15)
            r.raise_for_status()
        except Exception:
            continue
        text = r.text[:500_000]
        matches = re.findall(r"(?<!\d)(\+?\d[\d() .-]{7,18}\d)(?!\d)", text)
        for candidate in matches:
            number = _normalize(candidate)
            if number:
                return number
    return ""


def send_whatsapp(phone: str, message: str) -> tuple[bool, str]:
    if os.getenv("SEND_WHATSAPP", "false").strip().lower() != "true":
        return False, "whatsapp_send_disabled"
    base = os.getenv("WAHA_URL", "").strip().rstrip("/")
    api_key = os.getenv("WAHA_API_KEY", "").strip()
    session = os.getenv("WAHA_SESSION", "default").strip() or "default"
    number = _normalize(phone)
    if not base or not api_key:
        return False, "missing_waha_configuration"
    if not number:
        return False, "invalid_phone"
    headers = {"X-Api-Key": api_key}
    try:
        # Blitz free instances can sleep. Wake WAHA before every outbound attempt.
        wake = requests.post(
            f"{base}/api/sessions/{session}/start",
            headers={**headers, "Content-Type": "application/json"},
            json={},
            timeout=60,
        )
        if not (wake.ok or wake.status_code == 409):
            return False, f"waha_wake_failed:http_{wake.status_code}"

        # Give a cold-starting WAHA instance a short window to become responsive.
        last_status = None
        for _ in range(3):
            try:
                status = requests.get(
                    f"{base}/api/checkNumberStatus",
                    params={"phone": number, "session": session},
                    headers=headers,
                    timeout=30,
                )
                last_status = status
                if status.ok:
                    break
            except requests.RequestException:
                pass
            import time
            time.sleep(5)

        if last_status is None or not last_status.ok:
            code = last_status.status_code if last_status is not None else "timeout"
            return False, f"waha_not_ready:http_{code}"

        payload = last_status.json()
        if isinstance(payload, dict) and payload.get("numberExists") is False:
            return False, "whatsapp_number_not_registered"
        response = requests.post(
            f"{base}/api/sendText",
            headers={**headers, "Content-Type": "application/json"},
            json={"session": session, "chatId": f"{number}@c.us", "text": message},
            timeout=30,
        )
        response.raise_for_status()
        return True, "sent"
    except Exception as exc:
        return False, f"waha_send_failed:{exc}"
