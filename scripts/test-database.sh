#!/bin/sh
set -eu

python -VV
python -m pip check
python -m pip freeze --all > /results/packages.txt
cp /wheels/*.whl /results/
if [ -f /opt/binding-sha256.txt ]; then
    cp /opt/binding-sha256.txt /results/
fi
python -c 'import hub, rocksdb; print("Testing installed packages:", hub.__file__, rocksdb.__file__)'
python -m pytest -v --junitxml=/results/tests.xml tests/test_revertable.py
