"""Run with python -B -m unittest discover -s scripts/meme-archive -p test_protocol.py."""
import hashlib
import struct
import unittest
import zlib

from decode import DecodeSession, InsufficientPackets
from protocol import (HEADER_BYTES, b64encode, make_object, parse_oti,
                      parse_packet, unpack_object, wrap_packet)


def oti(length=600, size=64, blocks=1):
    return length.to_bytes(5, "big") + b"\0" + size.to_bytes(2, "big") + bytes((blocks, 0, 1, 1))


def packet(edition=b"1" * 16, config=None, esi=0, symbol=b"x" * 64):
    return wrap_packet(edition, config or oti(), b"\0" + esi.to_bytes(3, "big") + symbol)


def crc(data):
    return data[:-4] + struct.pack(">I", zlib.crc32(data[:-4]) & 0xFFFFFFFF)


class FakeBackend:
    def __init__(self, result=None):
        self.result = result
        self.calls = []

    def request(self, op, **kwargs):
        self.calls.append((op, kwargs))
        return {"data": b64encode(self.result) if self.result is not None and op == "decode" else None}


class ProtocolTests(unittest.TestCase):
    def test_deterministic_object_and_exact_roundtrip(self):
        raw = "Příliš žluťoučký kůň\r\n".encode() * 500
        first = make_object(raw)
        self.assertEqual(first, make_object(raw))
        self.assertEqual(first[45], 255)
        self.assertEqual(unpack_object(first), raw)

    def test_bounded_decompression_and_integrity(self):
        obj = make_object(b"z" * 10000)
        with self.assertRaisesRegex(ValueError, "exceeds"):
            unpack_object(obj, 200)
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            unpack_object(obj[:4] + bytes(32) + obj[36:])
        with self.assertRaises(ValueError):
            unpack_object(obj[:-1])
        with self.assertRaisesRegex(ValueError, "trailing"):
            unpack_object(obj + b"junk")
        with self.assertRaises(ValueError):
            unpack_object(obj[:-5] + bytes(5))

    def test_packet_compact_size_and_fields(self):
        data = packet(esi=123)
        parsed = parse_packet(data)
        self.assertEqual(len(data), HEADER_BYTES + 64)
        self.assertEqual(parsed.esi, 123)
        self.assertEqual(parsed.edition, b"1" * 16)
        self.assertEqual(parsed.oti, oti())
        self.assertEqual(parsed.packet[4:], b"x" * 64)

    def test_corrupt_unknown_and_truncated_headers(self):
        data = packet()
        for offset in (0, 2, 3, 4, 25, 38, len(data) - 1):
            mutated = bytearray(data)
            mutated[offset] ^= 1
            with self.assertRaises(ValueError):
                parse_packet(bytes(mutated))
        with self.assertRaises(ValueError):
            parse_packet(data[:-1])
        with self.assertRaisesRegex(ValueError, "exactly one"):
            parse_packet(crc(data[:-4] + b"x" + data[-4:]))

    def test_oti_rejects_reserved_profile_partition_and_limits(self):
        reserved = bytearray(oti())
        reserved[5] = 1
        with self.assertRaisesRegex(ValueError, "reserved"):
            parse_oti(bytes(reserved))
        for config in (oti(length=0), oti(size=0), oti(blocks=0), oti(length=5, blocks=2),
                       oti(length=6000000, size=64), oti()[:-1] + b"\2"):
            with self.assertRaises(ValueError):
                parse_oti(config)
        with self.assertRaisesRegex(ValueError, "limit"):
            parse_oti(oti(), max_transfer=500)
        outside = bytearray(packet())
        outside[33] = 1
        with self.assertRaisesRegex(ValueError, "source block"):
            parse_packet(crc(bytes(outside)))

    def test_mixed_editions_conflicts_and_duplicates(self):
        backend = FakeBackend()
        session = DecodeSession(backend)
        self.assertTrue(session.add(packet()))
        self.assertFalse(session.add(packet()))
        self.assertEqual(session.duplicates, 1)
        with self.assertRaisesRegex(ValueError, "Mixed editions"):
            session.add(packet(edition=b"2" * 16))
        with self.assertRaisesRegex(ValueError, "Conflicting payloads"):
            session.add(packet(symbol=b"y" * 64))
        with self.assertRaisesRegex(ValueError, "Conflicting RFC"):
            session.add(packet(config=oti(length=601)))
        with self.assertRaises(InsufficientPackets):
            session.finish()

    def test_selection_and_verified_result(self):
        raw = b"Original bytes\r\n"
        backend = FakeBackend(make_object(raw))
        session = DecodeSession(backend, edition=b"2" * 16)
        self.assertFalse(session.add(packet()))
        self.assertEqual(backend.calls, [])
        self.assertTrue(session.add(packet(edition=b"2" * 16)))
        self.assertEqual(session.finish(), raw)
        # Still reject mixtures after successfully reconstructing.
        other = DecodeSession(FakeBackend(make_object(raw)))
        other.add(packet())
        with self.assertRaisesRegex(ValueError, "Mixed editions"):
            other.add(packet(edition=b"2" * 16))


if __name__ == "__main__":
    unittest.main()
