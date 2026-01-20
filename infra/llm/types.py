from dataclasses import dataclass
from typing import Optional


@dataclass
class LlmConfig:
    provider: str = "openai"
    api_key: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    timeout: float = 60.0
    base_url: Optional[str] = None
    azure_endpoint: Optional[str] = None
    azure_deployment: Optional[str] = None
    azure_api_version: Optional[str] = None
    anthropic_version: Optional[str] = None
    max_tokens: int = 1024
