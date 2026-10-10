from importlib.metadata import PackageNotFoundError, requires, version

from packaging.markers import default_environment
from packaging.requirements import Requirement
import pytest


@pytest.mark.parametrize('system,machine,python,implementation,expected', [
    ('linux', 'x86_64', '3.9', 'cpython', 'lbry-rocksdb-ng'),
    ('linux', 'aarch64', '3.9', 'cpython', 'lbry-rocksdb'),
    ('linux', 'x86_64', '3.8', 'cpython', 'lbry-rocksdb'),
    ('linux', 'x86_64', '3.13', 'cpython', 'lbry-rocksdb'),
    ('linux', 'x86_64', '3.9', 'pypy', 'lbry-rocksdb'),
    ('darwin', 'x86_64', '3.9', 'cpython', 'lbry-rocksdb'),
    ('win32', 'AMD64', '3.9', 'cpython', 'lbry-rocksdb'),
])
def test_binding_requirement_selects_one_distribution(system, machine, python, implementation, expected):
    environment = default_environment()
    environment.update(sys_platform=system, platform_machine=machine,
                       python_version=python, implementation_name=implementation)
    bindings = [Requirement(value) for value in requires('hub') if 'rocksdb' in value]
    selected = [item for item in bindings if item.marker.evaluate(environment)]
    assert [item.name for item in selected] == [expected]
    if expected == 'lbry-rocksdb-ng':
        assert selected[0].url.startswith(
            'https://github.com/kodxana/lbry-rocksdb/releases/download/v0.8.3/'
            'lbry_rocksdb_ng-0.8.3-cp39-cp39-manylinux_2_31_x86_64.whl#sha256='
        )
        assert len(selected[0].url.split('#sha256=')[1]) == 64
    else:
        assert str(selected[0].specifier) == '==0.8.2'


def test_only_maintained_binding_is_installed():
    assert version('lbry-rocksdb-ng') == '0.8.3'
    with pytest.raises(PackageNotFoundError):
        version('lbry-rocksdb')
