"""API routes for metrics endpoints."""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from .influx import influx_helper

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["metrics"])


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
