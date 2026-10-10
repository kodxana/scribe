import asyncio
import logging
import time
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from hub.herald.session import SessionManager


class SessionManagerTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager = object.__new__(SessionManager)
        self.manager.env = SimpleNamespace(
            max_sessions=100, session_timeout=10, max_send=350000, drop_client=None
        )
        self.manager.db = SimpleNamespace(db_height=1)
        self.manager.logger = logging.getLogger('hub.herald.session')
        self.manager.servers = {}
        self.manager.sessions = {}
        self.manager.shutdown_event = asyncio.Event()
        self.manager.on_available_callback = Mock()
        self.manager._start_external_servers = AsyncMock()
        self.manager._close_servers = AsyncMock()
        self.manager.running = False
        self.mempool = SimpleNamespace(start=AsyncMock())
        self.listening = asyncio.Event()
        self.children = []
        self.serving = None

    async def asyncTearDown(self):
        # Also clean up tasks leaked by the old implementation in regression runs.
        tasks = [task for task in [self.serving, *self.children] if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def start_loops(self, failing=None, cleanup_gate=None):
        ready = [asyncio.Event(), asyncio.Event()]
        finished = [asyncio.Event(), asyncio.Event()]
        fail = asyncio.Event()

        async def worker(index):
            self.children.append(asyncio.current_task())
            ready[index].set()
            try:
                if index == failing:
                    await fail.wait()
                    raise RuntimeError('maintenance failed')
                await asyncio.Event().wait()
            finally:
                if index == 0 and cleanup_gate is not None:
                    await cleanup_gate.wait()
                await asyncio.sleep(0)
                finished[index].set()

        self.manager._clear_stale_sessions = lambda: worker(0)
        self.manager._manage_servers = lambda: worker(1)
        self.serving = asyncio.create_task(self.manager.serve(self.mempool, self.listening))
        return ready, finished, fail

    async def wait_for_loops(self, ready):
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in ready)), 1)

    async def test_cancellation_finishes_maintenance_before_closing_connections(self):
        ready, finished, _ = self.start_loops()
        await self.wait_for_loops(ready)
        self.assertTrue(self.listening.is_set())
        connection_closed = asyncio.Event()

        async def close_servers(kinds):
            self.assertTrue(all(event.is_set() for event in finished))

        async def close_session(force_after):
            self.manager._close_servers.assert_awaited_once()
            await asyncio.sleep(0)
            connection_closed.set()

        self.manager._close_servers.side_effect = close_servers
        self.manager.sessions[1] = SimpleNamespace(session_id=1, close=AsyncMock(side_effect=close_session))
        self.serving.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(self.serving, 1)
        self.assertTrue(connection_closed.is_set())
        self.assertFalse(self.manager.running)
        self.assertFalse(self.manager.shutdown_event.is_set())
        self.assertTrue(all(task.done() for task in self.children))

    async def check_background_failure(self, index):
        ready, finished, fail = self.start_loops(failing=index)
        await self.wait_for_loops(ready)
        with self.assertLogs(self.manager.logger, level='ERROR') as logs:
            fail.set()
            with self.assertRaisesRegex(RuntimeError, 'maintenance failed'):
                await asyncio.wait_for(self.serving, 1)
        self.assertIn('maintenance failed', '\n'.join(logs.output))
        self.assertTrue(all(event.is_set() for event in finished))
        self.assertTrue(self.manager.shutdown_event.is_set())
        self.assertFalse(self.manager.running)
        self.manager._close_servers.assert_awaited_once()

    async def test_cancellation_does_not_interrupt_slow_maintenance_cleanup(self):
        cleanup_gate = asyncio.Event()
        ready, finished, _ = self.start_loops(cleanup_gate=cleanup_gate)
        await self.wait_for_loops(ready)
        self.serving.cancel()
        try:
            # The fast worker finishes while the other is still releasing resources.
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(self.children[1]), 1)
        finally:
            cleanup_gate.set()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(self.serving, 1)
        self.assertTrue(all(event.is_set() for event in finished))

    async def test_stale_session_loop_failure_stops_server_loop(self):
        await self.check_background_failure(0)

    async def test_server_loop_failure_stops_stale_session_loop(self):
        await self.check_background_failure(1)

    async def test_failure_finishes_cleanup_before_requesting_service_shutdown(self):
        cleanup_started = asyncio.Event()
        allow_cleanup = asyncio.Event()

        async def wait_for_cleanup():
            cleanup_started.set()
            await allow_cleanup.wait()

        ready, finished, fail = self.start_loops(
            failing=1, cleanup_gate=SimpleNamespace(wait=wait_for_cleanup)
        )
        await self.wait_for_loops(ready)

        async def stop_service():
            await self.manager.shutdown_event.wait()
            self.serving.cancel()

        stopping = asyncio.create_task(stop_service())
        self.children.append(stopping)
        with self.assertLogs(self.manager.logger, level='ERROR'):
            fail.set()
            try:
                await asyncio.wait_for(cleanup_started.wait(), 1)
                self.assertFalse(self.manager.shutdown_event.is_set())
            finally:
                allow_cleanup.set()
            with self.assertRaisesRegex(RuntimeError, 'maintenance failed'):
                await asyncio.wait_for(self.serving, 1)
        await asyncio.wait_for(stopping, 1)
        self.assertTrue(all(event.is_set() for event in finished))
        self.assertFalse(self.manager.running)

    async def test_maintenance_loop_exit_requests_service_shutdown(self):
        ready, finished, _ = self.start_loops()
        # Replace one loop before serve() gets its first turn on the event loop.
        self.manager._clear_stale_sessions = AsyncMock()
        await asyncio.wait_for(self.serving, 1)
        self.assertTrue(self.manager.shutdown_event.is_set())
        self.assertTrue(ready[1].is_set())
        self.assertTrue(finished[1].is_set())
        self.assertFalse(self.manager.running)

    async def test_startup_failure_closes_partial_listener_and_connections(self):
        self.manager.servers['TCP'] = Mock(wait_closed=AsyncMock())
        session = SimpleNamespace(session_id=1, close=AsyncMock())
        self.manager.sessions[1] = session
        self.manager._start_external_servers.side_effect = RuntimeError('listen failed')
        with self.assertLogs(self.manager.logger, level='ERROR'):
            with self.assertRaisesRegex(RuntimeError, 'listen failed'):
                await self.manager.serve(self.mempool, self.listening)
        self.manager._close_servers.assert_awaited_once_with(['TCP'])
        session.close.assert_awaited_once_with(force_after=1)
        self.assertFalse(self.listening.is_set())
        self.assertFalse(self.manager.running)
        self.assertTrue(self.manager.shutdown_event.is_set())

    async def test_failed_connection_close_does_not_skip_other_connections(self):
        ready, _, _ = self.start_loops()
        await self.wait_for_loops(ready)
        closed = asyncio.Event()

        async def close_session(force_after):
            await asyncio.sleep(0)
            self.manager.sessions.pop(2)
            closed.set()

        self.manager.sessions = {
            1: SimpleNamespace(session_id=1, close=AsyncMock(side_effect=RuntimeError('close failed'))),
            2: SimpleNamespace(session_id=2, close=AsyncMock(side_effect=close_session))
        }
        with self.assertLogs(self.manager.logger, level='ERROR') as logs:
            self.serving.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(self.serving, 1)
        self.assertTrue(closed.is_set())
        self.assertIn('close failed', '\n'.join(logs.output))
        self.assertFalse(self.manager.running)

    async def test_listener_close_failure_still_closes_connections(self):
        ready, _, _ = self.start_loops()
        await self.wait_for_loops(ready)
        session = SimpleNamespace(session_id=1, close=AsyncMock())
        self.manager.sessions[1] = session
        self.manager._close_servers.side_effect = RuntimeError('listener close failed')
        self.serving.cancel()
        with self.assertRaisesRegex(RuntimeError, 'listener close failed'):
            await asyncio.wait_for(self.serving, 1)
        session.close.assert_awaited_once_with(force_after=1)
        self.assertFalse(self.manager.running)

    async def test_stale_connections_close_concurrently_and_report_failures(self):
        closed = asyncio.Event()
        first_started = asyncio.Event()
        second_started = asyncio.Event()

        async def fail_close(force_after):
            first_started.set()
            await second_started.wait()
            raise RuntimeError('stale close failed')

        async def finish_close(force_after):
            second_started.set()
            await first_started.wait()
            closed.set()

        stale = time.perf_counter() - 100
        sessions = [
            SimpleNamespace(session_id=1, last_recv=stale, close=AsyncMock(side_effect=fail_close)),
            SimpleNamespace(session_id=2, last_recv=stale, close=AsyncMock(side_effect=finish_close)),
            SimpleNamespace(session_id=3, last_recv=time.perf_counter(), close=AsyncMock())
        ]
        self.manager.sessions = {session.session_id: session for session in sessions}
        self.manager._group_map = Mock(return_value={})
        sleeps = 0

        async def one_iteration(delay):
            nonlocal sleeps
            sleeps += 1
            if sleeps > 1:
                raise asyncio.CancelledError()

        with patch('hub.herald.session.sleep', one_iteration):
            with self.assertLogs(self.manager.logger, level='ERROR') as logs:
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(self.manager._clear_stale_sessions(), 1)
        self.assertTrue(closed.is_set())
        self.assertIn('stale close failed', '\n'.join(logs.output))
        for session in sessions[:2]:
            session.close.assert_awaited_once_with(force_after=1)
        sessions[2].close.assert_not_awaited()

    async def test_cancelling_stale_cleanup_drains_connection_closes(self):
        started = asyncio.Event()
        finished = asyncio.Event()

        async def close_session(force_after):
            self.children.append(asyncio.current_task())
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await asyncio.sleep(0)
                finished.set()

        self.manager.sessions[1] = SimpleNamespace(
            session_id=1, last_recv=time.perf_counter() - 100,
            close=AsyncMock(side_effect=close_session)
        )
        with patch('hub.herald.session.sleep', AsyncMock()):
            self.serving = asyncio.create_task(self.manager._clear_stale_sessions())
            await asyncio.wait_for(started.wait(), 1)
            self.serving.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(self.serving, 1)
        self.assertTrue(finished.is_set())
        self.assertTrue(all(task.done() for task in self.children))

    async def open_real_connection(self):
        accepted = asyncio.Queue()
        server = await asyncio.start_server(
            lambda reader, writer: accepted.put_nowait((reader, writer)), '127.0.0.1', 0
        )
        client_reader, client_writer = await asyncio.open_connection(
            *server.sockets[0].getsockname()
        )
        server_reader, server_writer = await asyncio.wait_for(accepted.get(), 1)

        async def cleanup():
            client_writer.close()
            server_writer.close()
            await asyncio.gather(client_writer.wait_closed(), server_writer.wait_closed())
            server.close()
            await asyncio.wait_for(server.wait_closed(), 1)

        self.addAsyncCleanup(cleanup)
        self.manager.servers['TCP'] = server
        self.manager._close_servers = SessionManager._close_servers.__get__(self.manager)
        return server, client_reader, client_writer, server_reader, server_writer

    async def test_pausing_listener_keeps_existing_connections_usable(self):
        _, _, client_writer, server_reader, _ = await self.open_real_connection()
        await asyncio.wait_for(self.manager._close_servers(['TCP']), 1)
        self.assertEqual(self.manager.servers, {})
        client_writer.write(b'still connected')
        await client_writer.drain()
        self.assertEqual(await asyncio.wait_for(server_reader.read(15), 1), b'still connected')

    async def test_shutdown_closes_sessions_before_waiting_for_listener(self):
        server, client_reader, _, _, server_writer = await self.open_real_connection()

        async def close_session(force_after):
            server_writer.close()
            await server_writer.wait_closed()
            self.manager.sessions.pop(1)

        self.manager.sessions[1] = SimpleNamespace(
            session_id=1, close=AsyncMock(side_effect=close_session)
        )
        ready, _, _ = self.start_loops()
        await self.wait_for_loops(ready)
        self.serving.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(self.serving, 1)
        await asyncio.wait_for(server.wait_closed(), 1)
        self.assertEqual(await asyncio.wait_for(client_reader.read(), 1), b'')
        self.assertEqual(self.manager.sessions, {})
