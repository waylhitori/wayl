LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "fmt": "%(asctime)s %(name)s %(levelname)s %(message)s"
        },
        "standard": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "stream": "ext://sys.stdout"
        },
        "json_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "json",
            "filename": "logs/app.json",
            "maxBytes": 10485760,
            "backupCount": 5
        }
    },
    "loggers": {
        "wayl": {
            "level": "INFO",
            "handlers": ["console", "json_file"],
            "propagate": False
        }
    },
    "root": {
        "level": "INFO",
        "handlers": ["console"]
    }
}