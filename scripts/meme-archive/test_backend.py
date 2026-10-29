"""Real RFC 6330 roundtrips against the bundled WASM, requiring only Node.

Run: python -B -m unittest discover -s scripts/meme-archive -p test_backend.py
"""
import base64
import json
from pathlib import Path
import random
import subprocess
import unittest

HERE = Path(__file__).resolve().parent


def b64(data):
    return base64.b64encode(data).decode("ascii")


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.process = subprocess.Popen(
            ["node", str(HERE / "backend.mjs")], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8")

    def tearDown(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        stderr = self.process.stderr.read()
        self.process.stdout.close()
        self.process.stderr.close()
        self.assertEqual(self.process.returncode, 0, stderr)

    def raw(self, op, **values):
        self.process.stdin.write(json.dumps(dict(op=op, **values)) + "\n")
        self.process.stdin.flush()
        response = self.process.stdout.readline()
        self.assertTrue(response, "Backend exited without a JSON reply")
        return json.loads(response)

    def request(self, op, **values):
        response = self.raw(op, **values)
        self.assertNotIn("error", response)
        return response

    def test_shuffled_repair_only_multiblock_recovery(self):
        """Recover without any original source symbol, across uneven blocks."""
        data = random.Random(9373).randbytes(256 * 2179 + 7)
        meta = self.request("init_encoder", data=b64(data), symbol_size=256)
        self.assertEqual(meta["source_counts"], [727, 727, 726])
        oti = base64.b64decode(meta["oti"])
        self.assertEqual(oti, bytes.fromhex("000008830700010003000101"))
        self.request("init_decoder", oti=meta["oti"])
        z = meta["block_count"]
        largest = max(meta["source_counts"])
        indices = list(range(largest * z, (largest * 2 + 20) * z))
        random.Random(811).shuffle(indices)
        recovered = None
        for index in indices:
            packet = self.request("packet", index=index)["packet"]
            recovered = self.request("decode", packet=packet)["data"]
            if recovered is not None:
                break
        self.assertIsNotNone(recovered)
        self.assertEqual(base64.b64decode(recovered), data)

    def test_systematic_source_layout_padding_and_random_access(self):
        data = random.Random(41).randbytes(131304)
        meta = self.request("init_encoder", data=b64(data), symbol_size=512)
        self.assertEqual(meta["source_counts"], [257])
        for index in (0, 122, 256):
            packet = base64.b64decode(self.request("packet", index=index)["packet"])
            self.assertEqual(int.from_bytes(packet[:4], "big"), index)
            self.assertEqual(packet[4:], data[index * 512:(index + 1) * 512].ljust(512, b"\0"))
        for index in (1_000_000, 0xffffff):
            first = self.request("packet", index=index)["packet"]
            self.assertEqual(first, self.request("packet", index=index)["packet"])
            self.assertEqual(int.from_bytes(base64.b64decode(first)[:4], "big"), index)
        self.assertIn("error", self.raw("packet", index=0x1000000))

    def test_malformed_inputs_fail_cleanly(self):
        for message in (dict(op="packet", index=0),
                        dict(op="init_encoder", data="!", symbol_size=512),
                        dict(op="init_encoder", data="", symbol_size=512),
                        dict(op="init_encoder", data=b64(b"abc"), symbol_size=0),
                        dict(op="init_decoder", oti=b64(bytes(12))),
                        dict(op="unknown")):
            self.assertIn("error", self.raw(**message))
        meta = self.request("init_encoder", data=b64(b"abc"), symbol_size=64)
        oti = bytearray(base64.b64decode(meta["oti"]))
        oti[5] = 6  # Reserved RFC 6330 byte is zero, FEC ID is external.
        self.assertIn("error", self.raw("init_decoder", oti=b64(oti)))
        self.request("init_decoder", oti=meta["oti"])
        for packet in (b"", b"\0" * 4, b"\x01" + bytes(67)):
            self.assertIn("error", self.raw("decode", packet=b64(packet)))
        source = self.request("packet", index=0)["packet"]
        self.assertEqual(self.request("decode", packet=source)["data"], b64(b"abc"))

    def test_independent_native_rfc_packet_vectors(self):
        """Reference packets cross-checked with @davidcal/fec-raptorq 1.11.0.

        That separately packaged native RFC codec is a validation tool only;
        it is not installed or imported by the exporter or this test suite.
        """
        data = b"RFC 6330 meme archive test\n"
        meta = self.request("init_encoder", data=b64(data), symbol_size=16)
        self.assertEqual(base64.b64decode(meta["oti"]).hex(), "000000001b00001001000101")
        vectors = [
            "000000005246432036333330206d656d65206172",
            "00000001636869766520746573740a0000000000",
            "00000002a8e30150a48290a20ccedd6d65206172",
            "000000031054fec493b82a077df9044d6b98787e",
            "00000004e770f1d5f5cb2b2eb26ec73009e49b0a",
            "000000056eabafd30796b29d6b1cef4782336eb4",
        ]
        for index, expected in enumerate(vectors):
            actual = self.request("packet", index=index)["packet"]
            self.assertEqual(base64.b64decode(actual).hex(), expected)
        self.request("init_decoder", oti=meta["oti"])
        result = None
        for packet in reversed(vectors[2:]):
            result = self.request("decode", packet=b64(bytes.fromhex(packet)))["data"]
            if result is not None:
                break
        self.assertEqual(base64.b64decode(result), data)


if __name__ == "__main__":
    unittest.main()
