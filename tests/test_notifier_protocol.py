import asyncio
import struct
import unittest
from collections import deque
from unittest.mock import Mock

from hub.elastic_sync.service import ElasticSyncService
from hub.notifier_protocol import ElasticNotifierClientProtocol


class NotifierTests(unittest.TestCase):
    def make_client(self):
        return ElasticNotifierClientProtocol(
            asyncio.Queue(), deque([(('localhost', 9200), ('localhost', 19081))])
        )

    def test_new_listener_receives_latest_indexed_tip(self):
        service = object.__new__(ElasticSyncService)
        service._listeners = []
        service._last_wrote_height = 217
        block_hash = bytes(range(32))
        service._last_wrote_block_hash = (b'x' * 32).hex()
        protocol = service.make_es_notifier()
        # The index can advance between accepting the socket and connection_made.
        service._last_wrote_height = 218
        service._last_wrote_block_hash = block_hash[::-1].hex()
        transport = Mock()
        protocol.connection_made(transport)
        transport.write.assert_called_once_with(struct.pack('>Q32s', 218, block_hash))
        self.assertEqual(service._listeners, [protocol])
        protocol.connection_lost(None)
        self.assertEqual(service._listeners, [])

    def test_listener_before_first_index_update_gets_no_invented_tip(self):
        service = object.__new__(ElasticSyncService)
        service._listeners = []
        service._last_wrote_height = 0
        service._last_wrote_block_hash = None
        protocol = service.make_es_notifier()
        transport = Mock()
        protocol.connection_made(transport)
        transport.write.assert_not_called()

    def test_notifications_survive_split_and_coalesced_tcp_reads(self):
        updates = [(218, b'a' * 32), (219, b'b' * 32)]
        wire = b''.join(struct.pack('>Q32s', *update) for update in updates)
        for split in range(1, len(wire) + 1):
            with self.subTest(split=split):
                client = self.make_client()
                client.data_received(wire[:split])
                client.data_received(wire[split:])
                self.assertEqual([client.notifications.get_nowait() for _ in updates], updates)
                self.assertTrue(client.notifications.empty())

    def test_reconnect_discards_partial_frame_from_previous_connection(self):
        client = self.make_client()
        client.connection_made(Mock())
        client.data_received(struct.pack('>Q32s', 218, b'a' * 32)[:17])
        client.connection_lost(None)
        client.connection_made(Mock())
        client.data_received(struct.pack('>Q32s', 219, b'b' * 32))
        self.assertEqual(client.notifications.get_nowait(), (219, b'b' * 32))
        self.assertTrue(client.notifications.empty())
