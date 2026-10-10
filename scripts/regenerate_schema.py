"""Regenerate protobuf modules from the checked-in wire schemas."""
import argparse
import importlib.metadata
import re
import tempfile
from pathlib import Path

from grpc_tools import protoc


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'hub'
SCHEMA = ROOT / PACKAGE / 'schema'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='fail if generated files differ')
    args = parser.parse_args()
    for package, expected in (('grpcio-tools', '1.84.0'), ('protobuf', '7.36.2')):
        if importlib.metadata.version(package) != expected:
            parser.error(f'install {SCHEMA / "requirements.txt"} before generating schemas')

    changed = []
    for version in ('v1', 'v2'):
        source = SCHEMA / 'proto' / version
        destination = SCHEMA / 'types' / version
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            inputs = sorted(path.name for path in source.glob('*.proto'))
            result = protoc.main(['protoc', f'-I{source}', f'--python_out={output}', *inputs])
            if result:
                raise SystemExit(result)
            if (source / 'hub.proto').exists():
                result = protoc.main(['protoc', f'-I{source}', f'--grpc_python_out={output}', 'hub.proto'])
                if result:
                    raise SystemExit(result)
            for generated in sorted(output.glob('*.py')):
                text = generated.read_text()
                text = re.sub(r'^import (\w+_pb2) as ', r'from . import \1 as ', text, flags=re.MULTILINE)
                text = text.replace(f"DESCRIPTOR, '{generated.stem}',",
                                    f"DESCRIPTOR, '{PACKAGE}.schema.types.{version}.{generated.stem}',")
                path = destination / generated.name
                if not path.exists() or path.read_text() != text:
                    changed.append(str(path.relative_to(ROOT)))
                    if not args.check:
                        path.write_text(text, newline='\n')
    if changed:
        print('\n'.join(changed))
        if args.check:
            raise SystemExit('generated protobuf modules are out of date')


if __name__ == '__main__':
    main()
