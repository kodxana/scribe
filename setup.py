import os
from hub import __name__, __version__
from setuptools import setup, find_packages

BASE = os.path.dirname(__file__)
with open(os.path.join(BASE, 'README.md'), encoding='utf-8') as fh:
    long_description = fh.read()


setup(
    name=__name__,
    version=__version__,
    author="LBRY Inc.",
    maintainer="LBRY NG contributors",
    url="https://github.com/kodxana/lbry-hub-ng",
    description="Community-maintained LBRY Hub for blockchain indexing and wallet services",
    long_description=long_description,
    long_description_content_type="text/markdown",
    keywords="lbry protocol electrum spv",
    license='MIT',
    python_requires='>=3.7',
    packages=find_packages(exclude=('tests',)),
    zip_safe=False,
    entry_points={
        'console_scripts': [
            'scribe=hub.scribe.__main__:main',
            'herald=hub.herald.__main__:main',
            'scribe-elastic-sync=hub.elastic_sync.__main__:main',
        ],
    },
    install_requires=[
        'aiohttp==3.7.4',
        'certifi>=2021.10.08',
        'colorama==0.3.7',
        'cffi==1.13.2',
        'protobuf==3.20.3',
        'msgpack==0.6.1',
        'prometheus_client==0.7.1',
        'coincurve==15.0.0',
        'pbkdf2==1.3',
        'attrs==18.2.0',
        'elasticsearch==7.10.1',
        'hachoir==3.1.2',
        'filetype==1.0.9',
        'grpcio==1.38.0',
        'lbry-rocksdb-ng @ https://github.com/kodxana/lbry-rocksdb-ng/releases/download/v0.8.3/'
        'lbry_rocksdb_ng-0.8.3-cp39-cp39-manylinux_2_31_x86_64.whl'
        '#sha256=c0313ce0c346b441f4e58705adab16cf27ec189e0d05897adbcb97ca6273e7a2 ; '
        'sys_platform == "linux" and platform_machine == "x86_64" and '
        'python_version == "3.9" and implementation_name == "cpython"',
        'lbry-rocksdb==0.8.2 ; '
        'sys_platform != "linux" or platform_machine != "x86_64" or '
        'python_version != "3.9" or implementation_name != "cpython"',
        'ujson==5.4.0',
        'sha256==1.0'
    ],
    extras_require={
        'lint': ['pylint==2.10.0'],
        'test': ['coverage'],
    },
    classifiers=[
        'Framework :: AsyncIO',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Operating System :: OS Independent',
        'Topic :: Internet',
        'Topic :: Software Development :: Testing',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: System :: Distributed Computing',
        'Topic :: Utilities',
    ],
)
