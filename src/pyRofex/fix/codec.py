# -*- coding: utf-8 -*-
"""FIX framing helpers.

Outbound messages are encoded with simplefix so checksum and body length
follow one well-tested implementation. Inbound frames are checked again
here: simplefix does not validate tag 9 or tag 10.

BodyLength (tag 9) is the number of bytes after the SOH that ends the
BodyLength field, up to and including the SOH before ``10=``, and not
including ``10=`` itself.

CheckSum (tag 10) is the sum of every byte up to and including that same
SOH, modulo 256, written as three digits.
"""

from simplefix import FixMessage, FixParser

from .constants import SOH_BYTES


class FrameError(ValueError):
    """A buffer is not a single well-formed FIX frame."""


def require_safe_value(value):
    """Return ``value`` as text, rejecting the FIX field delimiter."""
    if value is None:
        raise ValueError("FIX value is missing")
    text = str(value)
    if SOH_BYTES.decode("ascii") in text:
        raise ValueError("FIX value must not contain SOH")
    return text


def encode_pairs(pairs):
    """Encode ``(tag, value)`` pairs and append BodyLength and CheckSum.

    Tag 8 and tag 35 must be present. Tags 9 and 10, if supplied, are
    ignored and recalculated.
    """
    message = FixMessage()
    for tag, value in pairs:
        message.append_pair(int(tag), require_safe_value(value))
    encoded = message.encode()
    if not checksum_ok(encoded) or not body_length_ok(encoded):
        raise FrameError("encoder produced an invalid FIX frame")
    return encoded


def parse_frame(raw):
    """Return ordered ``(tag, value)`` pairs from one complete frame.

    Raises ``FrameError`` when the checksum or body length does not match
    the bytes, or when the buffer is not one message.
    """
    if not isinstance(raw, (bytes, bytearray)):
        raise FrameError("FIX frame must be bytes")
    raw = bytes(raw)
    if not checksum_ok(raw):
        raise FrameError("bad checksum")
    if not body_length_ok(raw):
        raise FrameError("bad body length")
    parser = FixParser()
    parser.append_buffer(raw)
    message = parser.get_message()
    if message is None:
        raise FrameError("incomplete FIX frame")
    trailing = parser.get_message()
    if trailing is not None:
        raise FrameError("buffer contains more than one FIX frame")
    return list(_pairs(message))


def parse_stream(parser, data):
    """Feed ``data`` to a ``FixParser`` and yield raw frames.

    Each yielded frame is the parser's lossless copy of one message,
    including the original checksum. Callers validate it with
    ``checksum_ok`` / ``body_length_ok``.
    """
    parser.append_buffer(data)
    while True:
        message = parser.get_message()
        if message is None:
            return
        yield message.encode(raw=True)


def pairs_from_message(message):
    """Ordered ``(int, str)`` pairs stored on a simplefix message."""
    return list(_pairs(message))


def _pairs(message):
    for tag, value in message.pairs:
        tag_number = int(tag)
        if isinstance(value, bytes):
            text = value.decode("latin-1")
        else:
            text = str(value)
        yield tag_number, text


def _checksum_split(raw):
    """Return ``(bytes_covered_by_checksum, declared_checksum)``."""
    if not raw.endswith(SOH_BYTES):
        raise FrameError("frame does not end with SOH")
    marker = SOH_BYTES + b"10="
    index = raw.rfind(marker)
    if index < 0:
        raise FrameError("checksum field is missing")
    covered = raw[:index + 1]
    field = raw[index + 1:]
    if not field.startswith(b"10=") or not field.endswith(SOH_BYTES):
        raise FrameError("checksum field is malformed")
    declared = field[3:-1]
    if len(declared) != 3 or not declared.isdigit():
        raise FrameError("checksum must be three digits")
    return covered, declared.decode("ascii")


def checksum_value(raw):
    """Integer checksum of the frame, from the bytes that tag 10 covers."""
    covered, _declared = _checksum_split(raw)
    return sum(covered) % 256


def checksum_ok(raw):
    """True when tag 10 equals the modulo-256 sum of the preceding bytes."""
    try:
        covered, declared = _checksum_split(raw)
    except FrameError:
        return False
    return "{:03d}".format(sum(covered) % 256) == declared


def body_length_parts(raw):
    """Return ``(declared, actual)`` body length.

    ``actual`` counts bytes after tag 9's trailing SOH through the SOH
    that precedes tag 10.
    """
    if not raw.startswith(b"8="):
        raise FrameError("BeginString is not first")
    first_soh = raw.find(SOH_BYTES)
    if first_soh < 0 or not raw.startswith(b"9=", first_soh + 1):
        raise FrameError("BodyLength is not second")
    second_soh = raw.find(SOH_BYTES, first_soh + 1)
    if second_soh < 0:
        raise FrameError("BodyLength is not terminated")
    declared_text = raw[first_soh + 3:second_soh]
    if not declared_text.isdigit():
        raise FrameError("BodyLength is not an integer")
    marker = SOH_BYTES + b"10="
    checksum_at = raw.rfind(marker)
    if checksum_at < 0 or checksum_at < second_soh:
        raise FrameError("checksum field is missing")
    actual = checksum_at - second_soh
    return int(declared_text), actual


def body_length_ok(raw):
    """True when tag 9 matches the FIX body-length byte count."""
    try:
        declared, actual = body_length_parts(raw)
    except FrameError:
        return False
    return declared == actual
