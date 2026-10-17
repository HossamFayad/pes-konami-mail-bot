import requests
import secrets
import string
import re
import time
from typing import Optional, Dict, Any, List

BASE_URL = "https://api.mail.tm"

# Persistent session with HTTP keep-alive for sub-second speeds
_session = requests.Session()
_cached_domains = ["maxxspace.com"]
_last_domains_fetch = 0

class MailService:
    @staticmethod
    def get_domains() -> List[str]:
        global _cached_domains, _last_domains_fetch
        # Refresh cache only once every 30 minutes
        if time.time() - _last_domains_fetch > 1800 or not _cached_domains:
            try:
                resp = _session.get(f"{BASE_URL}/domains", timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    domains = [d["domain"] for d in data.get("hydra:member", []) if d.get("isActive")]
                    if domains:
                        _cached_domains = domains
                        _last_domains_fetch = time.time()
            except Exception as e:
                print(f"[MailService] Error fetching domains: {e}")
        return _cached_domains

    @staticmethod
    def create_account(prefix: str = "pes") -> Optional[Dict[str, str]]:
        domains = MailService.get_domains()
        domain = domains[0] if domains else "maxxspace.com"
        
        # Generate clean, believable username
        random_chars = ''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(7))
        email = f"{prefix}_{random_chars}@{domain}"
        
        # Secure password that meets common Konami & mail standards
        raw_pwd = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(10))
        password = f"{raw_pwd}!9"
        
        payload = {
            "address": email,
            "password": password
        }
        
        try:
            # Reusing session connection makes this execute in ~0.5s total
            resp = _session.post(f"{BASE_URL}/accounts", json=payload, timeout=6)
            if resp.status_code in [200, 201]:
                account_data = resp.json()
                account_id = account_data.get("id")
                
                # Fetch authentication JWT token
                token_resp = _session.post(f"{BASE_URL}/token", json=payload, timeout=6)
                if token_resp.status_code == 200:
                    token = token_resp.json().get("token")
                    return {
                        "email": email,
                        "password": password,
                        "account_id": account_id,
                        "token": token
                    }
        except Exception as e:
            print(f"[MailService] Error creating account: {e}")
        return None

    @staticmethod
    def get_messages(token: str) -> List[Dict[str, Any]]:
        headers = {"Authorization": f"Bearer {token}"}
        try:
            resp = _session.get(f"{BASE_URL}/messages", headers=headers, timeout=5)
            if resp.status_code == 200:
                return resp.json().get("hydra:member", [])
        except Exception as e:
            print(f"[MailService] Error fetching messages: {e}")
        return []

    @staticmethod
    def get_message_detail(token: str, message_id: str) -> Optional[Dict[str, Any]]:
        headers = {"Authorization": f"Bearer {token}"}
        try:
            resp = _session.get(f"{BASE_URL}/messages/{message_id}", headers=headers, timeout=5)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            print(f"[MailService] Error fetching message detail: {e}")
        return None

    @staticmethod
    def extract_otp(subject: str, text_content: str, html_content: str = "") -> Optional[str]:
        full_text = f"{subject}\n{text_content}\n{html_content}"
        matches = re.findall(r'\b\d{6}\b', full_text)
        if matches:
            for code in matches:
                return code
        return None

    @staticmethod
    def extract_verification_url(text_content: str, html_content: str = "") -> Optional[str]:
        full_text = f"{text_content}\n{html_content}"
        matches = re.findall(r'https?://[^\s<>"]+(?:konami|confirm|verify)[^\s<>"]*', full_text, re.IGNORECASE)
        if matches:
            return matches[0]
        return None
