import os
import sys
from logging.config import dictConfig

from hymie import create_app

try:
    path = os.environ["HYMIE_APP_PATH"]
except KeyError:
    sys.exit("HYMIE_APP_PATH environmental variable not set")


dictConfig(
    {
        "version": 1,
        "formatters": {
            "default": {
                "format": "[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
            }
        },
        "handlers": {
            "wsgi": {
                "class": "logging.StreamHandler",
                "stream": "ext://flask.logging.wsgi_errors_stream",
                "formatter": "default",
            }
        },
        "loggers": {"hymie": {"level": "DEBUG", "handlers": ["wsgi"]}},
    }
)

# noqa: F401
app = create_app(path, production=bool(os.environ.get("HYMIE_PRODUCTION", False)))
app.logger.info("App created")
