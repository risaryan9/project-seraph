"""
Optimizer diagnostics: phase correlation and interference scoring.

Phase correlation algorithm:
1. Load 60s of samples with valid LLC from InfluxDB
2. Build uniform time grid (1s bins)
3. Forward-fill phase and LLC per model onto grid
4. For each victim model, identify spike bins (LLC > baseline × 1.2 or > p90)
5. For each other model's phase, compute spike_ratio as lift: P(spike | phase_active) / P(spike)
6. Return sorted list of (victim, cause_model, cause_phase, spike_ratio)
"""

import logging
from typing import Dict, List, Optional, Tuple
import numpy as np

logger = logging.getLogger(__name__)

GRID_BIN_MS = 1000
SPIKE_THRESHOLD_MULTIPLIER = 1.2
MIN_OCCUPANCY_BINS = 3
LIFT_EPSILON = 0.01
EPSILON = 0.02
LLC_WEIGHT = 0.6
THROUGHPUT_WEIGHT = 0.4


class PhaseCorrelationItem:
    """Single phase correlation finding."""
    
    def __init__(
        self,
        victim_model: str,
        cause_model: str,
        cause_phase: str,
        spike_ratio: float
    ):
        self.victim_model = victim_model
        self.cause_model = cause_model
        self.cause_phase = cause_phase
        self.spike_ratio = spike_ratio
    
    def to_dict(self) -> dict:
        return {
            "victim_model": self.victim_model,
            "cause_model": self.cause_model,
            "cause_phase": self.cause_phase,
            "spike_ratio": round(self.spike_ratio, 4),
        }


class InterferenceScoreResult:
    """Per-model interference score."""
    
    def __init__(
        self,
        model_id: str,
        score: float,
        llc_degradation: float,
        throughput_degradation: float,
        baseline_llc: Optional[float],
        baseline_throughput: Optional[float],
        current_llc: float,
        current_throughput: float
    ):
        self.model_id = model_id
        self.score = score
        self.llc_degradation = llc_degradation
        self.throughput_degradation = throughput_degradation
        self.baseline_llc = baseline_llc
        self.baseline_throughput = baseline_throughput
        self.current_llc = current_llc
        self.current_throughput = current_throughput
    
    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "score": round(self.score, 4),
            "llc_degradation": round(self.llc_degradation, 4),
            "throughput_degradation": round(self.throughput_degradation, 4),
            "baseline_llc": round(self.baseline_llc, 4) if self.baseline_llc is not None else None,
            "baseline_throughput": round(self.baseline_throughput, 2) if self.baseline_throughput is not None else None,
            "current_llc": round(self.current_llc, 4),
            "current_throughput": round(self.current_throughput, 2),
        }


def compute_weighted_baseline(fingerprint: dict) -> Tuple[Optional[float], Optional[float]]:
    """
    Extract weighted baseline LLC and throughput from fingerprint.
    
    Returns: (llc_mean, throughput_mean) or (None, None) if insufficient data.
    """
    if fingerprint.get("status") != "complete":
        return None, None
    
    phases = fingerprint.get("phases", {})
    if not phases:
        return None, None
    
    llc_sum = 0.0
    llc_weight = 0
    thr_sum = 0.0
    thr_weight = 0
    
    for phase_data in phases.values():
        count = phase_data.get("sample_count", 0)
        if count <= 0:
            continue
        
        llc_stats = phase_data.get("llc", {})
        llc_mean = llc_stats.get("mean", 0.0)
        llc_sum += llc_mean * count
        llc_weight += count
        
        thr_stats = phase_data.get("throughput", {})
        thr_mean = thr_stats.get("mean", -1.0)
        if thr_mean > 0:
            thr_sum += thr_mean * count
            thr_weight += count
    
    llc_baseline = llc_sum / llc_weight if llc_weight > 0 else None
    thr_baseline = thr_sum / thr_weight if thr_weight > 0 else None
    
    return llc_baseline, thr_baseline


def compute_interference_score(
    model_id: str,
    samples: List[dict],
    fingerprint: Optional[dict]
) -> InterferenceScoreResult:
    """
    Compute interference score for a single model.
    
    Formula: 0.6 * LLC_degradation + 0.4 * throughput_degradation
    If throughput unavailable, use only LLC.
    """
    valid_llc = [s["llc_miss_rate"] for s in samples if s.get("llc_miss_rate", -1) >= 0]
    valid_thr = [s["throughput"] for s in samples if s.get("throughput", -1) >= 0]
    
    if not valid_llc:
        return InterferenceScoreResult(
            model_id=model_id,
            score=0.0,
            llc_degradation=0.0,
            throughput_degradation=0.0,
            baseline_llc=None,
            baseline_throughput=None,
            current_llc=0.0,
            current_throughput=-1.0
        )
    
    llc_curr = np.mean(valid_llc)
    thr_curr = np.mean(valid_thr) if valid_thr else -1.0
    
    baseline_llc, baseline_thr = None, None
    if fingerprint:
        baseline_llc, baseline_thr = compute_weighted_baseline(fingerprint)
    
    if baseline_llc is None:
        return InterferenceScoreResult(
            model_id=model_id,
            score=0.0,
            llc_degradation=0.0,
            throughput_degradation=0.0,
            baseline_llc=None,
            baseline_throughput=None,
            current_llc=llc_curr,
            current_throughput=thr_curr
        )
    
    llc_deg = np.clip((llc_curr - baseline_llc) / max(baseline_llc, EPSILON), 0, 1)
    
    thr_deg = 0.0
    use_throughput = False
    
    if baseline_thr is not None and baseline_thr > 0 and thr_curr > 0:
        thr_deg = np.clip((baseline_thr - thr_curr) / max(baseline_thr, EPSILON), 0, 1)
        use_throughput = True
    
    if use_throughput:
        score = LLC_WEIGHT * llc_deg + THROUGHPUT_WEIGHT * thr_deg
    else:
        score = llc_deg
    
    score = np.clip(score, 0, 1)
    
    return InterferenceScoreResult(
        model_id=model_id,
        score=float(score),
        llc_degradation=float(llc_deg),
        throughput_degradation=float(thr_deg),
        baseline_llc=baseline_llc,
        baseline_throughput=baseline_thr,
        current_llc=llc_curr,
        current_throughput=thr_curr
    )


def analyze_phase_correlation(
    samples: List[dict],
    fingerprints: Optional[Dict[str, dict]] = None
) -> List[PhaseCorrelationItem]:
    """
    Analyze phase correlation: which model's phase correlates with LLC spikes on other models.
    
    Args:
        samples: List of metric samples (dicts with timestamp, model_id, phase, llc_miss_rate)
        fingerprints: Optional dict of model_id -> fingerprint for baseline LLC
    
    Returns:
        Sorted list of PhaseCorrelationItem by descending spike_ratio
    """
    valid_samples = [s for s in samples if s.get("llc_miss_rate", -1) >= 0]
    
    if len(valid_samples) < 10:
        logger.warning("Insufficient samples for phase correlation (need ≥10 with valid LLC)")
        return []
    
    timestamps = [s["timestamp"] for s in valid_samples]
    min_ts = min(timestamps)
    max_ts = max(timestamps)
    
    if max_ts - min_ts < 5000:
        logger.warning("Time window too narrow for phase correlation")
        return []
    
    num_bins = int((max_ts - min_ts) / GRID_BIN_MS) + 1
    grid_times = [min_ts + i * GRID_BIN_MS for i in range(num_bins)]
    
    models = list(set(s["model_id"] for s in valid_samples))
    
    grid_phase: Dict[str, List[Optional[str]]] = {m: [None] * num_bins for m in models}
    grid_llc: Dict[str, List[float]] = {m: [0.0] * num_bins for m in models}
    
    for model in models:
        model_samples = sorted(
            [s for s in valid_samples if s["model_id"] == model],
            key=lambda s: s["timestamp"]
        )
        
        for i, grid_t in enumerate(grid_times):
            last_sample = None
            for s in model_samples:
                if s["timestamp"] <= grid_t:
                    last_sample = s
                else:
                    break
            
            if last_sample:
                grid_phase[model][i] = last_sample.get("phase", "idle")
                grid_llc[model][i] = last_sample.get("llc_miss_rate", 0.0)
    
    baselines: Dict[str, float] = {}
    for model in models:
        llc_values = [v for v in grid_llc[model] if v > 0]
        if fingerprints and model in fingerprints:
            fp_baseline, _ = compute_weighted_baseline(fingerprints[model])
            if fp_baseline is not None:
                baselines[model] = fp_baseline
            elif llc_values:
                baselines[model] = float(np.median(llc_values))
        elif llc_values:
            baselines[model] = float(np.median(llc_values))
    
    findings: List[PhaseCorrelationItem] = []
    
    for victim in models:
        if victim not in baselines:
            continue
        
        baseline = baselines[victim]
        llc_arr = np.array(grid_llc[victim])
        p90 = np.percentile(llc_arr[llc_arr > 0], 90) if np.any(llc_arr > 0) else baseline * 1.5
        spike_threshold = max(baseline * SPIKE_THRESHOLD_MULTIPLIER, p90)
        
        spike_bins = llc_arr > spike_threshold
        p_spike = np.mean(spike_bins)
        
        if p_spike < 0.01:
            continue
        
        for cause in models:
            if cause == victim:
                continue
            
            phases_seen = set(p for p in grid_phase[cause] if p is not None)
            
            for phase in phases_seen:
                phase_active = np.array([grid_phase[cause][i] == phase for i in range(num_bins)])
                
                if np.sum(phase_active) < MIN_OCCUPANCY_BINS:
                    continue
                
                spike_given_phase = np.sum(spike_bins & phase_active) / max(np.sum(phase_active), 1)
                spike_ratio = spike_given_phase / max(p_spike, LIFT_EPSILON)
                
                if spike_ratio > 1.1:
                    findings.append(PhaseCorrelationItem(
                        victim_model=victim,
                        cause_model=cause,
                        cause_phase=phase,
                        spike_ratio=float(spike_ratio)
                    ))
    
    findings.sort(key=lambda f: f.spike_ratio, reverse=True)
    return findings
