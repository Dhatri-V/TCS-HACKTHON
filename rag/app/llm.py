import requests

from .config import OLLAMA_MODEL


OLLAMA_URL = "http://localhost:11434/api/generate"


class LLM:

    def __init__(self):
        self.model = OLLAMA_MODEL

    def generate(self, prompt: str):

        response = requests.post(
            OLLAMA_URL,
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False
            },
            timeout=120
        )

        response.raise_for_status()

        data = response.json()

        return data["response"]
    

