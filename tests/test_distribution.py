from importlib.metadata import PackageNotFoundError, metadata, requires, version

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
import pytest


def test_binding_requirement_uses_the_python313_release():
    bindings = [Requirement(value) for value in requires('hub') if 'rocksdb' in value]
    assert len(bindings) == 1
    binding = bindings[0]
    assert binding.name == 'lbry-rocksdb-ng'
    assert binding.url == (
        'https://github.com/kodxana/lbry-rocksdb-ng/releases/download/v0.8.3/'
        'lbry_rocksdb_ng-0.8.3-cp313-cp313-manylinux_2_35_x86_64.whl'
        '#sha256=9e905f44895e0815ef6e803da964ee648cfd970cc2621003a92bc822875e3e72'
    )
    supported = SpecifierSet(metadata('hub')['Requires-Python'])
    assert '3.13' in supported
    assert '3.12' not in supported
    assert '3.14' not in supported


def test_only_maintained_binding_is_installed():
    assert version('lbry-rocksdb-ng') == '0.8.3'
    with pytest.raises(PackageNotFoundError):
        version('lbry-rocksdb')
