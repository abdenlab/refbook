"""The catalog's pipeline, version 2: plain functions over declared sources and books.

doit (catalog/dodo.py) only wires them together: each task calls one function with its declared inputs and
outputs. Every function raises Refused when it refuses its inputs (a checksum, a lock, a check), never exits
the process.
"""


class Refused(Exception):
    """A function refused its inputs: a file that doesn't match its checksum or its lock, a failed check."""
