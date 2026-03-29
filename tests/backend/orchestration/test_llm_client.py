import pytest
from unittest.mock import patch, MagicMock
from backend.orchestration.llm_client import OllamaClient
import requests

class TestOllamaClient:
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = OllamaClient()

    @patch('requests.post')
    def test_generate_workout_plan_success(self, mock_post):
        # Arrange
        context = {"fatigue": 0.5, "hrv_trend": "stable", "race_focus": "Ironman"}
        expected_response = {"workouts": ["Swim 2 hours", "Cycle 4 hours", "Run 3 hours"]}
        
        mock_post.return_value = MagicMock(status_code=200)
        mock_post.return_value.json.return_value = {"response": json.dumps(expected_response)}

        # Act
        response = self.client.generate_workout_plan(context)

        # Assert
        assert response == expected_response
        mock_post.assert_called_once_with(
            f"{self.client.base_url}/api/generate",
            json={
                "model": self.client.model,
                "prompt": f"""
                You are a triathlon coach for an athlete with 10 years of history.
                User data context: {json.dumps(context)}
                Based on this data, reason about the athlete's current fatigue (TSB), 
                HRV trend, and upcoming race focus. 
                Then, generate a structured week of workouts in JSON format only.
                """,
                "format": "json",
                "stream": False
            }
        )

    @patch('requests.post')
    def test_generate_workout_plan_failure(self, mock_post):
        # Arrange
        context = {"fatigue": 0.5, "hrv_trend": "stable", "race_focus": "Ironman"}
        
        mock_post.return_value = MagicMock(status_code=400)
        mock_post.return_value.json.return_value = {"error": "Bad Request"}

        # Act & Assert
        with pytest.raises(requests.HTTPError):
            self.client.generate_workout_plan(context)