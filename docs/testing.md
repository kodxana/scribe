# Test baseline

The fork includes upstream Hub through `ebcc6e508660f72fe11d308ae4031971b5fbf782`,
including the rename from the `scribe` package to `hub`. The repository remains
`kodxana/scribe`, and its custom Docker publishing workflow is preserved.

## Database tests

With Docker and a Linux daemon available:

```sh
sh scripts/test.sh
```

On Windows, run the command from WSL. The image pins Python 3.9.23 by digest and
pins the test environment in `docker/test-requirements.txt`. It builds and
installs a Hub wheel, then runs outside the source directory as an unprivileged
user. `pip check` verifies the installed dependency metadata.

The test container has no network access, host mounts, or exposed ports. It is
limited to two CPUs and 4 GiB of memory, with a five-minute process timeout.
Dependency installation and compilation happen during the Docker build, which
does need network access. CI has a 45-minute job timeout.

The six tests in `tests/test_revertable.py` cover operation-stack integrity,
block commits and rollback, prefix/range/reverse iteration, persisted undo
records across reopening, and secondary readers catching up after commits and
rollbacks. The undo test helper applies upstream's staged operations before
checking the resulting database.

The 39 cases in `tests/test_migrations.py` cover startup upgrades from every
supported version (7 through 11) to version 12, with address indexing enabled
and disabled. Small fixtures encode legacy keys and 94-, 98-, and 102-byte state
records independently of the current serializers, starting without the newer
column families. Tests check transaction and
claim records, UTXOs, history/status hashes, repost counts, and active/future
amount totals after reopening the database. Exceptions injected before and
after each migration batch commit exercise restart behavior. Empty indexes,
stale derived rows, rebuilding address statuses after upgrading, and rollback of
a block written after upgrading are covered.

### Reorgs across a schema upgrade

Old undo records remain on disk, but they cannot safely undo indexes added by a
later schema. Before changing state, the block processor checks that the undo
record restores the current database version. A reorg reaching a block written
under an older schema stops with an explicit error; recovery requires a
compatible Hub snapshot or a resync. This protects against partially reverting
source data while leaving the new derived indexes unchanged. Blocks written
after the upgrade retain normal rollback support.

Results go to `ci-results/published/`: the Hub wheel, test log, JUnit report,
and installed package versions. Set `TEST_OUTPUT_DIR` to change the destination.

## Resolve and reorg tests

Use the matching SDK checkout, including RPC cancellation cleanup and the
shared protobuf 3.20.3 requirement:

```sh
git clone https://github.com/kodxana/lbry-sdk.git .ci/sdk
git -C .ci/sdk checkout 418cd5fac4e60be69b456c9d97a5e8cabb21c053
sh scripts/test-integration.sh .ci/sdk
```

CI pins this SDK revision. The runner builds the SDK's test image, which
downloads and checksums its regtest binaries, then installs this checkout's Hub
wheel over the SDK's pinned Hub. Tests import the installed Hub from a separate
working directory. They use the SDK's maintained `CommandTestCase` and async
runner; the unused, stale copy in `tests/testcase.py` has been removed.

Both projects pin protobuf 3.20.3 because the upstream 3.18.3 macOS wheel
crashes while importing the SDK's legacy claim messages, also reported in
[protobuf issue #10691](https://github.com/protocolbuffers/protobuf/issues/10691).
The generated message definitions are unchanged.

All 37 tests in `tests/test_resolve_command.py` run, covering claim resolution,
channel/short-ID handling, activation delays, supports, takeovers, expiration,
trending, and chain reorgs.

Elasticsearch 7.12.1 is pinned by image digest. Its container has no external
network, uses two CPUs and 2 GiB, and publishes no ports. The test container
shares only its loopback network, uses four CPUs and 4 GiB, and runs as an
unprivileged user. Nodes create temporary regtest data. No host database or
mainnet connection is used.

The suite has a 30-minute timeout, adjustable with `TEST_TIMEOUT` in seconds.
Results go to `ci-results/resolve-published/`, including the log, installed
package versions, Hub wheel, and coverage XML. Both containers are removed on
exit. Both runners preserve nonzero test exits.

## Compare the maintained RocksDB binding

By default both runners install `lbry-rocksdb==0.8.2` from PyPI. To test a
locally built Linux CPython 3.9 wheel, pass its path:

```sh
sh scripts/test.sh /path/to/lbry_rocksdb-0.8.2-cp39-cp39-linux_x86_64.whl
sh scripts/test-integration.sh .ci/sdk /path/to/lbry_rocksdb-0.8.2-cp39-cp39-linux_x86_64.whl
```

Results use the `local-wheel` suffix and record the supplied wheel's SHA-256.
Installation is offline and does not replace other dependencies.

CI runs both suites with both bindings. Its maintained binding comes from
[`kodxana/lbry-rocksdb` at `59cb269cc18e64991174f05a1fa9e9de25fbc2dd`](https://github.com/kodxana/lbry-rocksdb/commit/59cb269cc18e64991174f05a1fa9e9de25fbc2dd),
which releases live iterators and snapshots safely when a database closes.
That checkout builds its pinned native libraries and passes its binding suite
before the wheel reaches the Hub database job. The resolve job downloads and
tests that same wheel artifact. These workflows do not publish packages.

The default dependency in `setup.py` still selects PyPI's 0.8.2 wheel, which
does not include those close fixes. The maintained wheel must be supplied
explicitly until a versioned release is available; updating the CI pin alone
does not change ordinary Hub installations.

## Scope

This validates Linux x86-64 on Python 3.9. It does not establish Python 3.13
support. Migration tests use small synthetic legacy databases; they do not
measure mainnet-scale migration time or test power-loss recovery, and no real
wallet or mainnet database is opened. A production snapshot rehearsal is still
needed before deployment. The regtest suites also start with temporary data.
