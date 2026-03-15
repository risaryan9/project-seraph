"""InfluxDB client and query helper for metrics."""

import logging
import os
from typing import Dict, List, Optional
from datetime import datetime

from influxdb_client import InfluxDBClient
from influxdb_client.client.query_api import QueryApi

logger = logging.getLogger(__name__)


class InfluxDBHelper:
    """
    Helper class for querying InfluxDB metrics.
    
    Manages InfluxDB client lifecycle and provides query building utilities.
    """
    
    METRIC_FIELDS = [
        "cpu_percent",
        "cpu_system",
        "ram_mb",
        "ram_system_pct",
        "io_read_mb",
        "io_write_mb",
        "thread_count",
        "page_faults_minor",
        "page_faults_major",
        "voluntary_ctx_switches",
        "llc_miss_rate",
        "throughput",
        "phase_duration_ms",
    ]
    
    def __init__(self):
        """Initialize InfluxDB helper with environment configuration."""
        self.url = os.getenv("INFLUX_URL", "http://localhost:8086")
        self.token = os.getenv("INFLUX_TOKEN", "mlviz-dev-token")
        self.org = os.getenv("INFLUX_ORG", "mlviz")
        self.bucket = os.getenv("INFLUX_BUCKET", "metrics")
        
        self.client: Optional[InfluxDBClient] = None
        self.query_api: Optional[QueryApi] = None
    
    def connect(self):
        """Connect to InfluxDB and initialize query API."""
        try:
            self.client = InfluxDBClient(
                url=self.url,
                token=self.token,
                org=self.org
            )
            self.query_api = self.client.query_api()
            logger.info(f"Connected to InfluxDB at {self.url}")
        except Exception as e:
            logger.error(f"Failed to connect to InfluxDB: {e}")
            raise
    
    def close(self):
        """Close InfluxDB client connection."""
        if self.client:
            try:
                self.client.close()
                logger.info("InfluxDB client closed")
            except Exception as e:
                logger.error(f"Error closing InfluxDB client: {e}")
    
    def health_check(self) -> bool:
        """Check if InfluxDB is reachable."""
        try:
            if not self.client:
                return False
            health = self.client.health()
            return health.status == "pass"
        except Exception as e:
            logger.error(f"InfluxDB health check failed: {e}")
            return False
    
    def build_time_range(
        self,
        start_relative: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None
    ) -> str:
        """
        Build Flux time range clause.
        
        Args:
            start_relative: Relative time (e.g., "-5m", "-1h", "-24h")
            start: Absolute start time (ISO8601 or Unix ms)
            end: Absolute end time (ISO8601 or Unix ms)
        
        Returns:
            Flux range clause
        """
        if start or end:
            start_clause = f'start: {self._format_time(start)}' if start else 'start: 0'
            end_clause = f', stop: {self._format_time(end)}' if end else ''
            return f'range({start_clause}{end_clause})'
        else:
            rel = start_relative or "-1h"
            return f'range(start: {rel})'
    
    def _format_time(self, time_str: str) -> str:
        """Format time string for Flux query."""
        try:
            int(time_str)
            return f'time(v: {int(time_str) * 1_000_000})'
        except ValueError:
            return f'time(v: "{time_str}")'
    
    def build_filters(
        self,
        model_id: Optional[str] = None,
        phase: Optional[str] = None,
        fields: Optional[List[str]] = None
    ) -> str:
        """
        Build Flux filter clauses.
        
        Args:
            model_id: Filter by model_id tag
            phase: Filter by phase tag
            fields: List of field names to include
        
        Returns:
            Flux filter clauses
        """
        filters = []
        filters.append('|> filter(fn: (r) => r._measurement == "hardware_sample")')
        
        if model_id:
            filters.append(f'|> filter(fn: (r) => r.model_id == "{model_id}")')
        
        if phase:
            filters.append(f'|> filter(fn: (r) => r.phase == "{phase}")')
        
        if fields:
            field_conditions = ' or '.join([f'r._field == "{f}"' for f in fields])
            filters.append(f'|> filter(fn: (r) => {field_conditions})')
        
        return '\n  '.join(filters)
    
    def query_raw(
        self,
        start_relative: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        model_id: Optional[str] = None,
        phase: Optional[str] = None,
        fields: Optional[List[str]] = None,
        limit: int = 1000
    ) -> List[Dict]:
        """
        Query raw time-series data from InfluxDB.
        
        Returns list of records with timestamp, tags, and field values.
        """
        time_range = self.build_time_range(start_relative, start, end)
        filters = self.build_filters(model_id, phase, fields)
        
        flux_query = f'''
from(bucket: "{self.bucket}")
  |> {time_range}
  {filters}
  |> limit(n: {limit})
'''
        
        logger.debug(f"Executing Flux query: {flux_query}")
        
        try:
            tables = self.query_api.query(flux_query)
            return self._parse_tables(tables)
        except Exception as e:
            logger.error(f"Query failed: {e}")
            raise
    
    def query_aggregate(
        self,
        window: str = "1m",
        aggregation: str = "mean",
        start_relative: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        model_id: Optional[str] = None,
        phase: Optional[str] = None,
        fields: Optional[List[str]] = None,
        limit: int = 500
    ) -> List[Dict]:
        """
        Query aggregated time-series data with windowing.
        
        Args:
            window: Window duration (e.g., "30s", "1m", "5m")
            aggregation: Aggregation function ("mean", "max", "min")
        
        Returns list of aggregated records.
        """
        time_range = self.build_time_range(start_relative, start, end)
        filters = self.build_filters(model_id, phase, fields)
        
        flux_query = f'''
from(bucket: "{self.bucket}")
  |> {time_range}
  {filters}
  |> aggregateWindow(every: {window}, fn: {aggregation}, createEmpty: false)
  |> limit(n: {limit})
'''
        
        logger.debug(f"Executing Flux query: {flux_query}")
        
        try:
            tables = self.query_api.query(flux_query)
            return self._parse_tables(tables)
        except Exception as e:
            logger.error(f"Query failed: {e}")
            raise
    
    def query_distinct_models(
        self,
        start_relative: str = "-24h",
        start: Optional[str] = None,
        end: Optional[str] = None
    ) -> List[str]:
        """Get distinct model_id values."""
        time_range = self.build_time_range(start_relative, start, end)
        
        flux_query = f'''
from(bucket: "{self.bucket}")
  |> {time_range}
  |> filter(fn: (r) => r._measurement == "hardware_sample")
  |> keep(columns: ["model_id"])
  |> distinct(column: "model_id")
'''
        
        try:
            tables = self.query_api.query(flux_query)
            models = set()
            for table in tables:
                for record in table.records:
                    if hasattr(record, 'values') and 'model_id' in record.values:
                        models.add(record.values['model_id'])
            return sorted(list(models))
        except Exception as e:
            logger.error(f"Query failed: {e}")
            raise
    
    def query_distinct_phases(
        self,
        model_id: Optional[str] = None,
        start_relative: str = "-24h",
        start: Optional[str] = None,
        end: Optional[str] = None
    ) -> List[str]:
        """Get distinct phase values, optionally filtered by model_id."""
        time_range = self.build_time_range(start_relative, start, end)
        
        model_filter = ''
        if model_id:
            model_filter = f'|> filter(fn: (r) => r.model_id == "{model_id}")'
        
        flux_query = f'''
from(bucket: "{self.bucket}")
  |> {time_range}
  |> filter(fn: (r) => r._measurement == "hardware_sample")
  {model_filter}
  |> keep(columns: ["phase"])
  |> distinct(column: "phase")
'''
        
        try:
            tables = self.query_api.query(flux_query)
            phases = set()
            for table in tables:
                for record in table.records:
                    if hasattr(record, 'values') and 'phase' in record.values:
                        phases.add(record.values['phase'])
            return sorted(list(phases))
        except Exception as e:
            logger.error(f"Query failed: {e}")
            raise
    
    def query_total_count(
        self,
        start_relative: str = "-24h",
        start: Optional[str] = None,
        end: Optional[str] = None
    ) -> int:
        """
        Get total count of metric records in InfluxDB for the time range.
        Each hardware sample writes multiple records (one per field); this returns
        the total record count. For approximate sample count, divide by len(METRIC_FIELDS).
        """
        time_range = self.build_time_range(start_relative, start, end)
        flux_query = f'''
from(bucket: "{self.bucket}")
  |> {time_range}
  |> filter(fn: (r) => r._measurement == "hardware_sample")
  |> group()
  |> count()
'''
        try:
            tables = self.query_api.query(flux_query)
            for table in tables:
                for record in table.records:
                    val = record.get_value()
                    if val is not None:
                        return int(val)
            return 0
        except Exception as e:
            logger.error(f"Count query failed: {e}")
            raise

    def query_recent_samples(
        self,
        start_relative: str = "-2m",
        limit: int = 3000
    ) -> List[Dict]:
        """
        Query recent raw metrics and pivot into one dict per (timestamp, model_id, phase)
        with all field values. Returns list of MetricSample-like dicts for dashboard use.
        """
        raw = self.query_raw(
            start_relative=start_relative,
            fields=None,
            limit=limit
        )
        # Pivot: group by (timestamp, model_id, phase)
        from collections import defaultdict
        from datetime import datetime
        groups = defaultdict(dict)
        for r in raw:
            ts = r["timestamp"]
            model_id = r.get("model_id") or ""
            phase = r.get("phase") or "idle"
            key = (ts, model_id, phase)
            if key not in groups:
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    groups[key]["timestamp"] = int(dt.timestamp() * 1000)
                except Exception:
                    groups[key]["timestamp"] = 0
                groups[key]["model_id"] = model_id
                groups[key]["phase"] = phase
            field = r.get("field")
            value = r.get("value")
            if field is not None and value is not None:
                groups[key][field] = value

        # Build list with all numeric fields, use 0 or -1 for missing
        result = []
        for key, d in groups.items():
            row = {
                "timestamp": d["timestamp"],
                "model_id": d["model_id"],
                "phase": d["phase"],
                "cpu_percent": d.get("cpu_percent", 0.0),
                "cpu_system": d.get("cpu_system", 0.0),
                "ram_mb": d.get("ram_mb", 0.0),
                "ram_system_pct": d.get("ram_system_pct", 0.0),
                "io_read_mb": d.get("io_read_mb", 0.0),
                "io_write_mb": d.get("io_write_mb", 0.0),
                "thread_count": int(d.get("thread_count", 0)),
                "page_faults_minor": int(d.get("page_faults_minor", 0)),
                "page_faults_major": int(d.get("page_faults_major", 0)),
                "voluntary_ctx_switches": int(d.get("voluntary_ctx_switches", 0)),
                "llc_miss_rate": d.get("llc_miss_rate", -1.0),
                "throughput": d.get("throughput", -1.0),
                "phase_duration_ms": d.get("phase_duration_ms", 0.0),
            }
            result.append(row)
        result.sort(key=lambda x: x["timestamp"])
        return result

    def _parse_tables(self, tables) -> List[Dict]:
        """
        Parse InfluxDB query result tables into list of dicts.
        
        Returns records in format:
        {
            "timestamp": "2024-03-14T12:00:00Z",
            "model_id": "resnet18-train",
            "phase": "forward",
            "field": "cpu_percent",
            "value": 45.2
        }
        """
        records = []
        for table in tables:
            for record in table.records:
                records.append({
                    "timestamp": record.get_time().isoformat(),
                    "model_id": record.values.get("model_id"),
                    "phase": record.values.get("phase"),
                    "field": record.get_field(),
                    "value": record.get_value()
                })
        return records


influx_helper = InfluxDBHelper()
