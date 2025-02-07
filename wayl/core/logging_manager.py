from typing import Dict, Any, Optional
import logging
import json
import asyncio
from datetime import datetime
import structlog
from prometheus_client import Counter
import sys
import traceback
from pathlib import Path

# Metrics
log_entries = Counter('log_entries_total', 'Total log entries', ['level'])


class LoggingManager:
    def __init__(
            self,
            app_name: str,
            log_dir: str = "logs",
            retention_days: int = 30,
            max_file_size: int = 100 * 1024 * 1024  # 100MB
    ):
        self.app_name = app_name
        self.log_dir = Path(log_dir)
        self.retention_days = retention_days
        self.max_file_size = max_file_size
        self._setup_logging()

    def _setup_logging(self):
        # Create log directory if it doesn't exist
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Configure structlog
        structlog.configure(
            processors=[
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.stdlib.add_log_level,
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                self._add_extra_fields,
                structlog.processors.JSONRenderer()
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )

        # Setup handlers
        self._setup_handlers()

    def _setup_handlers(self):
        handlers = []

        # File handler for general logs
        general_handler = logging.handlers.RotatingFileHandler(
            self.log_dir / f"{self.app_name}.log",
            maxBytes=self.max_file_size,
            backupCount=5
        )
        general_handler.setLevel(logging.INFO)
        handlers.append(general_handler)

        # File handler for errors
        error_handler = logging.handlers.RotatingFileHandler(
            self.log_dir / f"{self.app_name}_error.log",
            maxBytes=self.max_file_size,
            backupCount=5
        )
        error_handler.setLevel(logging.ERROR)
        handlers.append(error_handler)

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        handlers.append(console_handler)

        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        for handler in handlers:
            handler.setFormatter(self._get_formatter())
            root_logger.addHandler(handler)

    def _get_formatter(self):
        return logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

    async def rotate_logs(self):
        """Rotate logs based on size and retention period"""
        try:
            for log_file in self.log_dir.glob("*.log*"):
                if await self._should_rotate(log_file):
                    await self._rotate_file(log_file)
        except Exception as e:
            logging.error(f"Log rotation failed: {str(e)}")

    async def _should_rotate(self, file_path: Path) -> bool:
        stats = file_path.stat()
        file_age_days = (datetime.now() - datetime.fromtimestamp(stats.st_mtime)).days
        return (
                stats.st_size > self.max_file_size or
                file_age_days > self.retention_days
        )

    def _add_extra_fields(self, logger, name, event_dict):
        """Add extra fields to log entries"""
        event_dict["app_name"] = self.app_name
        event_dict["hostname"] = socket.gethostname()
        event_dict["pid"] = os.getpid()
        return event_dict

    async def archive_logs(self, archive_dir: Optional[str] = None):
        """Archive old logs"""
        if not archive_dir:
            archive_dir = self.log_dir / "archive"

        Path(archive_dir).mkdir(parents=True, exist_ok=True)

        current_date = datetime.now()