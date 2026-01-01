"""
Centralized logging configuration for Honora Book API.
"""
import logging
import sys
from pathlib import Path
from typing import Optional

from app.config import Config


class HonoraLogger:
    """Centralized logger for Honora Book API."""
    
    _loggers = {}
    _configured = False
    
    @classmethod
    def setup(cls, log_file: Optional[Path] = None) -> None:
        """
        Setup logging configuration.
        
        Args:
            log_file: Optional path to log file
        """
        if cls._configured:
            return
        
        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, Config.LOG_LEVEL, logging.INFO))
        
        # Remove existing handlers
        root_logger.handlers.clear()
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG if Config.DEBUG else logging.INFO)
        console_formatter = logging.Formatter(Config.LOG_FORMAT)
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)
        
        # File handler (if specified)
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(logging.DEBUG)
            file_formatter = logging.Formatter(Config.LOG_FORMAT)
            file_handler.setFormatter(file_formatter)
            root_logger.addHandler(file_handler)
        
        cls._configured = True
    
    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """
        Get or create a logger with the specified name.
        
        Args:
            name: Logger name (usually __name__)
            
        Returns:
            Configured logger instance
        """
        if not cls._configured:
            cls.setup()
        
        if name not in cls._loggers:
            logger = logging.getLogger(name)
            cls._loggers[name] = logger
        
        return cls._loggers[name]


# Convenience function
def get_logger(name: str) -> logging.Logger:
    """Get a logger instance."""
    return HonoraLogger.get_logger(name)


# Setup logging on module import
HonoraLogger.setup()
