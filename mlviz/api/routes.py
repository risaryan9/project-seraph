"""API routes for metrics endpoints."""

import json
import logging
import os
import time
import uuid
from typing import List, Optional
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .influx import influx_helper
from .slack_notifier import slack_notifier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["metrics"])


class AlertNotification(BaseModel):
    """Alert notification payload for Slack."""
    model_id: str
    metric: str
    severity: str
    threshold: float
    observed_value: float
    timestamp: float


class AlertSummary(BaseModel):
    """Summary of an active alert for optimizer analysis."""
    model_id: str
    metric: str
    severity: str
    observed_value: float


class OptimizerAnalysisRequest(BaseModel):
    """Request payload for optimizer analysis."""
    active_alerts: List[AlertSummary] = Field(default_factory=list)
    time_window_ms: Optional[int] = None
    operator_note: Optional[str] = None


class OptimizerFixCommand(BaseModel):
    """Remediation command recommendation."""
    id: str
    title: str
    description: str
    command: str
    risk_level: Optional[str] = None
    estimated_impact: Optional[str] = None


class OptimizerAnalysisResponse(BaseModel):
    """Response payload for optimizer analysis."""
    severity: str
    issue_headline: str
    root_cause_analysis: str
    recommended_fixes: List[OptimizerFixCommand]
    analysis_id: Optional[str] = None
    model_version: Optional[str] = None
    latency_ms: Optional[int] = None


@router.get("/metrics/raw")
async def get_raw_metrics(
    start_relative: Optional[str] = Query(
        default="-1h",
        description="Relative time range (e.g., '-5m', '-1h', '-24h')"
    ),
    start: Optional[str] = Query(
        default=None,
        description="Absolute start time (ISO8601 or Unix ms)"
    ),
    end: Optional[str] = Query(
        default=None,
        description="Absolute end time (ISO8601 or Unix ms)"
    ),
    model_id: Optional[str] = Query(
        default=None,
        description="Filter by model_id (e.g., 'resnet18-train')"
    ),
    phase: Optional[str] = Query(
        default=None,
        description="Filter by phase (e.g., 'forward', 'backward')"
    ),
    fields: Optional[str] = Query(
        default=None,
        description="Comma-separated field names (e.g., 'cpu_percent,ram_mb')"
    ),
    limit: int = Query(
        default=1000,
        ge=1,
        le=10000,
        description="Maximum number of points to return"
    )
):
    """
    Get raw time-series metrics from InfluxDB.
    
    Returns a list of metric records with timestamp, tags, field name, and value.
    """
    try:
        field_list = None
        if fields:
            field_list = [f.strip() for f in fields.split(",")]
        
        results = influx_helper.query_raw(
            start_relative=start_relative if not start else None,
            start=start,
            end=end,
            model_id=model_id,
            phase=phase,
            fields=field_list,
            limit=limit
        )
        
        return {
            "count": len(results),
            "data": results
        }
    
    except Exception as e:
        logger.error(f"Failed to query raw metrics: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"InfluxDB query failed: {str(e)}"
        )


@router.get("/metrics/aggregate")
async def get_aggregate_metrics(
    window: str = Query(
        default="1m",
        description="Window duration (e.g., '30s', '1m', '5m')"
    ),
    aggregation: str = Query(
        default="mean",
        regex="^(mean|max|min)$",
        description="Aggregation function: mean, max, or min"
    ),
    start_relative: Optional[str] = Query(
        default="-1h",
        description="Relative time range (e.g., '-5m', '-1h', '-24h')"
    ),
    start: Optional[str] = Query(
        default=None,
        description="Absolute start time (ISO8601 or Unix ms)"
    ),
    end: Optional[str] = Query(
        default=None,
        description="Absolute end time (ISO8601 or Unix ms)"
    ),
    model_id: Optional[str] = Query(
        default=None,
        description="Filter by model_id"
    ),
    phase: Optional[str] = Query(
        default=None,
        description="Filter by phase"
    ),
    fields: Optional[str] = Query(
        default=None,
        description="Comma-separated field names"
    ),
    limit: int = Query(
        default=500,
        ge=1,
        le=5000,
        description="Maximum number of aggregated points"
    )
):
    """
    Get aggregated time-series metrics with windowing.
    
    Applies aggregation function (mean, max, min) over specified time windows.
    """
    try:
        field_list = None
        if fields:
            field_list = [f.strip() for f in fields.split(",")]
        
        results = influx_helper.query_aggregate(
            window=window,
            aggregation=aggregation,
            start_relative=start_relative if not start else None,
            start=start,
            end=end,
            model_id=model_id,
            phase=phase,
            fields=field_list,
            limit=limit
        )
        
        return {
            "count": len(results),
            "window": window,
            "aggregation": aggregation,
            "data": results
        }
    
    except Exception as e:
        logger.error(f"Failed to query aggregate metrics: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"InfluxDB query failed: {str(e)}"
        )


@router.get("/models")
async def get_models(
    start_relative: str = Query(
        default="-24h",
        description="Time range for model discovery"
    ),
    start: Optional[str] = Query(
        default=None,
        description="Absolute start time"
    ),
    end: Optional[str] = Query(
        default=None,
        description="Absolute end time"
    )
):
    """
    Get list of distinct model_id values in the metrics bucket.
    
    Useful for discovering which models have reported metrics.
    """
    try:
        models = influx_helper.query_distinct_models(
            start_relative=start_relative if not start else None,
            start=start,
            end=end
        )
        
        return {
            "count": len(models),
            "models": models
        }
    
    except Exception as e:
        logger.error(f"Failed to query models: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"InfluxDB query failed: {str(e)}"
        )


@router.get("/phases")
async def get_phases(
    model_id: Optional[str] = Query(
        default=None,
        description="Filter phases by model_id"
    ),
    start_relative: str = Query(
        default="-24h",
        description="Time range for phase discovery"
    ),
    start: Optional[str] = Query(
        default=None,
        description="Absolute start time"
    ),
    end: Optional[str] = Query(
        default=None,
        description="Absolute end time"
    )
):
    """
    Get list of distinct phase values.
    
    Optionally filter by model_id to see phases for a specific model.
    """
    try:
        phases = influx_helper.query_distinct_phases(
            model_id=model_id,
            start_relative=start_relative if not start else None,
            start=start,
            end=end
        )
        
        return {
            "count": len(phases),
            "model_id": model_id,
            "phases": phases
        }
    
    except Exception as e:
        logger.error(f"Failed to query phases: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"InfluxDB query failed: {str(e)}"
        )


@router.get("/metrics/count")
async def get_metrics_count(
    start_relative: Optional[str] = Query(
        default="-24h",
        description="Time range for count (e.g. '-1h', '-24h')"
    )
):
    """
    Get total count of metric records in InfluxDB for the time range.
    Used by the dashboard for 'Samples Collected' (poll every 5-10s).
    """
    try:
        count = influx_helper.query_total_count(start_relative=start_relative)
        return {"count": count}
    except Exception as e:
        logger.error(f"Failed to get metrics count: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"InfluxDB query failed: {str(e)}"
        )


@router.get("/metrics/recent")
async def get_recent_samples(
    start_relative: Optional[str] = Query(
        default="-2m",
        description="Time range (e.g. '-1m', '-2m')"
    ),
    limit: int = Query(default=2000, ge=100, le=5000, description="Max raw records (≈samples*14)")
):
    """
    Get recent metric samples in dashboard format (one object per sample with all fields).
    Used for polling-based chart updates when WebSocket is not enough.
    """
    try:
        samples = influx_helper.query_recent_samples(
            start_relative=start_relative,
            limit=limit
        )
        return {"count": len(samples), "data": samples}
    except Exception as e:
        logger.error(f"Failed to get recent samples: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"InfluxDB query failed: {str(e)}"
        )


@router.get("/metrics/fields")
async def get_fields():
    """
    Get list of available metric field names.
    
    Returns the standard set of hardware metrics tracked by Seraph.
    """
    return {
        "count": len(influx_helper.METRIC_FIELDS),
        "fields": influx_helper.METRIC_FIELDS
    }


@router.post("/alerts/notify")
async def notify_alert(alert: AlertNotification):
    """
    Send critical alert notification to Slack.
    
    Only processes critical alerts. Each request posts to the webhook (no server-side debounce).
    """
    if alert.severity != "critical":
        return {
            "sent": False,
            "reason": "Only critical alerts trigger Slack notifications",
            "channel": "#ml-ops-alerts"
        }
    
    try:
        sent, reason = slack_notifier.send_alert(
            model_id=alert.model_id,
            metric=alert.metric,
            severity=alert.severity,
            threshold=alert.threshold,
            observed_value=alert.observed_value,
            dashboard_url="http://localhost:3000/alerts"
        )
        
        return {
            "sent": sent,
            "reason": reason,
            "channel": "#ml-ops-alerts",
            "timestamp": alert.timestamp,
            "debounced": reason == "debounced",
            "integration_type": "incoming_webhook"
        }
    
    except Exception as e:
        logger.error(f"Failed to send Slack notification: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Slack notification failed: {str(e)}"
        )


@router.post("/optimizer/analysis")
async def analyze_optimizer(request: OptimizerAnalysisRequest) -> OptimizerAnalysisResponse:
    """
    Run AI-powered optimizer analysis on current system state.
    
    This endpoint serves as a proxy/placeholder for future integration with
    external AI analysis services (e.g., Gemini, Claude). Currently returns
    deterministic analysis based on active alerts.
    
    Returns structured recommendations with severity assessment, root cause
    analysis, and remediation commands.
    """
    def _fallback_response(elapsed_ms: int, reason: str) -> OptimizerAnalysisResponse:
        critical_alerts = [a for a in request.active_alerts if a.severity == "critical"]
        has_critical = len(critical_alerts) > 0
        if has_critical:
            top_alert = critical_alerts[0]
            return OptimizerAnalysisResponse(
                severity="critical",
                issue_headline=f"Critical {top_alert.metric.upper()} threshold breach detected on {top_alert.model_id}",
                root_cause_analysis=(
                    f"Fallback analysis path engaged due to Gemini unavailability ({reason}). "
                    f"Observed critical {top_alert.metric} on {top_alert.model_id} at "
                    f"value={top_alert.observed_value:.3f}. "
                    "Treat this as advisory triage output and validate against live telemetry."
                ),
                recommended_fixes=[
                    OptimizerFixCommand(
                        id="fix-01",
                        title="Throttle Worker Concurrency",
                        description="Reduce concurrency to lower contention and cache pressure.",
                        command=f"docker exec mlviz-{top_alert.model_id} /bin/sh -lc \"export OMP_NUM_THREADS=4\"",
                        risk_level="low",
                        estimated_impact="10-25% CPU/LLC pressure reduction",
                    ),
                    OptimizerFixCommand(
                        id="fix-02",
                        title="Rebalance CPU Affinity",
                        description="Pin workload to dedicated cores for reduced scheduler contention.",
                        command=f"taskset -cp 0-3 $(docker inspect --format '{{{{.State.Pid}}}}' mlviz-{top_alert.model_id})",
                        risk_level="medium",
                        estimated_impact="5-15% tail latency improvement",
                    ),
                ],
                analysis_id=f"analysis-fallback-{uuid.uuid4().hex[:12]}",
                model_version="gemini-flash-latest-fallback",
                latency_ms=elapsed_ms,
            )

        return OptimizerAnalysisResponse(
            severity="low",
            issue_headline="No critical issue detected from current alert summary",
            root_cause_analysis=(
                f"Fallback analysis path engaged due to Gemini unavailability ({reason}). "
                "No critical alerts were provided. Continue monitoring and trigger re-analysis "
                "on any sustained anomaly."
            ),
            recommended_fixes=[
                OptimizerFixCommand(
                    id="fix-01",
                    title="Re-run Optimizer",
                    description="Collect additional telemetry and re-run analysis.",
                    command="curl -X POST http://localhost:8000/api/optimizer/analysis -H 'Content-Type: application/json' -d '{}'",
                    risk_level="low",
                    estimated_impact="Improved diagnostic confidence",
                )
            ],
            analysis_id=f"analysis-fallback-{uuid.uuid4().hex[:12]}",
            model_version="gemini-flash-latest-fallback",
            latency_ms=elapsed_ms,
        )

    try:
        start_time = time.time()
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            elapsed_ms = int((time.time() - start_time) * 1000)
            return _fallback_response(elapsed_ms, "missing GEMINI_API_KEY")

        # Summarized + raw metric snippets for strict SRE prompting.
        recent_samples = influx_helper.query_recent_samples(start_relative="-2m", limit=2000)
        model_metrics = {}
        for sample in recent_samples:
            model_id = sample.get("model_id", "unknown")
            model_metrics.setdefault(model_id, []).append(sample)

        summarized_metrics = []
        for model_id, samples in list(model_metrics.items())[:5]:
            if not samples:
                continue
            cpu_avg = sum(float(s.get("cpu_percent", 0.0)) for s in samples) / len(samples)
            ram_avg = sum(float(s.get("ram_mb", 0.0)) for s in samples) / len(samples)
            llc_avg = sum(float(s.get("llc_miss_rate", 0.0)) for s in samples) / len(samples)
            thr_avg = sum(float(s.get("throughput", 0.0)) for s in samples) / len(samples)
            summarized_metrics.append(
                {
                    "model_id": model_id,
                    "samples": len(samples),
                    "cpu_percent_avg": round(cpu_avg, 3),
                    "ram_mb_avg": round(ram_avg, 3),
                    "llc_miss_rate_avg": round(llc_avg, 4),
                    "throughput_avg": round(thr_avg, 3),
                }
            )

        raw_snippets = recent_samples[-12:] if len(recent_samples) > 12 else recent_samples

        prompt_payload = {
            "active_alerts": [a.model_dump() for a in request.active_alerts],
            "time_window_ms": request.time_window_ms,
            "operator_note": request.operator_note,
            "metrics_summary": summarized_metrics,
            "metrics_raw_snippets": raw_snippets,
            "policy": {
                "tone": "strict SRE",
                "commands": "advisory only",
                "severity_allowed": ["critical", "high", "medium", "low"],
            },
            "response_schema": {
                "severity": "critical|high|medium|low",
                "issue_headline": "string",
                "root_cause_analysis": "2-3 dense paragraphs",
                "recommended_fixes": [
                    {
                        "id": "fix-01",
                        "title": "string",
                        "description": "string",
                        "command": "string",
                        "risk_level": "low|medium|high",
                        "estimated_impact": "string",
                    }
                ],
            },
        }

        system_instruction = (
            "You are a strict SRE optimizer engine. Return ONLY valid JSON with keys: "
            "severity, issue_headline, root_cause_analysis, recommended_fixes. "
            "Keep commands advisory-only (do not claim execution happened). "
            "Use concrete technical language tied to provided metrics."
        )

        user_instruction = (
            "Analyze this telemetry payload and produce remediation advice.\n"
            f"{json.dumps(prompt_payload, separators=(',', ':'))}"
        )

        gemini_url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-flash-latest:generateContent"
        )
        req_body = {
            "contents": [{"parts": [{"text": f"{system_instruction}\n\n{user_instruction}"}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }

        http_req = Request(
            gemini_url,
            data=json.dumps(req_body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-goog-api-key": api_key,
            },
            method="POST",
        )
        with urlopen(http_req, timeout=20) as resp:
            gemini_raw = resp.read().decode("utf-8")
        gemini_json = json.loads(gemini_raw)
        text_out = (
            gemini_json.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )
        if not text_out:
            raise ValueError("Gemini returned empty response text")

        parsed = json.loads(text_out)
        fixes = [
            OptimizerFixCommand(
                id=str(fx.get("id", f"fix-{idx+1:02d}")),
                title=str(fx.get("title", "Untitled Fix")),
                description=str(fx.get("description", "No description provided")),
                command=str(fx.get("command", "# advisory command unavailable")),
                risk_level=str(fx.get("risk_level", "medium")).lower(),
                estimated_impact=str(fx.get("estimated_impact", "")) or None,
            )
            for idx, fx in enumerate(parsed.get("recommended_fixes", []))
        ]
        if not fixes:
            fixes = [
                OptimizerFixCommand(
                    id="fix-01",
                    title="No remediations returned",
                    description="Gemini returned no command cards; re-run analysis with larger window.",
                    command="curl -X POST http://localhost:8000/api/optimizer/analysis -H 'Content-Type: application/json' -d '{}'",
                    risk_level="low",
                    estimated_impact="Improves diagnostic completeness",
                )
            ]

        elapsed_ms = int((time.time() - start_time) * 1000)
        severity = str(parsed.get("severity", "medium")).lower()
        if severity not in {"critical", "high", "medium", "low"}:
            severity = "medium"

        return OptimizerAnalysisResponse(
            severity=severity,
            issue_headline=str(parsed.get("issue_headline", "Optimizer analysis completed")),
            root_cause_analysis=str(
                parsed.get(
                    "root_cause_analysis",
                    "No detailed diagnosis returned from Gemini. Re-run with additional telemetry.",
                )
            ),
            recommended_fixes=fixes,
            analysis_id=f"analysis-{uuid.uuid4().hex[:12]}",
            model_version="gemini-flash-latest",
            latency_ms=elapsed_ms,
        )

    except (HTTPError, URLError) as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.error(f"Gemini transport error: {e}")
        return _fallback_response(elapsed_ms, f"gemini transport error: {e}")
    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.error(f"Optimizer analysis failed: {e}")
        return _fallback_response(elapsed_ms, f"runtime error: {e}")
