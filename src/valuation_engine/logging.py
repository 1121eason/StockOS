import json
import logging

logger = logging.getLogger("qve")


def log(event: str, **fields: object) -> None:
    logger.info(json.dumps({"event": event, **fields}, default=str, sort_keys=True))
