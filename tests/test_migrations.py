import array
import asyncio
import hashlib
import logging
import struct
from types import SimpleNamespace
from unittest.mock import Mock, patch, sentinel

import pytest
import rocksdb

from hub.db.common import DB_PREFIXES, DBError
from hub.db.migrators import migrate7to8, migrate8to9, migrate9to10, migrate10to11, migrate11to12
from hub.scribe.db import PrimaryDB
from hub.scribe.network import LBCRegTest
from hub.scribe.service import BlockchainProcessorService


MIGRATIONS = (migrate7to8, migrate8to9, migrate9to10, migrate10to11, migrate11to12)
ADDRESSES = (b'\x10' * 11, b'\x20' * 11, b'\x30' * 11)
CLAIMS = (b'A' * 20, b'B' * 20, b'C' * 20, b'D' * 20)
TX_HASHES = tuple(bytes([n + 1]) * 32 for n in range(5))
TX_COUNTS = (1, 3, 5)
BLOCK_HASHES = (b'g' * 32, b'p' * 32, b't' * 32)
HISTORIES = ((0, 2, 3), (1, 4), (2, 4))
TX_HEIGHTS = (0, 1, 1, 2, 2)


def address_status(history):
    wire_history = ''.join(f'{TX_HASHES[n][::-1].hex()}:{TX_HEIGHTS[n]}:' for n in history)
    return hashlib.sha256(wire_history.encode()).digest()


def legacy_rows(version, index_address_status=True, state_size=98):
    # Frozen wire layouts from the old fork (46a08e8), with the later derived
    # indexes added at their schema versions. Do not use today's row packers:
    # these fixtures must continue to represent databases written by older code.
    state = struct.pack(
        '>32sLL32sLLBBlll', bytes.fromhex(LBCRegTest.GENESIS_HASH), 2, 5, b't' * 32,
        4, 123456, int(index_address_status) << 1, version, 4, -1, -1
    )
    if state_size >= 98:
        state += struct.pack('>L', 1)
    if state_size == 102:
        state += struct.pack('>L', 2)
    rows = [(b's', state)]
    rows += [(b'T' + struct.pack('>L', height), struct.pack('>L', count))
             for height, count in enumerate(TX_COUNTS)]
    rows += [(b'X' + struct.pack('>L', n), tx_hash) for n, tx_hash in enumerate(TX_HASHES)]
    rows += [(b'N' + tx_hash, struct.pack('>L', n)) for n, tx_hash in enumerate(TX_HASHES)]
    rows += [(b'C' + struct.pack('>L', n), block_hash) for n, block_hash in enumerate(BLOCK_HASHES)]
    for address, history in zip(ADDRESSES, HISTORIES):
        chunks = ((1, history[:1]), (2, history[1:])) if version == 7 else ((0, history),)
        rows += [(b'x' + address + struct.pack('>L', height), array.array('I', chunk).tobytes())
                 for height, chunk in chunks]
        if version >= 8 and (version == 8 or index_address_status):
            rows.append((b'f' + struct.pack('>20s', address), address_status(history)))
    # Existing claim, UTXO and transaction records must survive an index rebuild.
    rows.append((b'E' + CLAIMS[0], struct.pack('>LHLHQBH', 2, 0, 2, 0, 100, 0, 4) + b'name'))
    rows.append((b'P\x00\x04name', struct.pack('>20sL', CLAIMS[0], 1)))
    rows.append((b'u' + ADDRESSES[0] + struct.pack('>LH', 2, 0), struct.pack('>Q', 100)))
    rows += [(b'V' + bytes([n + 70]) * 20, target)
             for n, target in enumerate((CLAIMS[0], CLAIMS[0], CLAIMS[1]))]
    amounts = (
        (CLAIMS[0], 1, 1, 0, 100), (CLAIMS[0], 2, 2, 1, 25),
        (CLAIMS[0], 2, 3, 2, 50), (CLAIMS[1], 1, 3, 3, 200),
        (CLAIMS[2], 1, 2, 4, 0), (CLAIMS[3], 2, 1, 4, 7),
    )
    rows += [(b'S' + struct.pack('>20sBLLH', claim, kind, height, tx_num, 0), struct.pack('>Q', amount))
             for claim, kind, height, tx_num, amount in amounts]
    if version >= 10:
        rows += [(b'j' + CLAIMS[0], struct.pack('>L', 2)), (b'j' + CLAIMS[1], struct.pack('>L', 1))]
    if version >= 11:
        rows += [(b'i' + claim, struct.pack('>QQ', amount, support))
                 for claim, amount, support in ((CLAIMS[0], 125, 25), (CLAIMS[2], 0, 0), (CLAIMS[3], 7, 7))]
    return rows


class DatabaseFixture:
    def __init__(self, path, version, index_address_status=True, state_size=98):
        path.mkdir()
        rows = legacy_rows(version, index_address_status, state_size)
        # Start without the newer column families. Opening the Hub must add them.
        legacy_db = rocksdb.DB(
            str(path / 'lbry-rocksdb'),
            rocksdb.Options(create_if_missing=True, create_missing_column_families=True, max_open_files=32),
            column_families={key[:1]: rocksdb.ColumnFamilyOptions() for key, _ in rows}
        )
        try:
            with legacy_db.write_batch(sync=True) as batch:
                for key, value in rows:
                    batch.put((legacy_db.get_column_family(key[:1]), key), value)
        finally:
            legacy_db.close()
        self.db = PrimaryDB(LBCRegTest, str(path), max_open_files=32, index_address_status=index_address_status)
        self.db.open_db()
        asyncio.get_event_loop().run_until_complete(self.db._read_tx_counts())

    def reopen(self):
        self.db.close()
        self.db.open_db()
        asyncio.get_event_loop().run_until_complete(self.db._read_tx_counts())

    def snapshot(self):
        prefix_db = self.db.prefix_db
        return {
            prefix.value: [(key[1], value) for key, value in
                           prefix_db.iterator(prefix.value, prefix_db.column_families[prefix.value])]
            for prefix in DB_PREFIXES
        }


@pytest.fixture
def database(tmp_path):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    opened = []

    def create(version, index_address_status=True, state_size=98):
        fixture = DatabaseFixture(tmp_path / str(len(opened)), version, index_address_status, state_size)
        opened.append(fixture)
        return fixture

    try:
        yield create
    finally:
        for fixture in opened:
            fixture.db.close()
        loop.run_until_complete(loop.shutdown_default_executor())
        loop.close()
        asyncio.set_event_loop(None)


def run_startup_migrations(db):
    # Exercise the real startup dispatch, stopping before daemon or prefetch work.
    service = Mock(spec=BlockchainProcessorService)
    service.db = db
    service.last_state = db.prefix_db.db_state.get()
    service.env = SimpleNamespace(index_address_status=db._index_address_status,
                                  rebuild_address_status_from_height=-1)
    service.log = logging.getLogger(__name__)
    service.start_prometheus = Mock(return_value=sentinel.prometheus)
    service.daemon = Mock()
    service.daemon.height.return_value = sentinel.daemon_height
    tasks = BlockchainProcessorService._iter_start_tasks(service)
    try:
        assert next(tasks) is sentinel.prometheus
        assert next(tasks) is sentinel.daemon_height
    finally:
        tasks.close()
    assert (service.height, service.tx_count, service.tip) == (2, 5, b't' * 32)


def assert_upgraded(fixture):
    fixture.reopen()
    db = fixture.db
    prefix_db = db.prefix_db
    assert db.db_version == 12
    assert (db.db_height, db.db_tx_count, db.db_tip) == (2, 5, b't' * 32)
    assert list(db.tx_counts) == list(TX_COUNTS)
    assert dict(prefix_db.reposted_count.iterate()) == {(CLAIMS[0],): (2,), (CLAIMS[1],): (1,)}
    assert dict(prefix_db.effective_amount.iterate()) == {
        (CLAIMS[0],): (125, 25), (CLAIMS[2],): (0, 0), (CLAIMS[3],): (7, 7)
    }
    assert dict(prefix_db.future_effective_amount.iterate()) == {
        (CLAIMS[0],): (175,), (CLAIMS[1],): (200,), (CLAIMS[2],): (0,), (CLAIMS[3],): (7,)
    }
    statuses = dict(prefix_db.hashX_status.iterate(deserialize_value=False))
    expected = {(address.ljust(20, b'\0'),): address_status(history)
                for address, history in zip(ADDRESSES, HISTORIES)}
    assert statuses == (expected if db._index_address_status else {})
    for address, history in zip(ADDRESSES, HISTORIES):
        assert list(prefix_db.hashX_history.iterate(prefix=(address,), include_key=False)) == [array.array('I', history)]


@pytest.mark.parametrize('version', range(7, 12))
@pytest.mark.parametrize('index_address_status', (False, True))
def test_startup_upgrades_and_reopens(database, version, index_address_status):
    fixture = database(version, index_address_status)
    before = fixture.snapshot()
    run_startup_migrations(fixture.db)
    assert_upgraded(fixture)
    after = fixture.snapshot()
    for prefix in (b'E', b'P', b'u', b'N', b'X', b'T', b'C', b'V', b'S'):
        assert after[prefix] == before[prefix]
    run_startup_migrations(fixture.db)
    fixture.reopen()
    assert fixture.snapshot() == after


@pytest.mark.parametrize('state_size', (94, 98, 102))
def test_legacy_state_layouts(database, state_size):
    fixture = database(7, state_size=state_size)
    run_startup_migrations(fixture.db)
    assert_upgraded(fixture)
    state = fixture.db.prefix_db.db_state.get()
    assert state.wall_time == 123456
    assert state.es_sync_height == (2 if state_size == 94 else 1)
    assert state.hashX_status_last_indexed_height == 2


def test_version_7_repairs_missing_stale_and_matching_statuses(database):
    fixture = database(7)
    prefix_db = fixture.db.prefix_db
    prefix_db.hashX_status.stash_put((ADDRESSES[1],), (b'wrong'.ljust(32, b'!'),))
    prefix_db.hashX_status.stash_put((ADDRESSES[2],), (address_status(HISTORIES[2]),))
    prefix_db.unsafe_commit()
    migrate7to8.migrate(fixture.db)
    fixture.reopen()
    assert fixture.db.db_version == 8
    assert dict(fixture.db.prefix_db.hashX_status.iterate(deserialize_value=False)) == {
        (address.ljust(20, b'\0'),): address_status(history) for address, history in zip(ADDRESSES, HISTORIES)
    }


def test_rebuild_address_index_after_upgrade(database):
    fixture = database(7, index_address_status=False)
    run_startup_migrations(fixture.db)
    assert_upgraded(fixture)
    fixture.db._rebuild_hashX_status_index(0)
    assert_upgraded(fixture)
    for address, history in zip(ADDRESSES, HISTORIES):
        hasher = fixture.db.prefix_db.hashX_history_hasher.get(address).hasher
        assert hasher.digest() == address_status(history)


@pytest.mark.parametrize('migration', MIGRATIONS, ids=lambda m: m.__name__.rsplit('.', 1)[-1])
@pytest.mark.parametrize('after_commit', (False, True), ids=('before-commit', 'after-commit'))
def test_restart_at_each_migration_batch(database, migration, after_commit):
    # Seed stale derived data to exercise the clear, rebuild and version commits.
    baseline = database(migration.FROM_VERSION, index_address_status=False)
    target = {9: 'reposted_count', 10: 'effective_amount', 11: 'future_effective_amount'}.get(migration.FROM_VERSION)

    def seed_stale(fixture):
        if target:
            row = getattr(fixture.db.prefix_db, target)
            row.stash_put((b'?' * 20,), (999, 1) if target == 'effective_amount' else (999,))
            fixture.db.prefix_db.unsafe_commit()

    seed_stale(baseline)
    with patch.object(baseline.db.prefix_db, 'unsafe_commit', wraps=baseline.db.prefix_db.unsafe_commit) as commits:
        migration.migrate(baseline.db)
    commit_count = commits.call_count
    assert commit_count > 0
    run_startup_migrations(baseline.db)
    assert_upgraded(baseline)
    expected = baseline.snapshot()

    for stop_after in range(1, commit_count + 1):
        fixture = database(migration.FROM_VERSION, index_address_status=False)
        seed_stale(fixture)
        original_commit = fixture.db.prefix_db.unsafe_commit
        calls = 0

        def interrupt():
            nonlocal calls
            calls += 1
            if calls == stop_after and not after_commit:
                raise InterruptedError('simulated stop before a batch')
            original_commit()
            if calls == stop_after:
                raise InterruptedError('simulated stop after a durable batch')

        with patch.object(fixture.db.prefix_db, 'unsafe_commit', side_effect=interrupt):
            with pytest.raises(InterruptedError):
                migration.migrate(fixture.db)
        fixture.reopen()
        assert fixture.db.db_version in (migration.FROM_VERSION, migration.TO_VERSION)
        run_startup_migrations(fixture.db)
        assert_upgraded(fixture)
        assert fixture.snapshot() == expected


def test_block_rollback_after_upgrade_and_reopen(database):
    fixture = database(7)
    run_startup_migrations(fixture.db)
    assert_upgraded(fixture)
    prefix_db = fixture.db.prefix_db
    prefix_db.claim_takeover.stash_delete(('name',), (CLAIMS[0], 1))
    prefix_db.claim_takeover.stash_put(('name',), (CLAIMS[1], 3))
    prefix_db.utxo.stash_delete((ADDRESSES[0], 2, 0), (100,))
    block_hash = b'next block'.ljust(32, b'!')
    prefix_db.tx_count.stash_put((3,), (5,))
    prefix_db.block_hash.stash_put((3,), (block_hash,))
    fixture.db.db_height = 3
    fixture.db.db_tip = block_hash
    fixture.db.write_db_state()
    prefix_db.commit(3, block_hash)
    fixture.reopen()
    assert fixture.db.prefix_db.claim_takeover.get('name') == (CLAIMS[1], 3)
    assert fixture.db.prefix_db.utxo.get(ADDRESSES[0], 2, 0) is None
    fixture.db.assert_rollback_supported(3, block_hash)
    fixture.db.prefix_db.rollback(3, block_hash)
    fixture.reopen()
    assert fixture.db.prefix_db.claim_takeover.get('name') == (CLAIMS[0], 1)
    assert fixture.db.prefix_db.utxo.get(ADDRESSES[0], 2, 0) == (100,)
    assert fixture.db.db_height == 2


@pytest.mark.parametrize('version', range(7, 12))
def test_reorg_cannot_cross_schema_upgrade(database, version):
    fixture = database(version)
    # A real legacy undo record contains the DB state it would restore. Its
    # source-index changes do not cover indexes introduced by later migrations.
    key = b'S' + struct.pack('>20sBLLH', CLAIMS[0], 2, 2, 1, 0)
    value = struct.pack('>Q', 25)
    old_state = legacy_rows(version)[0][1]
    undo = struct.pack('>BLL', 0, len(key), len(value)) + key + value
    undo += struct.pack('>BLL', 0, 1, len(old_state)) + b's' + old_state
    previous_state = bytearray(old_state)
    struct.pack_into('>LL', previous_state, 32, 1, 3)
    previous_state[40:72] = BLOCK_HASHES[1]
    undo += struct.pack('>BLL', 1, 1, len(previous_state)) + b's' + previous_state
    fixture.db.prefix_db.undo.stash_put((2, b't' * 32), (undo,))
    fixture.db.prefix_db.unsafe_commit()
    run_startup_migrations(fixture.db)
    assert_upgraded(fixture)
    before = fixture.snapshot()
    fixture.db.block_hashes = list(BLOCK_HASHES)
    service = Mock(spec=BlockchainProcessorService)
    service.db = fixture.db
    service.height = 2
    with pytest.raises(DBError, match='schema'):
        BlockchainProcessorService.backup_block(service)
    assert service.height == 2
    assert fixture.db.db_height == 2
    assert fixture.db.block_hashes == list(BLOCK_HASHES)
    assert fixture.snapshot() == before


@pytest.mark.parametrize('undo', (None, b'bad', struct.pack('>BLL', 1, 1, 3) + b'sbad'),
                         ids=('missing', 'truncated-operation', 'truncated-state'))
def test_missing_or_malformed_undo_is_rejected(database, undo):
    fixture = database(11)
    if undo is not None:
        fixture.db.prefix_db.undo.stash_put((2, b't' * 32), (undo,))
        fixture.db.prefix_db.unsafe_commit()
    before = fixture.snapshot()
    with pytest.raises(DBError, match='cannot roll back block 2'):
        fixture.db.assert_rollback_supported(2, b't' * 32)
    assert fixture.snapshot() == before


@pytest.mark.parametrize('version', range(7, 12))
def test_migrations_with_empty_indexes(database, version):
    fixture = database(version)
    prefix_db = fixture.db.prefix_db
    for name in ('hashX_history', 'hashX_status', 'repost', 'active_amount', 'reposted_count', 'effective_amount'):
        row = getattr(prefix_db, name)
        prefix_db.multi_delete(list(row.iterate(deserialize_key=False, deserialize_value=False)))
    prefix_db.unsafe_commit()
    run_startup_migrations(fixture.db)
    fixture.reopen()
    assert fixture.db.db_version == 12
    for name in ('hashX_status', 'reposted_count', 'effective_amount', 'future_effective_amount'):
        assert list(getattr(fixture.db.prefix_db, name).iterate()) == []
