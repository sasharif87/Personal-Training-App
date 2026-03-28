import requests
import json
from typing import Dict, Any

class OllamaClient:
    def __init__(self, base_url="http://localhost:11434", model="llama3:70b-instruct-q4_K_M"):
        self.base_url = base_url
        self.model = model

    def generate_workout_plan(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sends context to Ollama and retrieves a structured workout plan.
        Forces JSON mode if the model supports it.
        """
        prompt = f"""
        You are a triathlon coach for an athlete with 10 years of history.
        User data context: {json.dumps(context)}
        Based on this data, reason about the athlete's current fatigue (TSB), 
        HRV trend, and upcoming race focus. 
        Then, generate a structured week of workouts in JSON format only.
        """
        
        response = requests.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "format": "json",
                "stream": False
            }
        )
        response.raise_for_status()
        return json.loads(response.json()["response"])
