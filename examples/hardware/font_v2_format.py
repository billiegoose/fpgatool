"""Wire-format constants for the FPGA font-v2 loader.

Font compilation, serialization and validation belong to red2-font.
"""
MAGIC = 0x32564652  # b"RFV2"
VERSION = 2
MAX_PAGES = 8
HEADER_WORDS = 40
HEADER_BYTES = HEADER_WORDS * 4
PAYLOAD_WORDS = 1024
PAGE_WORD_BASE = 24
CHECKSUM_WORD = 16
