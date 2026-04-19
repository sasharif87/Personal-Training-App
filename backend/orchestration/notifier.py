# backend/orchestration/notifier.py
"""
Notification layer — pushes alerts to athlete via multiple channels.

Channels:
  1. ntfy.sh   — self-hosted push notifications (primary)
  2. Email     — via Postfix/SMTP relay (optional)
  3. Log file  — always on

Notification types:
  - Morning readout (daily 3am result)
  - Weekly summary digest
  - NFOR alert
  - Gear replacement alert
  - Pipeline failure alert
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(
        self,
        ntfy_url: Optional[str] = None,
        ntfy_topic: Optional[str] = None,
        ntfy_token: Optional[str] = None,
        smtp_host: Optional[str] = None,
        smtp_to: Optional[str] = None,
    ):
        self.ntfy_url = ntfy_url or os.environ.get("NTFY_URL", "https://ntfy.sh")
        self.ntfy_topic = ntfy_topic or os.environ.get("NTFY_TOPIC", "training-coach")
        self.ntfy_token = ntfy_token or os.environ.get("NTFY_TOKEN", "")
        self.smtp_host = smtp_host or os.environ.get("SMTP_HOST")
        self.smtp_to = smtp_to or os.environ.get("NOTIFICATION_EMAIL")

        # Warn if using default or obviously-placeholder topic on public ntfy
        if "ntfy.sh" in self.ntfy_url and self.ntfy_topic in (
            "training-coach", "coach-CHANGEME-use-random-topic",
        ):
            logger.warning(
                "ntfy topic '%s' is a well-known default on public ntfy.sh — "
                "anyone can subscribe. Set NTFY_TOPIC to a random value.",
                self.ntfy_topic,
            )

    # -----------------------------------------------------------------------
    # Send via ntfy.sh
    # -----------------------------------------------------------------------
    def send_ntfy(
        self,
        title: str,
        message: str,
        priority: int = 3,
        tags: Optional[List[str]] = None,
    ) -> bool:
        """
        Send a push notification via ntfy.sh.
        Priority: 1=min, 3=default, 5=urgent
        """
        url = f"{self.ntfy_url}/{self.ntfy_topic}"
        import base64
        b64_title = base64.b64encode(title.encode("utf-8")).decode("ascii")
        rfc2047_title = f"=?utf-8?B?{b64_title}?="

        headers = {
            "Title": rfc2047_title,
            "Priority": str(priority),
        }
        if self.ntfy_token:
            headers["Authorization"] = f"Bearer {self.ntfy_token}"
        if tags:
            headers["Tags"] = ",".join(tags)

        try:
            resp = requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=10)
            resp.raise_for_status()
            logger.info("ntfy notification sent: %s", title)
            return True
        except requests.RequestException as exc:
            logger.error("ntfy send failed: %s", exc)
            return False

    # -----------------------------------------------------------------------
    # Send via email (SMTP)
    # -----------------------------------------------------------------------
    def send_email(self, subject: str, body: str) -> bool:
        """Send email notification via SMTP."""
        if not self.smtp_host or not self.smtp_to:
            logger.debug("SMTP not configured — skipping email")
            return False

        try:
            import smtplib
            from email.mime.text import MIMEText

            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = os.environ.get("SMTP_FROM", "coach@localhost")
            msg["To"] = self.smtp_to

            port = int(os.environ.get("SMTP_PORT", "587"))
            with smtplib.SMTP(self.smtp_host, port) as smtp:
                smtp.ehlo()
                if port != 25:
                    smtp.starttls()
                    smtp.ehlo()
                # Authenticate if credentials provided
                smtp_user = os.environ.get("SMTP_USER")
                smtp_pass = os.environ.get("SMTP_PASS")
                if smtp_user and smtp_pass:
                    smtp.login(smtp_user, smtp_pass)
                smtp.send_message(msg)

            logger.info("Email sent: %s → %s", subject, self.smtp_to)
            return True
        except Exception as exc:
            logger.error("Email send failed: %s", exc)
            return False

    # -----------------------------------------------------------------------
    # High-level notification methods
    # -----------------------------------------------------------------------
    def morning_readout(self, readout: Dict[str, Any]) -> None:
        """Send the daily morning readout summary."""
        conflict = readout.get("conflict_level", "clear")
        recommendation = readout.get("recommendation", "primary")
        summary = readout.get("signal_summary", "")

        emoji = {"clear": "🟢", "mild": "🟡", "significant": "🟠", "high": "🔴"}.get(conflict, "⚪")
        title = f"{emoji} Morning Readout — {recommendation.upper()}"

        message = f"{summary}\n\nRecommendation: {recommendation}"

        # Add gear alerts if present
        gear_alerts = readout.get("gear_alerts", [])
        if gear_alerts:
            message += "\n\n📦 Gear:\n" + "\n".join(gear_alerts)

        priority = 4 if conflict in ("significant", "high") else 3
        self.send_ntfy(title, message, priority=priority, tags=["runner", "coach"])

    def nfor_alert(self, alert: Dict[str, Any]) -> None:
        """Send an NFOR (overreaching) alert."""
        severity = alert.get("severity", "warning")
        response = alert.get("recommended_response", "")

        self.send_ntfy(
            title=f"⚠️ NFOR {severity.upper()} Alert",
            message=response,
            priority=5,
            tags=["warning", "coach"],
        )
        self.send_email(
            subject=f"NFOR {severity} Alert — Recovery Recommended",
            body=f"NFOR Alert:\n\n{response}\n\nSignals: {alert.get('signals_triggered', [])}",
        )

    def pipeline_failure(self, pipeline_name: str, error: str) -> None:
        """Alert on pipeline failure."""
        self.send_ntfy(
            title=f"🔴 Pipeline Failed: {pipeline_name}",
            message=f"Error: {error}",
            priority=5,
            tags=["warning", "x"],
        )

    def weekly_summary(self, summary: Dict[str, Any]) -> None:
        """Send the weekly training summary digest."""
        sessions = summary.get("sessions_completed", 0)
        missed = summary.get("sessions_missed", 0)
        tss_ratio = summary.get("week_tss_ratio", 0)

        message = (
            f"Sessions: {sessions} completed, {missed} missed\n"
            f"TSS execution: {tss_ratio:.0%}\n"
            f"Total TSS: {summary.get('total_actual_tss', 0):.0f}\n"
        )

        # Add flag summary
        flags = summary.get("flag_summary", {})
        if flags:
            message += f"Flags: {', '.join(f'{k}({v})' for k, v in flags.items())}\n"

        self.send_ntfy(
            title="📊 Weekly Training Summary",
            message=message,
            priority=3,
            tags=["chart_with_upwards_trend", "coach"],
        )

    def gear_alert(self, alerts: List[Dict]) -> None:
        """Send gear replacement alerts."""
        if not alerts:
            return
        message = "\n".join(a.get("message", "") for a in alerts)
        self.send_ntfy(
            title="👟 Gear Alert",
            message=message,
            priority=3,
            tags=["running_shoe"],
        )
