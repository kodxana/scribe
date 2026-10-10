# Test baseline

The fork includes upstream Hub through `ebcc6e508660f72fe11d308ae4031971b5fbf782`,
including the rename from the `scribe` package to `hub`. The community repository
is now `kodxana/lbry-hub-ng` (formerly `kodxana/scribe`). Its custom Docker
publishing workflow is preserved.

## Database tests

With Docker and a Linux daemon available:

```sh
sh scripts/test.sh
```

On Windows, run the command from WSL. The image pins Python 3.13 by digest and
pins the test environment in `docker/test-requirements.txt`. It builds and
installs a Hub wheel, then runs outside the source directory as an unprivileged
user. `pip check` verifies the installed dependency metadata.

The test container has no network access, host mounts, or exposed ports. It is
limited to two CPUs and 4 GiB of memory, with a five-minute process timeout.
Dependency installation and compilation happen during the Docker build, which
does need network access. CI has a 45-minute job timeout.

The tests in `tests/test_revertable.py` cover operation-stack integrity,
block commits and rollback, prefix/range/reverse iteration, persisted undo
records across reopening, and secondary readers catching up after commits and
rollbacks. The undo test helper applies upstream's staged operations before
checking the resulting database.

The installed-distribution tests verify that the maintained binding is the only
RocksDB distribution present and that Hub's package metadata selects the
CPython 3.13 GitHub wheel. The runtime requires Linux x86-64 with glibc 2.35 or
newer; the installer no longer falls back to the abandoned binding.

Saved SHA-256 fixtures cover states from the old OpenSSL implementation, block
boundaries and bit counters. Database tests load those bytes, append history,
reopen the database and roll back to the original bytes. The standalone hash
tests also run on Python 3.9 for comparison; that job does not install the Hub.

RPC tests cover request completion, batch ordering and disconnects. Protobuf
tests compare captured descriptors and serialized messages with the regenerated
modules. CI separately checks reproducible generation from the vendored schemas.

The service shutdown tests in `tests/test_service.py` check that background
tasks finish their cleanup before databases and search clients close. They also
check that failed tasks are reported, normal shutdown preserves the search
index, and explicit index deletion waits for reader cleanup. The SDK separately
tests this ordering against a real temporary Elasticsearch index in regtest.

Session-manager tests in `tests/test_session_manager.py` cover cancellation of
maintenance loops and in-progress connection closes, failure of either loop,
partial startup, and failures while closing listeners or individual sessions.
An exited maintenance loop requests service shutdown after cleanup; normal
cancellation stays quiet. Slow task cleanup is not canceled a second time.
Connection-close errors are logged without skipping other connections.

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
shared protobuf 7.36.2 requirement:

```sh
git clone https://github.com/kodxana/lbry-sdk-ng.git .ci/sdk
git -C .ci/sdk checkout 89c4029bf54671148ecfccd47a6f76646f090cb1
sh scripts/test-integration.sh .ci/sdk
```

CI pins this SDK revision. The runner builds the SDK's test image, which
downloads and checksums its regtest binaries, then installs this checkout's Hub
wheel over the SDK's pinned Hub. During this image build, it replaces the Hub
distribution and removes `lbry-rocksdb` if present before resolving this Hub
wheel's dependencies. This prevents the old and new bindings from owning the
same files. The pinned SDK includes ordered search-index shutdown during teardown.
Tests import the installed Hub from a separate
working directory. They use the SDK's maintained `CommandTestCase` and async
runner; the unused, stale copy in `tests/testcase.py` has been removed.

Both projects pin protobuf 7.36.2 and use regenerated modules. Compatibility
fixtures preserve the deployed wire definitions, including legacy claims and
the Hub's result schema. See [schema generation](../hub/schema/README.md).

All 37 tests in `tests/test_resolve_command.py` run, covering claim resolution,
channel/short-ID handling, activation delays, supports, takeovers, expiration,
trending, and chain reorgs.

The same runner also tests session shutdown against a real local TCP connection
in `tests/test_session_lifecycle.py`. It requests a server banner, stops the
regtest node, and checks that the client disconnects, maintenance tasks finish,
and the session and listener registries are empty.

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

By default both runners install the hash-pinned `lbry-rocksdb-ng` 0.8.3 wheel
from [the GitHub release](https://github.com/kodxana/lbry-rocksdb-ng/releases/tag/v0.8.3).
To test a
locally built Linux CPython 3.13 wheel, pass its path:

```sh
sh scripts/test.sh /path/to/lbry_rocksdb_ng-0.8.3-cp313-cp313-manylinux_2_35_x86_64.whl
sh scripts/test-integration.sh .ci/sdk /path/to/lbry_rocksdb_ng-0.8.3-cp313-cp313-manylinux_2_35_x86_64.whl
```

Results use the `local-wheel` suffix and record the supplied wheel's SHA-256.
Installation is offline and does not replace other dependencies.

CI runs both suites with the published release and a binding rebuilt from
[`kodxana/lbry-rocksdb-ng` at `cdbe008312a191b3099065a94c470818b10d6d9d`](https://github.com/kodxana/lbry-rocksdb-ng/commit/cdbe008312a191b3099065a94c470818b10d6d9d),
which releases live iterators and snapshots safely when a database closes.
That checkout builds its pinned native libraries and passes its binding suite
before the wheel reaches the Hub database job. The resolve job downloads and
tests that same wheel artifact. These workflows do not publish packages.

Normal Hub installs now receive the same release on the tested Linux x86-64
CPython 3.13 platform, with `manylinux_2_35` system-library requirements. Other
platforms are not supported by this build. Start with a fresh environment when
switching distributions; their `rocksdb` module files overlap. Neither the
database directory name nor the database format changes.

## Scope

This validation targets Linux x86-64 on Python 3.13. Migration tests use small
synthetic legacy databases; they do not
measure mainnet-scale migration time or test power-loss recovery, and no real
wallet or mainnet database is opened. A production snapshot rehearsal is still
needed before deployment. The regtest suites also start with temporary data.
