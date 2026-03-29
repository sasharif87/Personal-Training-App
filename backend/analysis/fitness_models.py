# backend/analysis/fitness_models.py
"""
Fitness metric calculations.

Implements the core performance modelling functions:
  calculate_ctl_atl_tsb — Banister impulse-response model (fitness/fatigue/form)
  extract_css           — Critical Swim Speed from 200m/400m TT times
  pace_to_css_fraction  — Normalise a swim pace to CSS fraction for TSS
"""
import pandas as pd
import numpy as np

# ---------------------------------------------------------------------------
# CTL / ATL / TSB  (Banister impulse-response model)
# ---------------------------------------------------------------------------
def calculate_ctl_atl_tsb(daily_tss_series: pd.Series):
    """
    Standard Banister CTL/ATL model.
    CTL = 42-day exponentially weighted average.
    ATL = 7-day exponentially weighted average.
    TSB = CTL - ATL.
    """
    ctl = daily_tss_series.ewm(span=42).mean()
    atl = daily_tss_series.ewm(span=7).mean()
    tsb = ctl - atl
    return ctl, atl, tsb

# ---------------------------------------------------------------------------
# Swim metrics
# ---------------------------------------------------------------------------
def extract_css(swim_400m_time_sec: float, swim_200m_time_sec: float):
    """
    CSS = (400-200) / (T400-T200)
    Returns CSS in m/sec.
    """
    css = (400 - 200) / (swim_400m_time_sec - swim_200m_time_sec)
    return css

def pace_to_css_fraction(pace_m_per_sec: float, css_m_per_sec: float):
    return pace_m_per_sec / css_m_per_sec
