"""
k8s_mcp.logging_config
~~~~~~~~~~~~~~~~~~~~~~

Centralised logging setup for the k8s_mcp package.

Call ``configure_logging()`` once at server startup.  Every other module
obtains its own logger via ``logging.getLogger(__name__)`` and inherits
this configuration automatically.

Log level is controlled by the ``LOG_LEVEL`` environment variable
(default: ``INFO``).  Valid values: DEBUG, INFO, WARNING, ERROR, CRITICAL.
"""

import logging
import os
import sys


def configure_logging() -> None:
    """Configure the root logger with a consistent format.

    Always logs to stderr — stdout is reserved for the MCP stdio protocol
    when the server runs as a subprocess.
    """
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        stream=sys.stderr,
        format="%(asctime)s [%(levelname)-5s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    if level != "DEBUG":
        logging.getLogger("kubernetes").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
