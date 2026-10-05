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
    try:
        status = requests.get(
            f"{base}/api/checkNumberStatus",
            params={"phone": number, "session": session},
            headers={"X-Api-Key": api_key},
            timeout=20,
        )
        if status.ok and isinstance(status.json(), dict) and status.json().get("numberExists") is False:
            return False, "whatsapp_number_not_registered"
        response = requests.post(
            f"{base}/api/sendText",
            headers={"X-Api-Key": api_key, "Content-Type": "application/json"},
            json={"session": session, "chatId": f"{number}@c.us", "text": message},
            timeout=30,
        )
        response.raise_for_status()
        return True, "sent"
    except Exception as exc:
        return False, f"waha_send_failed:{exc}"
