import asyncio
import json

from lbry.testcase import IntegrationTestCase


class SessionLifecycleTests(IntegrationTestCase):
    async def test_stop_disconnects_clients_and_finishes_maintenance(self):
        node = self.conductor.spv_node
        manager = node.server.session_manager
        reader, writer = await asyncio.open_connection(node.hostname, node.port)
        self.addCleanup(writer.wait_closed)
        self.addCleanup(writer.close)
        writer.write(b'{"jsonrpc":"2.0","id":1,"method":"server.banner","params":[]}\n')
        await writer.drain()
        response = json.loads(await asyncio.wait_for(reader.readline(), 5))
        self.assertEqual(response['id'], 1)
        self.assertIn('result', response)

        workers = [task for task in asyncio.all_tasks() if task.get_coro().__qualname__ in (
            'SessionManager._clear_stale_sessions', 'SessionManager._manage_servers'
        )]
        self.assertEqual(len(workers), 2)
        await self.conductor.stop_spv()

        self.assertEqual(await asyncio.wait_for(reader.read(), 5), b'')
        self.assertTrue(all(task.done() for task in workers))
        self.assertEqual(manager.servers, {})
        self.assertEqual(manager.sessions, {})
        self.assertFalse(manager.running)
