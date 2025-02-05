
import logging
from logging.handlers import RotatingFileHandler
import os
from datetime import datetime

def setup_logging(app_name: str, log_dir: str = "logs"):
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_file = os.path.join(
        log_dir,
        f"{app_name.lower()}_{datetime.now().strftime('%Y%m%d')}.log"
    )

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    loggers = {
        'wayl': {
            'level': 'INFO',
            'handlers': [file_handler, console_handler]
        },
        'wayl.api': {
            'level': 'DEBUG',
            'handlers': [file_handler, console_handler]
        },
        'wayl.blockchain': {
            'level': 'INFO',
            'handlers': [file_handler, console_handler]
        },
        'wayl.core': {
            'level': 'INFO',
            'handlers': [file_handler, console_handler]
        }
    }

    for logger_name, config in loggers.items():
        logger = logging.getLogger(logger_name)
        logger.setLevel(config['level'])
        for handler in config['handlers']:
            logger.addHandler(handler)

    return logging.getLogger(app_name)