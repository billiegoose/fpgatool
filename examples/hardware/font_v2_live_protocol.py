"""Compatibility names for the original font-demo mailbox ABI."""
from .live_flash_protocol import (
    MAGIC, BEGIN, RELOAD as COMMIT, RELEASE as ABORT,
    READY, GRANTED, BUSY, ERROR, USER2, IR_BITS, DEFAULT_URL,
)
