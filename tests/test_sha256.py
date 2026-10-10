import copy
import hashlib
import json
import struct
import unittest
from pathlib import Path

from hub.sha256 import ResumableSHA256


class ResumableSHA256Tests(unittest.TestCase):
    def test_saved_state_matches_legacy_layout(self):
        vectors = json.loads((Path(__file__).parent / 'fixtures' / 'sha256-legacy.json').read_text())
        for vector in vectors:
            with self.subTest(length=vector['length']):
                hasher = ResumableSHA256()
                hasher.update(bytes.fromhex(vector['data']))
                expected = bytearray.fromhex(vector['state'])
                # OpenSSL leaves previously processed bytes in the unused
                # buffer. They are not part of the resumable hash state.
                pending = vector['length'] % 64
                expected[40 + pending:104] = b'\x00' * (64 - pending)
                self.assertEqual(hasher.get_state(), expected)

    def test_legacy_states_resume_without_rebuilding_history(self):
        vectors = json.loads((Path(__file__).parent / 'fixtures' / 'sha256-legacy.json').read_text())
        for vector in vectors:
            with self.subTest(length=vector['length']):
                state = bytes.fromhex(vector['state'])
                hasher = ResumableSHA256(state)
                self.assertEqual(hasher.digest().hex(), vector['digest'])
                self.assertEqual(hasher.get_state(), state)
                self.assertEqual(copy.copy(hasher).get_state(), state)
                hasher.update(b'')
                self.assertEqual(hasher.get_state(), state)
                hasher.update(b' continuation')
                self.assertEqual(hasher.digest().hex(), vector['continued_digest'])

    def test_chunk_boundaries_and_saved_states(self):
        data = bytes(range(256)) * 40
        for chunk_size in (1, 7, 55, 56, 63, 64, 65, 127, 128, 4096, len(data)):
            with self.subTest(chunk_size=chunk_size):
                hasher = ResumableSHA256()
                expected = hashlib.sha256()
                for offset in range(0, len(data), chunk_size):
                    chunk = data[offset:offset + chunk_size]
                    hasher.update(chunk)
                    expected.update(chunk)
                    self.assertEqual(hasher.digest(), expected.digest())
                    hasher = ResumableSHA256(hasher.get_state())
                self.assertEqual(hasher.digest(), hashlib.sha256(data).digest())

    def test_legacy_bit_counter_carry(self):
        vectors = json.loads((Path(__file__).parent / 'fixtures' / 'sha256-counter.json').read_text())
        for vector in vectors:
            with self.subTest(byte_count=vector['byte_count']):
                hasher = ResumableSHA256(bytes.fromhex(vector['state']))
                self.assertEqual(hasher.digest().hex(), vector['digest'])
                hasher.update(b'y' * 64)
                self.assertEqual(hasher.digest().hex(), vector['continued_digest'])
                expected = bytearray.fromhex(vector['continued_state'])
                expected[72:104] = b'\x00' * 32
                self.assertEqual(hasher.get_state(), expected)

    def test_copy_and_digest_leave_original_usable(self):
        for length in (0, 1, 63, 64, 65):
            with self.subTest(length=length):
                data = b'x' * length
                hasher = ResumableSHA256()
                hasher.update(data)
                state = hasher.get_state()
                self.assertEqual(hasher.digest(), hasher.digest())
                self.assertEqual(hasher.get_state(), state)
                other = copy.copy(hasher)
                other.update(b'other')
                hasher.update(b'original')
                self.assertEqual(other.digest(), hashlib.sha256(data + b'other').digest())
                self.assertEqual(hasher.digest(), hashlib.sha256(data + b'original').digest())

    def test_known_million_byte_vector(self):
        hasher = ResumableSHA256()
        hasher.update(b'a' * 1000000)
        self.assertEqual(hasher.digest().hex(),
                         'cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0')

    def test_invalid_states_are_rejected(self):
        for size in (0, 1, 112, 119, 121, 128):
            with self.subTest(size=size), self.assertRaises(ValueError):
                ResumableSHA256(b'\x00' * size)
        for offset, value in ((32, 1), (32, 8), (104, 64), (104, 1), (108, 28)):
            state = bytearray(ResumableSHA256().get_state())
            struct.pack_into('<I', state, offset, value)
            with self.subTest(offset=offset, value=value), self.assertRaises(ValueError):
                ResumableSHA256(state)
