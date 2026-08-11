"""
Beem Bulk SMS integration for Africa (Tanzania-based).

Uses the Beem SMS API (https://apisms.beem.africa/v1/send) to send
transactional SMS messages to tenants and guests.
"""
import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class BeemSMSClient:
    """Thin wrapper around the Beem SMS API."""

    def __init__(self):
        self.api_key = settings.BEEM_API_KEY
        self.secret_key = settings.BEEM_SECRET_KEY
        self.sender_name = settings.BEEM_SENDER_NAME
        self.api_url = settings.BEEM_API_URL

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _post(self, payload: dict) -> dict:
        """
        Low-level POST helper for the Beem API.

        Args:
            payload: JSON-serialisable request body.

        Returns:
            Parsed JSON response dict.

        Raises:
            requests.RequestException on network / HTTP error.
        """
        auth = (self.api_key, self.secret_key)
        headers = {"Content-Type": "application/json"}

        logger.info(
            "Beem POST to %s (sender=%s, %d recipient(s))",
            self.api_url,
            self.sender_name,
            len(payload.get("recipients", [])),
        )

        resp = requests.post(
            self.api_url,
            json=payload,
            auth=auth,
            headers=headers,
            timeout=15,
        )

        if not resp.ok:
            logger.error(
                "Beem API error %s: body=%s",
                resp.status_code,
                resp.text,
            )

        resp.raise_for_status()
        data = resp.json()
        logger.info("Beem response: %s", data)
        return data

    # ------------------------------------------------------------------
    # Single-SMS helper
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_phone(phone: str) -> str:
        """Strip +, spaces, dashes, parens – keep only digits."""
        import re
        # Remove anything non-digit
        digits = re.sub(r"\D", "", phone)
        # If starts with 0 (e.g. 0715...), replace leading 0 with 255
        if digits.startswith("0"):
            digits = "255" + digits[1:]
        # If starts with 7 (local format), prepend 255
        elif digits.startswith("7"):
            digits = "255" + digits
        return digits

    @staticmethod
    def _strip_unicode(text: str) -> str:
        """
        Normalise Unicode text to plain ASCII-safe GSM-7 characters.

        Uses unicodedata NFKD decomposition to split accented characters
        (e.g. ā → a, ǧ → g) and then drops combining marks.
        Also replaces common typographic/paste artifacts.
        """
        import unicodedata
        import re

        # 1. Replace common typographic characters first
        typo_map = {
            "\u201c": '"',   # left double quote
            "\u201d": '"',   # right double quote
            "\u2018": "'",   # left single quote
            "\u2019": "'",   # right single quote
            "\u2013": "-",   # en dash
            "\u2014": "--",  # em dash
            "\u2026": "...", # ellipsis
            "\u00a0": " ",   # non-breaking space
            "\ufeff": "",    # BOM
        }
        for old, new in typo_map.items():
            text = text.replace(old, new)

        # 2. NFKD decomposition splits accented chars into base + combining mark
        nfkd = unicodedata.normalize("NFKD", text)

        # 3. Strip all combining diacritical marks (category Mn, Mc, Me)
        ascii_approx = ""
        for ch in nfkd:
            cat = unicodedata.category(ch)
            if cat.startswith("M"):
                continue          # drop combining marks (accents, etc.)
            # Keep only printable ASCII
            if ord(ch) < 128:
                ascii_approx += ch
            else:
                # Replace any remaining non-ASCII with their closest match or ?
                ascii_approx += ch.encode("ascii", errors="replace").decode("ascii")

        # 4. Collapse multiple spaces
        ascii_approx = re.sub(r" +", " ", ascii_approx).strip()
        return ascii_approx

    def send_sms(self, phone_number: str, message: str) -> dict:
        """
        Send a single SMS via Beem.

        Args:
            phone_number: Recipient phone (e.g. +255712345678)
            message: SMS text content

        Returns:
            API response dict

        Raises:
            requests.RequestException on network error
        """
        if not self.api_key or not self.secret_key:
            logger.warning(
                "Beem SMS not configured – skipping SMS to %s", phone_number
            )
            return {"success": False, "reason": "Not configured"}

        # Normalise phone – Beem expects "255XXXXXXXXX" (no +, no spaces/dashes)
        raw_number = self._normalise_phone(phone_number)
        # Strip Unicode/accented chars to plain ASCII (Beem only accepts GSM-7)
        safe_message = self._strip_unicode(message)

        payload = {
            "source_addr": self.sender_name,
            "schedule_time": "",
            "encoding": "0",
            "message": safe_message,
            "recipients": [{"recipient_id": 1, "dest_addr": raw_number}],
        }

        try:
            return self._post(payload)
        except requests.RequestException as exc:
            logger.error("Beem SMS failed for %s: %s", phone_number, exc)
            raise

    # ------------------------------------------------------------------
    # Bulk-SMS helper
    # ------------------------------------------------------------------

    def send_bulk_sms(
        self,
        message: str,
        recipients: list[dict],
        schedule_time: str = "",
        encoding: str = "0",
    ) -> dict:
        """
        Send an SMS to multiple recipients in a single API call.

        Args:
            message: SMS text content.
            recipients: List of dicts, each with keys:
                - recipient_id (int) – unique per-recipient identifier
                - dest_addr   (str) – phone number without leading +
            schedule_time: ISO datetime string for scheduled send
                           (empty string = send immediately).
            encoding: "0" (GSM-7) or "1" (UCS-2 / Unicode).

        Returns:
            API response dict.

        Raises:
            requests.RequestException on network / HTTP error.

        Example::

            client.send_bulk_sms(
                message="Hello from the property manager!",
                recipients=[
                    {"recipient_id": 1, "dest_addr": "255700000001"},
                    {"recipient_id": 2, "dest_addr": "255700000002"},
                ],
            )
        """
        if not self.api_key or not self.secret_key:
            logger.warning("Beem SMS not configured – skipping bulk send")
            return {"success": False, "reason": "Not configured"}

        # Normalise every phone number
        cleaned = []
        for idx, r in enumerate(recipients, start=1):
            cleaned.append({
                "recipient_id": r.get("recipient_id", idx),
                "dest_addr": self._normalise_phone(r["dest_addr"]),
            })

        # Strip Unicode (Beem only accepts plain GSM-7)
        safe_message = self._strip_unicode(message)

        payload = {
            "source_addr": self.sender_name,
            "schedule_time": schedule_time,
            "encoding": "0",
            "message": safe_message,
            "recipients": cleaned,
        }

        logger.info(
            "Sending bulk SMS to %d recipient(s) via Beem",
            len(cleaned),
        )

        try:
            return self._post(payload)
        except requests.RequestException as exc:
            logger.error("Beem bulk SMS failed: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Convenience methods for common notifications
    # ------------------------------------------------------------------

    def notify_booking_confirmation(
        self, phone: str, guest_name: str, unit_name: str,
        check_in: str, check_out: str, total: str,
        currency: str = "TZS"
    ) -> dict:
        msg = (
            f"Dear {guest_name}, your booking for {unit_name} "
            f"({check_in} to {check_out}) is confirmed! "
            f"Total: {currency} {total}. Thank you."
        )
        return self.send_sms(phone, msg)

    def notify_booking_checked_in(
        self, phone: str, guest_name: str, unit_name: str
    ) -> dict:
        msg = (
            f"Welcome, {guest_name}! You have checked into {unit_name}. "
            f"Enjoy your stay. For assistance, contact the property manager."
        )
        return self.send_sms(phone, msg)

    def notify_booking_checked_out(
        self, phone: str, guest_name: str, unit_name: str
    ) -> dict:
        msg = (
            f"Thank you, {guest_name}, for staying at {unit_name}. "
            f"We hope you had a great stay! Please leave a review."
        )
        return self.send_sms(phone, msg)

    def notify_booking_cancelled(
        self, phone: str, guest_name: str, unit_name: str
    ) -> dict:
        msg = (
            f"Dear {guest_name}, your booking for {unit_name} "
            f"has been cancelled. Refund will be processed accordingly."
        )
        return self.send_sms(phone, msg)

    def notify_rent_reminder(
        self, phone: str, tenant_name: str,
        unit_name: str, amount: str, due_date: str,
        currency: str = "TZS"
    ) -> dict:
        msg = (
            f"Dear {tenant_name}, this is a reminder that your rent of "
            f"{currency} {amount} for {unit_name} is due on {due_date}. "
            f"Please make payment to avoid late charges. Thank you."
        )
        return self.send_sms(phone, msg)

    def notify_payment_received(
        self, phone: str, name: str, amount: str,
        payment_type: str, unit_name: str,
        currency: str = "TZS"
    ) -> dict:
        msg = (
            f"Dear {name}, we have received your {payment_type} payment of "
            f"{currency} {amount} for {unit_name}. Thank you for your prompt payment!"
        )
        return self.send_sms(phone, msg)

    def notify_lease_renewal(
        self, phone: str, tenant_name: str,
        unit_name: str, new_end_date: str
    ) -> dict:
        msg = (
            f"Dear {tenant_name}, your lease for {unit_name} "
            f"has been renewed until {new_end_date}. "
            f"Please contact us if you have any questions."
        )
        return self.send_sms(phone, msg)

    def notify_lease_expiry_reminder(
        self, phone: str, tenant_name: str,
        unit_name: str, end_date: str, days_left: int,
    ) -> dict:
        """
        Send an SMS alert that the tenant's lease is about to expire.
        """
        if days_left <= 0:
            msg = (
                f"Dear {tenant_name}, your lease for {unit_name} "
                f"has expired as of {end_date}. Please contact us "
                f"to discuss renewal or vacating. Thank you."
            )
        else:
            msg = (
                f"Dear {tenant_name}, your lease for {unit_name} "
                f"will expire in {days_left} day(s) on {end_date}. "
                f"Please contact us to discuss renewal options."
            )
        return self.send_sms(phone, msg)


# Singleton for convenience
beem_client = BeemSMSClient()
