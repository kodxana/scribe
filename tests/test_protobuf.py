import importlib
import json
import unittest
from pathlib import Path

from google.protobuf.descriptor_pb2 import FileDescriptorProto, FileDescriptorSet


PACKAGE = 'hub'
FIXTURES = Path(__file__).resolve().parent / 'fixtures'


def normalize_descriptor(file):
    # Older protoc omitted proto2 and inferred JSON names. Preserve explicit
    # non-default names so changes to the JSON API still fail this comparison.
    if file.syntax == 'proto2':
        file.ClearField('syntax')

    def normalize_message(message):
        for field in message.field:
            first, *words = field.name.split('_')
            default_name = first + ''.join(word[:1].upper() + word[1:] for word in words)
            if field.json_name == default_name:
                field.ClearField('json_name')
        for nested in message.nested_type:
            normalize_message(nested)

    for message in file.message_type:
        normalize_message(message)
    for service in file.service:
        for method in service.method:
            if not method.options.ListFields():
                method.ClearField('options')
    return file


class ProtobufCompatibilityTests(unittest.TestCase):
    def test_descriptors_preserve_deployed_schema(self):
        for version in ('v1', 'v2'):
            previous = FileDescriptorSet.FromString((FIXTURES / f'protobuf-{version}.pb').read_bytes())
            for old in previous.file:
                with self.subTest(version=version, schema=old.name):
                    module_name = old.name.replace('.proto', '_pb2')
                    module = importlib.import_module(f'{PACKAGE}.schema.types.{version}.{module_name}')
                    current = FileDescriptorProto()
                    module.DESCRIPTOR.CopyToProto(current)
                    self.assertEqual(normalize_descriptor(current), normalize_descriptor(old))

    def test_legacy_wire_roundtrip_and_unknown_fields(self):
        for vector in json.loads((FIXTURES / 'protobuf-wire.json').read_text()):
            with self.subTest(version=vector['version'], message=vector['message'], variant=vector['variant']):
                module = importlib.import_module(f"{PACKAGE}.schema.types.{vector['version']}.{vector['module']}")
                message_type = getattr(module, vector['message'])
                wire = bytes.fromhex(vector['wire'])
                # An unknown varint field must survive decoding and encoding,
                # allowing older clients to relay messages from newer peers.
                for data in (wire, wire + b'\xf8\x07\x7b'):
                    message = message_type.FromString(data)
                    self.assertTrue(message.IsInitialized())
                    self.assertEqual(message.SerializeToString(), data)
