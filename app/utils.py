"""
Utility functions for Honora Book API.
Includes retry logic, error handling, and helper functions.
"""
import time
import functools
from typing import Callable, Any, Optional, Type
from pathlib import Path
import shutil

from app.config import Config
from app.logger import get_logger

logger = get_logger(__name__)


class RetryableError(Exception):
    """Error that should trigger a retry."""
    pass


def retry_on_failure(
    max_retries: Optional[int] = None,
    delay: Optional[int] = None,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,)
) -> Callable:
    """
    Decorator to retry a function on failure.
    
    Args:
        max_retries: Maximum number of retries (default from Config)
        delay: Initial delay in seconds (default from Config)
        backoff: Backoff multiplier for delay
        exceptions: Tuple of exceptions to catch and retry
        
    Returns:
        Decorated function
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            retries = max_retries or Config.OPENAI_MAX_RETRIES
            current_delay = delay or Config.OPENAI_RETRY_DELAY
            
            for attempt in range(retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt == retries:
                        logger.error(
                            f"{func.__name__} failed after {retries} retries: {e}"
                        )
                        raise
                    
                    logger.warning(
                        f"{func.__name__} attempt {attempt + 1} failed: {e}. "
                        f"Retrying in {current_delay}s..."
                    )
                    time.sleep(current_delay)
                    current_delay *= backoff
            
            return None
        
        return wrapper
    return decorator


def safe_file_operation(func: Callable) -> Callable:
    """
    Decorator for safe file operations with error handling.
    
    Args:
        func: Function to wrap
        
    Returns:
        Wrapped function
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        try:
            return func(*args, **kwargs)
        except OSError as e:
            logger.error(f"File operation failed in {func.__name__}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error in {func.__name__}: {e}")
            raise
    
    return wrapper


@safe_file_operation
def ensure_directory(path: Path) -> Path:
    """
    Ensure a directory exists, creating it if necessary.
    
    Args:
        path: Directory path
        
    Returns:
        Path object
    """
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


@safe_file_operation
def cleanup_temp_files(directory: Path, max_age_hours: int = 24) -> int:
    """
    Clean up old temporary files.
    
    Args:
        directory: Directory to clean
        max_age_hours: Maximum age of files to keep in hours
        
    Returns:
        Number of files deleted
    """
    if not directory.exists():
        return 0
    
    deleted_count = 0
    current_time = time.time()
    max_age_seconds = max_age_hours * 3600
    
    for item in directory.iterdir():
        try:
            # Check file age
            if item.is_file():
                age = current_time - item.stat().st_mtime
                if age > max_age_seconds:
                    item.unlink()
                    deleted_count += 1
                    logger.debug(f"Deleted old temp file: {item}")
            elif item.is_dir():
                # Recursively clean directories
                age = current_time - item.stat().st_mtime
                if age > max_age_seconds:
                    shutil.rmtree(item)
                    deleted_count += 1
                    logger.debug(f"Deleted old temp directory: {item}")
        except Exception as e:
            logger.warning(f"Failed to delete {item}: {e}")
    
    logger.info(f"Cleaned up {deleted_count} old temporary files from {directory}")
    return deleted_count


def validate_file_size(file_path: Path, max_size_mb: Optional[int] = None) -> bool:
    """
    Validate that a file is within size limits.
    
    Args:
        file_path: Path to file
        max_size_mb: Maximum size in MB (default from Config)
        
    Returns:
        True if valid, False otherwise
        
    Raises:
        ValueError: If file exceeds size limit
    """
    max_size = (max_size_mb or Config.MAX_FILE_SIZE_MB) * 1024 * 1024
    file_size = file_path.stat().st_size
    
    if file_size > max_size:
        raise ValueError(
            f"File size ({file_size / 1024 / 1024:.1f} MB) exceeds "
            f"maximum allowed size ({max_size / 1024 / 1024:.1f} MB)"
        )
    
    return True


def truncate_text(text: str, max_length: int, suffix: str = "...") -> str:
    """
    Truncate text to a maximum length.
    
    Args:
        text: Text to truncate
        max_length: Maximum length
        suffix: Suffix to add if truncated
        
    Returns:
        Truncated text
    """
    if not text or len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename to remove dangerous characters.
    
    Args:
        filename: Original filename
        
    Returns:
        Sanitized filename
    """
    # Remove path separators and other dangerous characters
    dangerous_chars = ['/', '\\', '..', '\0', '\n', '\r', '\t']
    for char in dangerous_chars:
        filename = filename.replace(char, '_')
    
    # Remove leading/trailing whitespace and dots
    filename = filename.strip('. ')
    
    # Ensure filename is not empty
    if not filename:
        filename = "unnamed_file"
    
    return filename


def format_bytes(bytes_size: int) -> str:
    """
    Format bytes into human-readable format.
    
    Args:
        bytes_size: Size in bytes
        
    Returns:
        Formatted string
    """
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} TB"
