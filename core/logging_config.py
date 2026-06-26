from logging.config import dictConfig

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": (
                "%(asctime)s | %(levelname)-8s | "
                "%(name)s | %(message)s"
            )
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": "ext://sys.stdout",  # The default is stderr
        }
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
}


def configure_logging():
    dictConfig(LOGGING_CONFIG)