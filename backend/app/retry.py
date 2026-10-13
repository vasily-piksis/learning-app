"""One retry budget at the external-request boundary, never around whole jobs."""

import math
import secrets
import time
from datetime import UTC
from email.utils import parsedate_to_datetime


class TransientError(Exception):
    def __init__(self, message, headers=None):
        super().__init__(message)
        self.headers = headers or {}


def server_delay(value, milliseconds=False):
    if value is None:
        return None
    try:
        seconds = float(value)
        if milliseconds:
            seconds /= 1000
    except (ValueError, TypeError):
        if milliseconds:
            return None
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=UTC)
            seconds = date.timestamp() - time.time()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0, seconds) if math.isfinite(seconds) else None


def call(operation):
    for attempt in range(3):
        try:
            return operation()
        except TransientError as error:
            if attempt == 2:
                raise
            instructions = (
                server_delay(error.headers.get("Retry-After")),
                server_delay(error.headers.get("retry-after-ms"), milliseconds=True),
            )
            instructed = max((value for value in instructions if value is not None), default=0)
            # A longer server cooldown requires a later manual retry. Never
            # shorten its instruction and send a request before it allows one.
            if instructed > 60:
                raise
            delay = 2**attempt + secrets.randbelow(250) / 1000
            time.sleep(max(delay, instructed or 0))
