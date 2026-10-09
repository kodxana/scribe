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

Results go to `ci-results/published/`: the Hub wheel, test log, JUnit report,
and installed package versions. Set `TEST_OUTPUT_DIR` to change the destination.

## Resolve and reorg tests

Use the matching SDK checkout, including the shared protobuf 3.20.3 requirement:

```sh
git clone https://github.com/kodxana/lbry-sdk.git .ci/sdk
git -C .ci/sdk checkout 500abb1d0894ec17081f8111f30e125d7c4f2c4e
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
[`kodxana/lbry-rocksdb` at `c4c9e7dc45f32ad99cfff934798b51624f41ed69`](https://github.com/kodxana/lbry-rocksdb/commit/c4c9e7dc45f32ad99cfff934798b51624f41ed69).
That checkout builds its pinned native libraries and passes its binding suite
before the wheel reaches the Hub database job. The resolve job downloads and
tests that same wheel artifact. These workflows do not publish packages.

## Scope

This validates Linux x86-64 on Python 3.9. It does not establish Python 3.13
support or validate migrating an existing mainnet database from the old fork's
schema to upstream's version 12. The regtest suites start with temporary
databases; deployment and existing-data migration need separate validation.
