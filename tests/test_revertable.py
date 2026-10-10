import unittest
import hashlib
import json
import tempfile
import shutil
from pathlib import Path
from hub.db.revertable import RevertableOpStack, RevertableDelete, RevertablePut, OpStackIntegrity
from hub.db.prefixes import ClaimToTXOPrefixRow, PrefixDB


class TestRevertableOpStack(unittest.TestCase):
    def setUp(self):
        class FakeDB(dict):
            def multi_get(self, keys):
                return map(self.get, keys)
        self.fake_db = FakeDB()
        self.stack = RevertableOpStack(self.fake_db.get, self.fake_db.multi_get)

    def tearDown(self) -> None:
        self.stack.clear()
        self.fake_db.clear()

    def process_stack(self):
        self.stack.validate_and_apply_stashed_ops()
        for op in self.stack:
            if op.is_put:
                self.fake_db[op.key] = op.value
            else:
                self.fake_db.pop(op.key)
        self.stack.clear()

    def update(self, key1: bytes, value1: bytes, key2: bytes, value2: bytes):
        self.stack.append_op(RevertableDelete(key1, value1))
        self.stack.append_op(RevertablePut(key2, value2))

    def test_simplify(self):
        key1 = ClaimToTXOPrefixRow.pack_key(b'\x01' * 20)
        key2 = ClaimToTXOPrefixRow.pack_key(b'\x02' * 20)
        key3 = ClaimToTXOPrefixRow.pack_key(b'\x03' * 20)
        key4 = ClaimToTXOPrefixRow.pack_key(b'\x04' * 20)

        val1 = ClaimToTXOPrefixRow.pack_value(1, 0, 1, 0, 1, False, 'derp')
        val2 = ClaimToTXOPrefixRow.pack_value(1, 0, 1, 0, 1, False, 'oops')
        val3 = ClaimToTXOPrefixRow.pack_value(1, 0, 1, 0, 1, False, 'other')

        # check that we can't delete a non existent value
        with self.assertRaises(OpStackIntegrity):
            self.stack.append_op(RevertableDelete(key1, val1))

        self.stack.append_op(RevertablePut(key1, val1))
        self.assertEqual(1, len(self.stack))
        self.stack.append_op(RevertableDelete(key1, val1))
        self.assertEqual(0, len(self.stack))

        self.stack.append_op(RevertablePut(key1, val1))
        self.assertEqual(1, len(self.stack))
        # try to delete the wrong value
        with self.assertRaises(OpStackIntegrity):
            self.stack.append_op(RevertableDelete(key2, val2))

        self.stack.append_op(RevertableDelete(key1, val1))
        self.assertEqual(0, len(self.stack))
        self.stack.append_op(RevertablePut(key2, val3))
        self.assertEqual(1, len(self.stack))

        self.process_stack()

        self.assertDictEqual({key2: val3}, self.fake_db)

        # check that we can't put on top of the existing stored value
        with self.assertRaises(OpStackIntegrity):
            self.stack.append_op(RevertablePut(key2, val1))

        self.assertEqual(0, len(self.stack))
        self.stack.append_op(RevertableDelete(key2, val3))
        self.assertEqual(1, len(self.stack))
        self.stack.append_op(RevertablePut(key2, val3))
        self.assertEqual(0, len(self.stack))

        self.update(key2, val3, key2, val1)
        self.assertEqual(2, len(self.stack))

        self.process_stack()
        self.assertDictEqual({key2: val1}, self.fake_db)

        self.update(key2, val1, key2, val2)
        self.assertEqual(2, len(self.stack))
        self.update(key2, val2, key2, val3)
        self.update(key2, val3, key2, val2)
        self.update(key2, val2, key2, val3)
        self.update(key2, val3, key2, val2)
        with self.assertRaises(OpStackIntegrity):
            self.update(key2, val3, key2, val2)
        self.update(key2, val2, key2, val3)
        self.assertEqual(2, len(self.stack))
        self.stack.append_op(RevertableDelete(key2, val3))
        self.process_stack()
        self.assertDictEqual({}, self.fake_db)

        self.stack.append_op(RevertablePut(key2, val3))
        self.process_stack()
        with self.assertRaises(OpStackIntegrity):
            self.update(key2, val2, key2, val2)
        self.update(key2, val3, key2, val2)
        self.assertDictEqual({key2: val3}, self.fake_db)
        undo = self.stack.get_undo_ops()
        self.process_stack()
        self.assertDictEqual({key2: val2}, self.fake_db)
        self.stack.apply_packed_undo_ops(undo)
        self.process_stack()
        self.assertDictEqual({key2: val3}, self.fake_db)


class TestRevertablePrefixDB(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db = PrefixDB(self.tmp_dir, max_open_files=32)

    def tearDown(self) -> None:
        if self.db is not None:
            self.db.close()
        shutil.rmtree(self.tmp_dir)

    def reopen(self):
        self.db.close()
        self.db = None
        self.db = PrefixDB(self.tmp_dir, max_open_files=32)

    def test_legacy_history_hash_survives_update_reopen_and_rollback(self):
        vectors = json.loads((Path(__file__).parent / 'fixtures' / 'sha256-legacy.json').read_text())
        row = self.db.hashX_history_hasher
        for index, vector in enumerate(vectors):
            self.db.stash_raw_put(row.pack_key(bytes([index]) * 11), bytes.fromhex(vector['state']))
        self.db.commit(100, b'a' * 32)
        self.reopen()

        row = self.db.hashX_history_hasher
        for index, vector in enumerate(vectors):
            address = bytes([index]) * 11
            original = row.get(address).hasher
            self.assertEqual(original.digest().hex(), vector['digest'])
            row.stash_delete((address,), (original,))
            original.update(b' continuation')
            row.stash_put((address,), (original,))
        self.db.commit(101, b'b' * 32)
        self.reopen()

        for index, vector in enumerate(vectors):
            hasher = self.db.hashX_history_hasher.get(bytes([index]) * 11).hasher
            self.assertEqual(hasher.digest().hex(), vector['continued_digest'])
            hasher.update(b' more')
            self.assertEqual(hasher.digest(), hashlib.sha256(
                bytes.fromhex(vector['data']) + b' continuation more').digest())

        self.db.rollback(101, b'b' * 32)
        self.reopen()
        for index, vector in enumerate(vectors):
            row = self.db.hashX_history_hasher
            self.assertEqual(row.get(bytes([index]) * 11, deserialize_value=False), bytes.fromhex(vector['state']))
            self.assertEqual(row.get(bytes([index]) * 11).hasher.digest().hex(), vector['digest'])

    def test_rollback_after_reopen(self):
        name = 'persisted-claim'
        claim_hash = b'\x01' * 20
        tx_hash = b'\x02' * 32
        first_block = b'\x03' * 32
        second_block = b'\x04' * 32

        self.db.claim_takeover.stash_put((name,), (claim_hash, 100))
        self.db.tx_num.stash_put((tx_hash,), (7,))
        self.db.commit(100, first_block)
        self.reopen()
        self.assertEqual((claim_hash, 100), self.db.claim_takeover.get(name))
        self.assertEqual((7,), self.db.tx_num.get(tx_hash))

        self.db.claim_takeover.stash_delete((name,), (claim_hash, 100))
        self.db.claim_takeover.stash_put((name,), (claim_hash, 101))
        self.db.tx_num.stash_delete((tx_hash,), (7,))
        self.db.commit(101, second_block)
        self.reopen()
        self.assertEqual((claim_hash, 101), self.db.claim_takeover.get(name))
        self.assertIsNone(self.db.tx_num.get(tx_hash))

        self.db.rollback(101, second_block)
        self.reopen()
        self.assertEqual((claim_hash, 100), self.db.claim_takeover.get(name))
        self.assertEqual((7,), self.db.tx_num.get(tx_hash))
        self.db.rollback(100, first_block)
        self.reopen()
        self.assertIsNone(self.db.claim_takeover.get(name))
        self.assertIsNone(self.db.tx_num.get(tx_hash))

    def test_secondary_catches_up_after_commit_and_rollback(self):
        name = 'secondary-claim'
        claim_hash = b'\x05' * 20
        block_hash = b'\x06' * 32
        with tempfile.TemporaryDirectory() as secondary_dir:
            secondary = PrefixDB(self.tmp_dir, secondary_path=secondary_dir)
            try:
                self.assertIsNone(secondary.claim_takeover.get(name))
                self.db.claim_takeover.stash_put((name,), (claim_hash, 100))
                self.db.commit(100, block_hash)
                self.assertIsNone(secondary.claim_takeover.get(name))
                secondary.try_catch_up_with_primary()
                self.assertEqual((claim_hash, 100), secondary.claim_takeover.get(name))

                self.db.rollback(100, block_hash)
                self.assertEqual((claim_hash, 100), secondary.claim_takeover.get(name))
                secondary.try_catch_up_with_primary()
                self.assertIsNone(secondary.claim_takeover.get(name))
            finally:
                secondary.close()

    def test_rollback(self):
        name = 'derp'
        claim_hash1 = 20 * b'\x00'
        claim_hash2 = 20 * b'\x01'
        claim_hash3 = 20 * b'\x02'

        takeover_height = 10000000

        self.assertIsNone(self.db.claim_takeover.get(name))
        self.db.claim_takeover.stash_put((name,), (claim_hash1, takeover_height))
        self.assertIsNone(self.db.claim_takeover.get(name))
        self.assertEqual(10000000, self.db.claim_takeover.get_pending(name).height)

        self.db.commit(10000000, b'\x00' * 32)
        self.assertEqual(10000000, self.db.claim_takeover.get(name).height)

        self.db.claim_takeover.stash_delete((name,), (claim_hash1, takeover_height))
        self.db.claim_takeover.stash_put((name,), (claim_hash2, takeover_height + 1))
        self.db.claim_takeover.stash_delete((name,), (claim_hash2, takeover_height + 1))
        self.db.commit(10000001, b'\x01' * 32)
        self.assertIsNone(self.db.claim_takeover.get(name))
        self.db.claim_takeover.stash_put((name,), (claim_hash3, takeover_height + 2))
        self.db.commit(10000002, b'\x02' * 32)
        self.assertEqual(10000002, self.db.claim_takeover.get(name).height)

        self.db.claim_takeover.stash_delete((name,), (claim_hash3, takeover_height + 2))
        self.db.claim_takeover.stash_put((name,), (claim_hash2, takeover_height + 3))
        self.db.commit(10000003, b'\x03' * 32)
        self.assertEqual(10000003, self.db.claim_takeover.get(name).height)

        self.db.rollback(10000003, b'\x03' * 32)
        self.assertEqual(10000002, self.db.claim_takeover.get(name).height)
        self.db.rollback(10000002, b'\x02' * 32)
        self.assertIsNone(self.db.claim_takeover.get(name))
        self.db.rollback(10000001, b'\x01' * 32)
        self.assertEqual(10000000, self.db.claim_takeover.get(name).height)
        self.db.rollback(10000000, b'\x00' * 32)
        self.assertIsNone(self.db.claim_takeover.get(name))

    def test_hub_db_iterator(self):
        name = 'derp'
        claim_hash0 = 20 * b'\x00'
        claim_hash1 = 20 * b'\x01'
        claim_hash2 = 20 * b'\x02'
        claim_hash3 = 20 * b'\x03'
        overflow_value = 0xffffffff
        self.db.claim_expiration.stash_put((99, 999, 0), (claim_hash0, name))
        self.db.claim_expiration.stash_put((100, 1000, 0), (claim_hash1, name))
        self.db.claim_expiration.stash_put((100, 1001, 0), (claim_hash2, name))
        self.db.claim_expiration.stash_put((101, 1002, 0), (claim_hash3, name))
        self.db.claim_expiration.stash_put((overflow_value - 1, 1003, 0), (claim_hash3, name))
        self.db.claim_expiration.stash_put((overflow_value, 1004, 0), (claim_hash3, name))
        self.db.tx_num.stash_put((b'\x00' * 32,), (101,))
        self.db.claim_takeover.stash_put((name,), (claim_hash3, 101))
        self.db.db_state.stash_put((), (b'n?\xcf\x12\x99\xd4\xec]y\xc3\xa4\xc9\x1dbJJ\xcf\x9e.\x17=\x95\xa1\xa0POgvihuV', 0, 1, b'VuhivgOP\xa0\xa1\x95=\x17.\x9e\xcfJJb\x1d\xc9\xa4\xc3y]\xec\xd4\x99\x12\xcf?n', 1, 0, 1, 7, 1, -1, -1, 0, 0, 0))
        self.db.unsafe_commit()

        state = self.db.db_state.get()
        self.assertEqual(b'n?\xcf\x12\x99\xd4\xec]y\xc3\xa4\xc9\x1dbJJ\xcf\x9e.\x17=\x95\xa1\xa0POgvihuV', state.genesis)

        self.assertListEqual(
            [], list(self.db.claim_expiration.iterate(prefix=(98,)))
        )
        self.assertListEqual(
            list(self.db.claim_expiration.iterate(start=(98,), stop=(99,))),
            list(self.db.claim_expiration.iterate(prefix=(98,)))
        )
        self.assertListEqual(
            list(self.db.claim_expiration.iterate(start=(99,), stop=(100,))),
            list(self.db.claim_expiration.iterate(prefix=(99,)))
        )
        self.assertListEqual(
            [
                ((99, 999, 0), (claim_hash0, name)),
            ], list(self.db.claim_expiration.iterate(prefix=(99,)))
        )
        self.assertListEqual(
            [
                ((100, 1000, 0), (claim_hash1, name)),
                ((100, 1001, 0), (claim_hash2, name))
            ], list(self.db.claim_expiration.iterate(prefix=(100,)))
        )
        self.assertListEqual(
            list(self.db.claim_expiration.iterate(start=(100,), stop=(101,))),
            list(self.db.claim_expiration.iterate(prefix=(100,)))
        )
        self.assertListEqual(
            [
                ((overflow_value - 1, 1003, 0), (claim_hash3, name))
            ], list(self.db.claim_expiration.iterate(prefix=(overflow_value - 1,)))
        )
        self.assertListEqual(
            [
                ((overflow_value, 1004, 0), (claim_hash3, name))
            ], list(self.db.claim_expiration.iterate(prefix=(overflow_value,)))
        )

    def test_hub_db_iterator_start_stop(self):
        tx_num = 101
        for x in range(255):
            claim_hash = 20 * chr(x).encode()
            self.db.active_amount.stash_put((claim_hash, 1, 200, tx_num, 1), (100000,))
            self.db.active_amount.stash_put((claim_hash, 1, 201, tx_num + 1, 1), (200000,))
            self.db.active_amount.stash_put((claim_hash, 1, 202, tx_num + 2, 1), (300000,))
            tx_num += 3
        self.db.unsafe_commit()

        def get_active_amount_as_of_height(claim_hash: bytes, height: int) -> int:
            for v in self.db.active_amount.iterate(
                    start=(claim_hash, 1, 0), stop=(claim_hash, 1, height + 1),
                    include_key=False, reverse=True):
                return v.amount
            return 0

        for x in range(255):
            claim_hash = 20 * chr(x).encode()
            self.assertEqual(300000, get_active_amount_as_of_height(claim_hash, 300))
            self.assertEqual(300000, get_active_amount_as_of_height(claim_hash, 203))
            self.assertEqual(300000, get_active_amount_as_of_height(claim_hash, 202))
            self.assertEqual(200000, get_active_amount_as_of_height(claim_hash, 201))
            self.assertEqual(100000, get_active_amount_as_of_height(claim_hash, 200))
            self.assertEqual(0, get_active_amount_as_of_height(claim_hash, 199))
