"""
Configuration management for Honora Book API.
Handles environment variables, API keys, and application settings.
"""
import os
import sys
from typing import Optional
from pathlib import Path


class ConfigurationError(Exception):
    """Raised when required configuration is missing or invalid."""
    pass


class Config:
    """Centralized configuration management."""
    
    # API Keys
    GEMINI_API_KEY: Optional[str] = None
    NANO_BANANA_API_KEY: Optional[str] = None
    SUPABASE_URL: Optional[str] = None
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = None
    MARKER_API_KEY: Optional[str] = None
    
    # Application Settings
    DEBUG: bool = False
    ENVIRONMENT: str = "production"
    
    # Temporary Directories
    TEMP_DIR: Path = None
    TEMP_DIR_V2: Path = None
    
    # Processing Limits
    MAX_FILE_SIZE_MB: int = 100
    MAX_CHARS_PER_SECTION: int = 250
    MAX_PAGES_PER_REQUEST: int = 1000
    
    # API Rate Limits
    GEMINI_MAX_RETRIES: int = 3
    GEMINI_RETRY_DELAY: int = 5
    
    # Timeouts (in seconds)
    API_TIMEOUT: int = 300
    GEMINI_TIMEOUT: int = 120
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    @classmethod
    def load(cls) -> None:
        """Load configuration from environment variables."""
        # API Keys - Required
        cls.GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
        cls.NANO_BANANA_API_KEY = os.getenv("NANO_BANANA_API_KEY")
        cls.SUPABASE_URL = os.getenv("SUPABASE_URL")
        cls.SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        cls.MARKER_API_KEY = os.getenv("MARKER_API_KEY")
        
        # Application Settings
        cls.DEBUG = os.getenv("DEBUG", "false").lower() == "true"
        cls.ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
        
        # Temporary Directories
        temp_base = os.getenv("TEMP_DIR", "/tmp")
        cls.TEMP_DIR = Path(temp_base) / "honora"
        cls.TEMP_DIR_V2 = Path(temp_base) / "honora_v2"
        
        # Create temp directories
        cls.TEMP_DIR.mkdir(parents=True, exist_ok=True)
        cls.TEMP_DIR_V2.mkdir(parents=True, exist_ok=True)
        
        # Processing Limits
        cls.MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "100"))
        cls.MAX_CHARS_PER_SECTION = int(os.getenv("MAX_CHARS_PER_SECTION", "250"))
        cls.MAX_PAGES_PER_REQUEST = int(os.getenv("MAX_PAGES_PER_REQUEST", "1000"))
        
        # API Settings
        cls.OPENAI_MAX_RETRIES = int(os.getenv("OPENAI_MAX_RETRIES", "3"))
        cls.OPENAI_RETRY_DELAY = int(os.getenv("OPENAI_RETRY_DELAY", "5"))
        cls.GEMINI_MAX_RETRIES = int(os.getenv("GEMINI_MAX_RETRIES", "3"))
        cls.GEMINI_RETRY_DELAY = int(os.getenv("GEMINI_RETRY_DELAY", "5"))
        
        # Timeouts
        cls.API_TIMEOUT = int(os.getenv("API_TIMEOUT", "300"))
        cls.OPENAI_TIMEOUT = int(os.getenv("OPENAI_TIMEOUT", "120"))
        cls.GEMINI_TIMEOUT = int(os.getenv("GEMINI_TIMEOUT", "120"))
        
        # Logging
        cls.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    
    @classmethod
    def validate_required(cls, *keys: str) -> None:
        """
        Validate that required configuration keys are set.
        
        Args:
            *keys: Configuration keys to validate
            
        Raises:
            ConfigurationError: If any required key is missing
        """
        missing = []
        for key in keys:
            value = getattr(cls, key, None)
            if not value:
                missing.append(key)
        
        if missing:
            raise ConfigurationError(
                f"Missing required configuration: {', '.join(missing)}. "
                f"Please set the corresponding environment variables."
            )
    
    @classmethod
    def get_temp_dir(cls, version: int = 1) -> Path:
        """Get the appropriate temporary directory."""
        return cls.TEMP_DIR_V2 if version == 2 else cls.TEMP_DIR
    
    @classmethod
    def is_configured(cls, service: str) -> bool:
        """Check if a service is configured."""
        service_map = {
            "openai": cls.OPENAI_API_KEY,
            "gemini": cls.GEMINI_API_KEY,
            "supabase": cls.SUPABASE_URL and cls.SUPABASE_SERVICE_ROLE_KEY,
            "marker": cls.MARKER_API_KEY
        }
        return bool(service_map.get(service.lower()))


# Load configuration on module import
try:
    Config.load()
except Exception as e:
    print(f"Warning: Failed to load configuration: {e}", file=sys.stderr)
