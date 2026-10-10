import asyncio
import json
import unittest

from hub.common import RPCError
from hub.herald.common import Batch, Notification, Request
from hub.herald.jsonrpc import JSONRPCConnection, JSONRPCv2


class JSONRPCResultTests(unittest.IsolatedAsyncioTestCase):
    async def test_response_completes_request(self):
        connection = JSONRPCConnection(JSONRPCv2)
        message, event = connection.send_request(Request('server.version', []))
        request_id = json.loads(message)['id']
        waiter = asyncio.create_task(event.wait())
        self.assertFalse(event.is_set())
        connection.receive_message(JSONRPCv2.response_message(['hub', '1.4'], request_id))
        await asyncio.wait_for(waiter, 1)
        self.assertEqual(event.result, ['hub', '1.4'])
        self.assertEqual(connection.pending_requests(), [])

    async def test_batch_results_keep_request_order(self):
        connection = JSONRPCConnection(JSONRPCv2)
        message, event = connection.send_batch(Batch([
            Request('first', []), Notification('notification', []), Request('second', [])
        ]))
        ids = [item['id'] for item in json.loads(message) if 'id' in item]
        error = RPCError(-1, 'unavailable')
        connection.receive_message(JSONRPCv2.batch_message_from_parts([
            JSONRPCv2.response_message(error, ids[1]),
            JSONRPCv2.response_message('first result', ids[0]),
        ]))
        await asyncio.wait_for(event.wait(), 1)
        self.assertEqual(event.result[0], 'first result')
        self.assertIsInstance(event.result[1], RPCError)
        self.assertEqual(event.result[1].code, -1)
        self.assertEqual(connection.pending_requests(), [])

    async def test_disconnect_releases_pending_request(self):
        connection = JSONRPCConnection(JSONRPCv2)
        _, event = connection.send_request(Request('server.version', []))
        error = ConnectionError('disconnected')
        connection.raise_pending_requests(error)
        await asyncio.wait_for(event.wait(), 1)
        self.assertIs(event.result, error)
        self.assertEqual(connection.pending_requests(), [])
