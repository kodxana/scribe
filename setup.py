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
    python_requires='>=3.13,<3.14',
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
        'aiohttp==3.14.4',
        'asn1crypto==1.5.1',
        'certifi==2026.7.22',
        'colorama==0.4.6',
        'cffi==2.1.1',
        'protobuf==7.36.2',
        'msgpack==1.2.3',
        'prometheus_client==0.26.0',
        'coincurve==21.0.0',
        'pbkdf2==1.3',
        'attrs==26.1.0',
        'elasticsearch==7.17.13',
        'hachoir==3.4.0',
        'filetype==1.2.0',
        'grpcio==1.84.0',
        'lbry-rocksdb-ng @ https://github.com/kodxana/lbry-rocksdb-ng/releases/download/v0.8.3/'
        'lbry_rocksdb_ng-0.8.3-cp313-cp313-manylinux_2_35_x86_64.whl'
        '#sha256=9e905f44895e0815ef6e803da964ee648cfd970cc2621003a92bc822875e3e72',
        'ujson==6.0.0',
        'sha256==1.0'
    ],
    extras_require={
        'lint': ['pylint==4.1.2'],
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
