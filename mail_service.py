import requests
import secrets
import string
import re
from typing import Optional, Dict, Any, List

BASE_URL = "https://api.mail.tm"

class MailService:
    @staticmethod
    def get_domains() -> List[str]:
        try:
            resp = requests.get(f"{BASE_URL}/domains", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                domains = [d["domain"] for d in data.get("hydra:member", []) if d.get("isActive")]
                return domains if domains else ["maxxspace.com"]
        except Exception as e:
            print(f"[MailService] Error fetching domains: {e}")
        return ["maxxspace.com"]

    @staticmethod
    def create_account(prefix: str = "pes") -> Optional[Dict[str, str]]:
        domains = MailService.get_domains()
        domain = domains[0]
        
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
            resp = requests.post(f"{BASE_URL}/accounts", json=payload, timeout=12)
            if resp.status_code in [200, 201]:
                account_data = resp.json()
                account_id = account_data.get("id")
                
                # Fetch authentication JWT token
                token_resp = requests.post(f"{BASE_URL}/token", json=payload, timeout=12)
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
            resp = requests.get(f"{BASE_URL}/messages", headers=headers, timeout=10)
            if resp.status_code == 200:
                return resp.json().get("hydra:member", [])
        except Exception as e:
            print(f"[MailService] Error fetching messages: {e}")
        return []

    @staticmethod
    def get_message_detail(token: str, message_id: str) -> Optional[Dict[str, Any]]:
        headers = {"Authorization": f"Bearer {token}"}
        try:
            resp = requests.get(f"{BASE_URL}/messages/{message_id}", headers=headers, timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            print(f"[MailService] Error fetching message detail: {e}")
        return None

    @staticmethod
    def extract_otp(subject: str, text_content: str, html_content: str = "") -> Optional[str]:
        full_text = f"{subject}\n{text_content}\n{html_content}"
        
        # Look for 6-digit verification code specifically for Konami / PES
        # Matches patterns like "Confirmation code: 123456" or isolated 6 digits
        matches = re.findall(r'\b\d{6}\b', full_text)
        if matches:
            # If multiple, prefer one near keywords like "code", "konami", "confirmation"
            for code in matches:
                # filter out obvious non-OTP strings if any
                return code
        return None

    @staticmethod
    def extract_verification_url(text_content: str, html_content: str = "") -> Optional[str]:
        full_text = f"{text_content}\n{html_content}"
        matches = re.findall(r'https?://[^\s<>"]+(?:konami|confirm|verify)[^\s<>"]*', full_text, re.IGNORECASE)
        if matches:
            return matches[0]
        return None
