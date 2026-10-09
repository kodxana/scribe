# Database test baseline

This baseline covers the current `kodxana/scribe` fork on Linux x86-64 and Python
3.9. It retains the existing package name, runtime dependency requirements, and
Docker publishing workflow. The fork predates the upstream rename to `hub`;
bringing in upstream changes is a separate step.

## Run the tests

With Docker and a Linux daemon available:

```sh
sh scripts/test.sh
```

On Windows, run the command from WSL. The image pins Python 3.9.23 by digest and
pins the test environment in `docker/test-requirements.txt`. It builds and
installs a Scribe wheel, then runs outside the source directory as an
unprivileged user. `pip check` verifies the installed dependency metadata.

The test container has no network access, host mounts, or exposed ports. It is
limited to two CPUs and 4 GiB of memory, with a five-minute process timeout.
Dependency installation and compilation happen during the Docker build, which
does need network access. CI has a 45-minute job timeout.

Results go to `ci-results/published/`: the Scribe wheel, test log, JUnit report,
and installed package versions. Set `TEST_OUTPUT_DIR` to change the destination.
The runner returns a nonzero status on failure and removes its test container.

## Compare the maintained RocksDB binding

The default run installs `lbry-rocksdb==0.8.2` from PyPI. To test a locally built
Linux CPython 3.9 wheel instead, pass its path:

```sh
sh scripts/test.sh /path/to/lbry_rocksdb-0.8.2-cp39-cp39-linux_x86_64.whl
```

The runner installs that exact wheel without fetching replacement dependencies.
Results go to `ci-results/local-wheel/`, including the wheel's SHA-256. The
installed package list also records its direct file reference and hash.

CI runs both variants. Its maintained binding comes from
[`kodxana/lbry-rocksdb` at `c4c9e7dc45f32ad99cfff934798b51624f41ed69`](https://github.com/kodxana/lbry-rocksdb/commit/c4c9e7dc45f32ad99cfff934798b51624f41ed69).
That checkout builds its pinned native libraries and runs its own binding suite
before the resulting wheel is passed to the Scribe tests. This does not publish
a package or change Scribe's runtime dependency pin.

## What is covered

`tests/test_revertable.py` exercises the real `PrefixDB` database interface:

- Operation-stack integrity and cancellation of opposing changes.
- Block commits and rollback through several heights.
- Prefix iteration, range boundaries, and reverse iteration.
- Reopening a database between commits and rollbacks, including persisted undo
  records and changes across multiple column families.
- A secondary reader catching up after a primary commit and rollback.

These six tests run against each binding. They do not establish full server or
Python 3.13 compatibility. The two binding versions use the same Python 3.9 test
environment so that a dependency upgrade cannot hide a difference between them.

`tests/test_resolve_command.py` is an SDK integration suite. It uses
`lbry.testcase.CommandTestCase`, whose current Hub orchestrator imports the newer
`hub` package rather than this fork's `scribe` package. Running that suite against
this fork requires reconciling the fork and its SDK harness first. It is
not collected by this database-only CI job; it has not been removed or marked
as passing. No mainnet node or existing user database is used by the baseline.
