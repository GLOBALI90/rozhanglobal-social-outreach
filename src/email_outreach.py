import csv
import json
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from .whatsapp_outreach import extract_phone, send_whatsapp

ROOT = Path(__file__).resolve().parents[1]
COMPANY = json.loads((ROOT / "config/company.json").read_text(encoding="utf-8"))
LEADS = ROOT / "data/social_leads.csv"
OUTREACH = ROOT / "data/social_outreach.csv"
ACTIVITY = ROOT / "data/social_activity.csv"

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
GEMINI_DEFAULT_MODEL = "gemini-2.5-flash-lite"
CLOUDFLARE_URL_TEMPLATE = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
CLOUDFLARE_DEFAULT_MODEL = "@cf/zai-org/glm-4.7-flash"
HEADERS = {"User-Agent": "Mozilla/5.0 ROZHAN-Global-Outreach/1.0"}
FIELDS = [
    "run_id", "platform", "slot", "target_name", "target_url", "recipient_email",
    "subject", "body", "status", "provider", "source", "whatsapp_phone", "whatsapp_status", "created_at"
]


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def _load_sent_whatsapp() -> set[str]:
    if not OUTREACH.exists():
        return set()
    try:
        with OUTREACH.open(encoding="utf-8") as f:
            return {str(r.get("whatsapp_phone", "")).strip() for r in csv.DictReader(f) if r.get("whatsapp_status") == "sent" and r.get("whatsapp_phone")}
    except Exception:
        return set()

def _daily_outreach_count() -> int:
    if not OUTREACH.exists():
        return 0
    today = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).date().isoformat()
    count = 0
    try:
        with OUTREACH.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                created = str(row.get("created_at", ""))
                if created.startswith(today) and (row.get("status") == "sent" or row.get("whatsapp_status") == "sent"):
                    count += 1
    except Exception:
        return 0
    return count

def _load_sent() -> set[str]:
    if not OUTREACH.exists():
        return set()
    try:
        with OUTREACH.open(encoding="utf-8") as f:
            return {str(r.get("recipient_email", "")).strip().lower() for r in csv.DictReader(f) if r.get("status") == "sent"}
    except Exception:
        return set()


def _load_social_context(run_id: str, target_url: str) -> str:
    if not ACTIVITY.exists():
        return "No Composio social activity was available."
    notes: list[str] = []
    try:
        with ACTIVITY.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("run_id") == run_id and row.get("target_url") == target_url and row.get("status") == "success":
                    summary = str(row.get("summary", "")).strip()
                    tool = str(row.get("tool", "")).strip()
                    if summary:
                        notes.append(f"{tool}: {summary}")
    except Exception:
        return "No Composio social activity was available."
    return " | ".join(notes)[:14000] if notes else "No successful Composio social activity was available."


def _save(row: dict[str, str]) -> None:
    exists = OUTREACH.exists() and OUTREACH.stat().st_size > 0
    with OUTREACH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in FIELDS})


def _extract_emails(url: str) -> tuple[str, str]:
    """Return first public business email and source URL. Never infer addresses."""
    if not url or "linkedin.com" in _domain(url) or "facebook.com" in _domain(url):
        return "", ""
    pages = [url, urljoin(url, "/contact"), urljoin(url, "/contact-us"), urljoin(url, "/contacts")]
    seen = set()
    for page in pages:
        if page in seen:
            continue
        seen.add(page)
        try:
            r = requests.get(page, headers=HEADERS, timeout=20, allow_redirects=True)
            r.raise_for_status()
        except Exception:
            continue
        text = r.text[:500_000]
        emails = re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, re.I)
        for email in emails:
            e = email.lower()
            if e.endswith("@example.com"):
                continue
            if any(x in e for x in ("noreply@", "no-reply@", "donotreply@", "do-not-reply@")):
                continue
            return e, page
    return "", ""


def _find_company_website(target_name: str, country: str, sector: str) -> str:
    key = os.getenv("YOU_API_KEY", "").strip()
    if not key or not target_name:
        return ""
    query = f'"{target_name}" {country} {sector} official website contact'
    url = os.getenv("YOU_SEARCH_URL", "").strip() or "https://ydc-index.io/v1/search"
    try:
        r = requests.post(
            url,
            headers={"X-API-Key": key, "Accept": "application/json", "Content-Type": "application/json"},
            json={"query": query, "count": 10},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        web = (data.get("results") or {}).get("web") or []
        for item in web:
            if not isinstance(item, dict):
                continue
            candidate = str(item.get("url", "")).strip()
            d = _domain(candidate)
            if d and "linkedin.com" not in d and "facebook.com" not in d and "youtube.com" not in d:
                return candidate
    except Exception as exc:
        print(f"Company website lookup failed for {target_name}: {exc}")
    return ""


def _parse_json(text: str) -> dict[str, str] | None:
    text = (text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(text[start:end + 1])
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    subject = str(obj.get("subject", "")).strip()
    body = str(obj.get("body", "")).strip()
    if not subject or not body:
        return None
    return {"subject": subject, "body": body}


def _prompt(lead: dict[str, str], company_website: str, social_context: str) -> str:
    return f"""You are ROZHAN GLOBAL's B2B export outreach writer.
Write one concise, professional first-contact email to a potential business buyer/importer/industrial consumer.

OUR COMPANY
Legal name: {COMPANY.get('legal_name')}
Brand: {COMPANY.get('brand')}
WhatsApp: {COMPANY.get('whatsapp', '+989023517939')}
Website: {COMPANY.get('website', 'https://www.rozhanglobal.com')}
Email: {COMPANY.get('email', 'info@rozhanglobal.com')}
Positioning: {COMPANY.get('positioning')}

TARGET
Platform: {lead.get('platform')}
Target name: {lead.get('name')}
Target URL: {lead.get('url')}
Country: {lead.get('country', 'China')}
Industry: {lead.get('sector', '')}
Region: {lead.get('region', '')}
Industrial zone: {lead.get('industrial_zone', '')}
Official website found (only if verified): {company_website or 'not found'}
Search context: {lead.get('title', '')}. {lead.get('snippet', '')}
Composio social context: {social_context}

Rules:
- Use only facts present above; do not invent purchase volumes, current contracts, product requirements, certifications, prices, or personal facts.
- Prefer concrete references to verified company activity from the social context when available.
- Show that ROZHAN GLOBAL can supply and source competitive international materials relevant to the target's visible business activity.
- Ask what materials/products they currently source or import and whether they are open to a quotation or supplier comparison.
- Mention supply continuity and competitive sourcing naturally, not as an exaggerated claim.
- Keep it short, human, and businesslike; avoid spammy marketing language.
- Do not claim to know the recipient's private identity.
- Include our WhatsApp and website in the signature.
- Do not include placeholders.
Return ONLY JSON: {{"subject":"...","body":"..."}}"""


def _generate_with_gemini(prompt: str) -> tuple[dict[str, str] | None, str]:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        return None, ""
    model = os.getenv("GEMINI_MODEL", GEMINI_DEFAULT_MODEL).strip() or GEMINI_DEFAULT_MODEL
    try:
        r = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent".format(model),
            params={"key": key},
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.35},
            },
            timeout=45,
        )
        r.raise_for_status()
        payload = r.json()
        candidates = payload.get("candidates") or []
        parts = ((candidates[0] if candidates else {}).get("content") or {}).get("parts") or []
        text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
        return _parse_json(text), f"gemini:{model}"
    except Exception as exc:
        print(f"Gemini email generation failed: {exc}")
        return None, ""


def _generate_with_cloudflare(prompt: str) -> tuple[dict[str, str] | None, str]:
    token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
    if not token or not account_id:
        return None, ""
    model = os.getenv("CLOUDFLARE_AI_MODEL", CLOUDFLARE_DEFAULT_MODEL).strip() or CLOUDFLARE_DEFAULT_MODEL
    url = CLOUDFLARE_URL_TEMPLATE.format(account_id=account_id, model=model)
    try:
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"prompt": prompt, "max_tokens": 900, "temperature": 0.35},
            timeout=45,
        )
        r.raise_for_status()
        result = r.json().get("result", {})
        text = result.get("response", "") if isinstance(result, dict) else str(result)
        return _parse_json(text), f"cloudflare:{model}"
    except Exception as exc:
        print(f"Cloudflare email generation failed: {exc}")
        return None, ""


def generate_email(lead: dict[str, str], website: str, social_context: str) -> tuple[dict[str, str] | None, str]:
    prompt = _prompt(lead, website, social_context)
    result, provider = _generate_with_gemini(prompt)
    if result:
        return result, provider
    result, provider = _generate_with_cloudflare(prompt)
    if result:
        return result, provider
    return None, ""


def _send(to: str, subject: str, body: str) -> tuple[bool, str]:
    username = os.getenv("GMAIL_USERNAME", "").strip()
    password = os.getenv("GMAIL_APP_PASSWORD", "").strip().replace(" ", "")
    if not username or not password:
        return False, "missing_gmail_credentials"
    message = EmailMessage()
    message["From"] = username
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    context = ssl.create_default_context()
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as smtp:
            smtp.starttls(context=context)
            smtp.login(username, password)
            smtp.send_message(message)
        return True, "sent"
    except Exception as exc:
        return False, f"send_failed:{exc}"


def process_run(run_id: str) -> None:
    if not LEADS.exists():
        return
    sent = _load_sent()
    sent_whatsapp = _load_sent_whatsapp()
    with LEADS.open(encoding="utf-8") as f:
        leads = [r for r in csv.DictReader(f) if r.get("run_id") == run_id]
    send_enabled = os.getenv("SEND_EMAILS", "false").strip().lower() == "true"
    max_sends = int(os.getenv("MAX_EMAILS_PER_RUN", "1"))
    sends = 0
    daily_cap = int(os.getenv("MAX_OUTREACH_PER_DAY", "3"))
    daily_used = _daily_outreach_count()

    for lead in leads:
        name = lead.get("name", "").strip()
        target_url = lead.get("url", "").strip()
        social_context = _load_social_context(run_id, target_url)
        website = _find_company_website(name, lead.get("country", "China"), lead.get("sector", ""))
        email, source = _extract_emails(website)
        phone = extract_phone(website)
        base = {
            "run_id": run_id,
            "platform": lead.get("platform", ""),
            "slot": lead.get("slot", ""),
            "target_name": name,
            "target_url": target_url,
            "recipient_email": email,
            "subject": "",
            "body": "",
            "status": "no_public_business_email",
            "provider": "",
            "source": source,
            "whatsapp_phone": "",
            "whatsapp_status": "not_checked",
            "created_at": lead.get("created_at", ""),
        }
        base["whatsapp_phone"] = phone
        if not email and not phone:
            _save(base)
            continue
        if email in sent and not phone:
            base["status"] = "already_contacted"
            _save(base)
            continue
        generated, provider = generate_email(lead, website, social_context)
        if not generated:
            base["status"] = "ai_generation_failed"
            _save(base)
            continue
        base.update({"subject": generated["subject"], "body": generated["body"], "provider": provider, "status": "draft"})
        if phone in sent_whatsapp:
            base["whatsapp_status"] = "already_contacted"
        elif phone and daily_used < daily_cap:
            wa_ok, wa_status = send_whatsapp(phone, generated["body"])
            base["whatsapp_status"] = wa_status
            if wa_ok:
                sent_whatsapp.add(phone)
        else:
            base["whatsapp_status"] = "no_public_phone"
        if send_enabled and sends < max_sends and daily_used < daily_cap:
            ok, status = _send(email, generated["subject"], generated["body"])
            base["status"] = status
            if ok:
                sent.add(email)
                sends += 1
        if base.get("status") == "sent" or base.get("whatsapp_status") == "sent":
            daily_used += 1
        _save(base)

    print(f"OUTREACH COMPLETE | run_id={run_id} | email_send_enabled={send_enabled} | sent={sends} | max_per_run={max_sends}")
