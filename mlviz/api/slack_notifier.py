"""Slack notification service for critical alerts."""

import logging
import os
import time
import threading
from typing import Optional
import urllib.request
import json

logger = logging.getLogger(__name__)


class SlackNotifier:
    """Sends critical alert notifications to Slack via webhook (one post per request)."""
    
    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or os.getenv("SLACK_WEBHOOK_URL")
        self.enabled = bool(self.webhook_url)
        self.debounce_seconds = 20
        self.last_sent_ts = 0.0
        self._send_lock = threading.Lock()
        
        if not self.enabled:
            logger.warning("Slack notifications disabled: SLACK_WEBHOOK_URL not set")
        else:
            logger.info("Slack notifier initialized")
    
    def _format_metric_value(self, metric: str, value: float) -> str:
        """Format metric value for display."""
        if metric == "cpu_percent":
            return f"{value:.1f}%"
        elif metric == "ram_mb":
            return f"{value:.0f} MB"
        elif metric == "llc_miss_rate":
            return f"{value * 100:.1f}%"
        elif metric == "throughput":
            return f"{value:.0f} items/s"
        elif metric == "io_write_mb":
            return f"{value:.1f} MB"
        elif metric == "page_faults":
            return f"{value:.0f}"
        else:
            return f"{value:.2f}"
    
    def _build_blocks(
        self,
        model_id: str,
        metric: str,
        severity: str,
        threshold: float,
        observed_value: float,
        dashboard_url: str = "http://localhost:3000/alerts"
    ) -> list:
        """Build Slack Block Kit JSON for rich formatting."""
        
        severity_emoji = "🔴" if severity == "critical" else "⚠️"
        severity_text = severity.upper()
        
        metric_display = metric.replace("_", " ").title()
        threshold_str = self._format_metric_value(metric, threshold)
        observed_str = self._format_metric_value(metric, observed_value)
        
        return [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{severity_emoji} {severity_text} Alert: {model_id.upper()}",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Metric:*\n{metric_display}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Severity:*\n{severity_text}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Threshold:*\n`{threshold_str}`"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Current Value:*\n`{observed_str}`"
                    }
                ]
            },
            {
                "type": "divider"
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Model:* `{model_id}`\n*Time:* <!date^{int(time.time())}^{{time}}|{time.strftime('%H:%M:%S')}>"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "View Dashboard",
                            "emoji": True
                        },
                        "url": dashboard_url,
                        "style": "danger" if severity == "critical" else "primary"
                    }
                ]
            }
        ]
    
    def send_alert(
        self,
        model_id: str,
        metric: str,
        severity: str,
        threshold: float,
        observed_value: float,
        dashboard_url: str = "http://localhost:3000/alerts"
    ) -> tuple[bool, str]:
        """
        Send alert notification to Slack.
        
        Returns:
          - sent: bool
          - reason: one of "ok", "debounced", "webhook_not_configured", "slack_http_error", "slack_exception"
        """
        if not self.enabled:
            logger.debug("Slack notifications disabled, skipping")
            return False, "webhook_not_configured"
        
        try:
            with self._send_lock:
                now = time.time()
                cooldown_remaining = self.debounce_seconds - (now - self.last_sent_ts)
                if cooldown_remaining > 0:
                    logger.info(
                        "Slack notification debounced globally (%.1fs remaining): %s %s %s",
                        cooldown_remaining,
                        model_id,
                        metric,
                        severity,
                    )
                    return False, "debounced"

                blocks = self._build_blocks(
                    model_id=model_id,
                    metric=metric,
                    severity=severity,
                    threshold=threshold,
                    observed_value=observed_value,
                    dashboard_url=dashboard_url
                )
                
                payload = {
                    "blocks": blocks,
                    "text": f"{severity.upper()} Alert: {model_id} - {metric}"
                }
                
                req = urllib.request.Request(
                    self.webhook_url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                
                with urllib.request.urlopen(req, timeout=5) as response:
                    if response.status == 200:
                        self.last_sent_ts = now
                        logger.info(
                            "Slack notification sent (global cooldown %ss): %s %s %s",
                            self.debounce_seconds,
                            model_id,
                            metric,
                            severity,
                        )
                        return True, "ok"
                    else:
                        logger.error(f"Slack webhook returned status {response.status}")
                        return False, "slack_http_error"
                    
        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")
            return False, "slack_exception"


slack_notifier = SlackNotifier()
