import os
import yaml
import logging
import logging.config

LOGGER_NAME = "srehubapp_logger"

def setup_logger(config_path="config/logger.yaml"):
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Logger config not found at {config_path}")
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
        logging.config.dictConfig(config)

def set_log_level(level_name: str):
    """
    Dynamically updates the log level for the srehubapp logger
    """
    logger = logging.getLogger(LOGGER_NAME)
    level = getattr(logging, level_name.upper(), None)
    if not isinstance(level, int):
        raise ValueError(f"Invalid log level: {level_name}")
    logger.setLevel(level)
    for handler in logger.handlers:
        handler.setLevel(level)
    logger.info(f"Log level changed dynamically to: {level_name}")