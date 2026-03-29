import pytest
import pandas as pd
from backend.analysis.fitness_models import calculate_ctl_atl_tsb, extract_css, pace_to_css_fraction

# Test Class for Fitness Models
class TestFitnessModels:
    
    @pytest.mark.parametrize("daily_tss_series", [pd.Series([], dtype=float)], scope="function")
    def test_calculate_ctl_atl_tsb_with_empty_series(self, daily_tss_series):
        ctl, atl, tsb = calculate_ctl_atl_tsb(daily_tss_series)
        assert pd.isna(ctl).all() and pd.isna(atl).all() and pd.isna(tsb).all()
    
    @pytest.mark.parametrize("daily_tss_series", [pd.Series([10]*30, dtype=float)], scope="function")
    def test_calculate_ctl_atl_tsb_with_constant_values(self, daily_tss_series):
        ctl, atl, tsb = calculate_ctl_atl_tsb(daily_tss_series)
        assert not pd.isna(ctl).any() and not pd.isna(atl).any() and not pd.isna(tsb).any()
        assert (ctl == 10).all() and (atl == 10).all() and (tsb == 0).all()
    
    @pytest.mark.parametrize("swim_400m_time_sec, swim_200m_time_sec", [(float('inf'), float('inf'))])
    def test_extract_css_with_zero_time_difference(self, swim_400m_time_sec, swim_200m_time_sec):
        with pytest.raises(ZeroDivisionError):
            extract_css(swim_400m_time_sec, swim_200m_time_sec)
    
    @pytest.mark.parametrize("pace_m_per_sec, css_m_per_sec", [(0, 1)])
    def test_pace_to_css_fraction_with_zero_css(self, pace_m_per_sec, css_m_per_sec):
        with pytest.raises(ZeroDivisionError):
            pace_to_css_fraction(pace_m_per_sec, css_m_per_sec)