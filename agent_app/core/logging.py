from logging.config import dictConfig

from agent_app.core.config import AgentSettings


def configure_agent_logging(settings: AgentSettings) -> None:
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "agent": {
                    "format": (
                        "%(asctime)s %(levelname)s service=agent "
                        "logger=%(name)s message=%(message)s"
                    )
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "agent",
                }
            },
            "root": {
                "handlers": ["console"],
                "level": settings.agent_log_level.upper(),
            },
        }
    )
