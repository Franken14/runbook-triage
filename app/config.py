import os
from typing import Optional

try:
    from pydantic_settings import BaseSettings

    class Settings(BaseSettings):
        APP_ENV: str = "development"
        LOG_LEVEL: str = "info"
        
        # Database (PostgreSQL + pgvector)
        DATABASE_URL: str = "postgresql://incident_admin:secret_runbook_pass@localhost:5432/incident_db"
        
        # Redis
        REDIS_URL: str = "redis://localhost:6379/0"
        
        # Agent Guardrails & Thresholds
        DEDUPLICATION_WINDOW_SECONDS: int = 60
        REQUIRE_APPROVAL_MUTATING_ACTIONS: bool = True
        MAX_DIAGNOSTIC_ITERATIONS: int = 5
        
        # LLM Settings
        OPENAI_API_KEY: Optional[str] = None
        GEMINI_API_KEY: Optional[str] = None
        LLM_MODEL: str = "gpt-4o-mini"
        EMBEDDING_MODEL: str = "text-embedding-3-small"
        EMBEDDING_DIMENSION: int = 1536

        class Config:
            env_file = ".env"
            env_file_encoding = "utf-8"

except ImportError:
    class Settings:  # type: ignore
        def __init__(self):
            self.APP_ENV = os.getenv("APP_ENV", "development")
            self.LOG_LEVEL = os.getenv("LOG_LEVEL", "info")
            self.DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://incident_admin:secret_runbook_pass@localhost:5432/incident_db")
            self.REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            self.DEDUPLICATION_WINDOW_SECONDS = int(os.getenv("DEDUPLICATION_WINDOW_SECONDS", "60"))
            self.REQUIRE_APPROVAL_MUTATING_ACTIONS = os.getenv("REQUIRE_APPROVAL_MUTATING_ACTIONS", "true").lower() in ("true", "1", "yes")
            self.MAX_DIAGNOSTIC_ITERATIONS = int(os.getenv("MAX_DIAGNOSTIC_ITERATIONS", "5"))
            self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
            self.GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
            self.LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
            self.EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
            self.EMBEDDING_DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "1536"))


settings = Settings()
