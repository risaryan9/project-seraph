"""Slack notification service for critical alerts."""

import logging
import os
import time
import threading
from typing import List, Optional
import urllib.request
import json

logger = logging.getLogger(__name__)


class SlackNotifier:
    """Sends critical alert notifications to Slack via webhook (one post per request)."""
    
    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or os.getenv("SLACK_WEBHOOK_URL")
        self.enabled = bool(self.webhook_url)
        self.optimizer_webhook_url = os.getenv("SLACK_OPTIMIZER_WEBHOOK_URL", "").strip() or None
        self.debounce_seconds = 20
        self.last_sent_ts = 0.0
        self._send_lock = threading.Lock()
        
        if not self.enabled:
            logger.warning("Slack notifications disabled: SLACK_WEBHOOK_URL not set")
        else:
            logger.info("Slack notifier initialized")
        if self.optimizer_webhook_url:
            logger.info("Slack optimizer webhook configured (SLACK_OPTIMIZER_WEBHOOK_URL)")
    
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
    
    @staticmethod
    def _escape_mrkdwn(text: str) -> str:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
    
    def _optimizer_severity_emoji(self, severity: str) -> str:
        return {
            "critical": "🔴",
            "high": "🟠",
            "medium": "🟡",
            "low": "🟢",
        }.get(severity.lower(), "⚪")
    
    def _build_optimizer_blocks(
        self,
        severity: str,
        issue_headline: str,
        root_cause_analysis: str,
        fix_titles: List[str],
        analysis_id: str,
        model_version: str,
        latency_ms: int,
        dashboard_url: str,
    ) -> list:
        emoji = self._optimizer_severity_emoji(severity)
        sev = severity.upper()
        headline = self._escape_mrkdwn(issue_headline.strip())[:500]
        root = self._escape_mrkdwn(root_cause_analysis.strip())
        if len(root) > 2400:
            root = root[:2399] + "…"
        fix_lines = []
        for i, title in enumerate(fix_titles[:6]):
            t = self._escape_mrkdwn(title.strip())[:200]
            fix_lines.append(f"{i + 1}. {t}")
        fixes_text = "\n".join(fix_lines) if fix_lines else "_No remediation cards_"
        return [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} Seraph Optimizer — analysis complete",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Severity*\n{sev}"},
                    {"type": "mrkdwn", "text": f"*Latency*\n{latency_ms} ms"},
                    {"type": "mrkdwn", "text": f"*Model*\n`{self._escape_mrkdwn(model_version)}`"},
                    {"type": "mrkdwn", "text": f"*Analysis ID*\n`{self._escape_mrkdwn(analysis_id)}`"},
                ],
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Issue*\n{headline}",
                },
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Root cause*\n{root}"},
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Recommended fixes*\n{fixes_text}"},
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"_Completed {time.strftime('%Y-%m-%d %H:%M:%S')} UTC_",
                    }
                ],
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Open Alerts & Optimizer",
                            "emoji": True,
                        },
                        "url": dashboard_url,
                        "style": "primary",
                    }
                ],
            },
        ]
    
    def send_optimizer_analysis_complete(
        self,
        severity: str,
        issue_headline: str,
        root_cause_analysis: str,
        recommended_fix_titles: List[str],
        analysis_id: str,
        model_version: str,
        latency_ms: int,
        dashboard_url: str = "http://localhost:3000/alerts",
    ) -> tuple[bool, str]:
        """
        Post successful optimizer analysis to SLACK_OPTIMIZER_WEBHOOK_URL.
        Does not use the alert debounce.
        """
        if not self.optimizer_webhook_url:
            logger.debug("Slack optimizer webhook not set, skipping")
            return False, "webhook_not_configured"
        try:
            blocks = self._build_optimizer_blocks(
                severity=severity,
                issue_headline=issue_headline,
                root_cause_analysis=root_cause_analysis,
                fix_titles=recommended_fix_titles,
                analysis_id=analysis_id,
                model_version=model_version,
                latency_ms=latency_ms,
                dashboard_url=dashboard_url,
            )
            plain = f"[{severity.upper()}] {issue_headline[:200]}"
            payload = {"blocks": blocks, "text": plain}
            req = urllib.request.Request(
                self.optimizer_webhook_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    logger.info("Slack optimizer notification sent (%s)", analysis_id)
                    return True, "ok"
                logger.error("Slack optimizer webhook returned status %s", response.status)
                return False, "slack_http_error"
        except Exception as e:
            logger.error("Slack optimizer notification failed: %s", e)
            return False, "slack_exception"
    
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
