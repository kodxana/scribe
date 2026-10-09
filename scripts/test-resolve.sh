#!/bin/sh
set -eu

python -VV
python -m pip check
python -m pip freeze --all > /results/packages.txt
cp /wheels/*.whl /results/
if [ -f /opt/binding-sha256.txt ]; then
    cp /opt/binding-sha256.txt /results/
fi
python -c 'import hub, lbry, rocksdb; print("Testing installed Hub:", hub.__file__); print("SDK:", lbry.__file__); print("RocksDB:", rocksdb.__file__)'
status=0
python -m coverage run --data-file=/tmp/.coverage --source=hub \
    -m unittest -v tests.test_resolve_command || status=$?
python -m coverage xml --data-file=/tmp/.coverage -o /results/coverage.xml
exit "$status"
