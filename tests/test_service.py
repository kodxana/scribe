import asyncio
import gc
import logging
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch
from collections import deque
from elasticsearch import ConnectionError as ElasticConnectionError

from hub.elastic_sync.service import ElasticSyncService
from hub.service import BlockchainService
from hub.common import RPCError
from hub.herald.search import SearchIndex
from hub.herald.session import LBRYElectrumX


class ServiceShutdownTests(IsolatedAsyncioTestCase):
    def make_service(self, service_class=BlockchainService):
        service = object.__new__(service_class)
        service.lock = asyncio.Lock()
        service.cancellable_tasks = []
        service.log = logging.getLogger('hub.tests.shutdown')
        service.shutdown_event = asyncio.Event()
        service.db = Mock()
        service._executor = Mock()
        service._stopping = False
        if service_class is ElasticSyncService:
            service.index = 'temporary-claims'
            service.sync_client = Mock()
            service.sync_client.close = AsyncMock()
            service.sync_client.indices.delete = AsyncMock()
        return service

    async def start_worker(self, service, cleanup):
        async def worker(started):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                await cleanup()

        await service.start_cancellable(worker)
        return service.cancellable_tasks[-1]

    async def test_stop_waits_for_cleanup_before_closing_database(self):
        service = self.make_service()
        executor = service._executor
        cleaned_up = asyncio.Event()

        async def cleanup():
            # Shutdown must release the lock before waiting for task cleanup.
            async with service.lock:
                await asyncio.sleep(0)
                service.db.close.assert_not_called()
                executor.shutdown.assert_not_called()
                cleaned_up.set()

        task = await self.start_worker(service, cleanup)
        try:
            await asyncio.wait_for(service.stop(), 1)
            self.assertTrue(cleaned_up.is_set())
            self.assertTrue(task.cancelled())
            self.assertEqual(service.cancellable_tasks, [])
            service.db.close.assert_called_once_with()
            executor.shutdown.assert_called_once_with(wait=True)
        finally:
            await asyncio.gather(task, return_exceptions=True)

    async def test_stop_reports_failed_tasks_and_finishes_cleanup(self):
        service = self.make_service()
        loop = asyncio.get_running_loop()
        unhandled = []
        old_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _, context: unhandled.append(context))
        self.addCleanup(loop.set_exception_handler, old_handler)

        async def fail(started):
            started.set()
            raise RuntimeError('reader failed')

        await service.start_cancellable(fail)
        with self.assertLogs(service.log, level='ERROR') as logs:
            await service.stop()
        gc.collect()
        self.assertEqual(unhandled, [])
        self.assertIn('reader failed', '\n'.join(logs.output))
        service.db.close.assert_called_once_with()
        self.assertTrue(service.shutdown_event.is_set())

    async def test_index_deletion_waits_for_reader_cleanup(self):
        service = self.make_service(ElasticSyncService)
        client = service.sync_client
        cleaned_up = asyncio.Event()

        async def cleanup():
            await asyncio.sleep(0)
            client.indices.delete.assert_not_awaited()
            client.close.assert_not_awaited()
            cleaned_up.set()

        async def delete(*args, **kwargs):
            self.assertTrue(cleaned_up.is_set())
            client.close.assert_not_awaited()

        client.indices.delete.side_effect = delete
        task = await self.start_worker(service, cleanup)
        try:
            await asyncio.wait_for(service.stop_index(delete=True), 1)
            self.assertTrue(task.cancelled())
            client.indices.delete.assert_awaited_once_with('temporary-claims', ignore_unavailable=True)
            client.close.assert_awaited_once_with()
            self.assertIsNone(service.sync_client)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_normal_stop_preserves_index(self):
        service = self.make_service(ElasticSyncService)
        client = service.sync_client
        cleanup = AsyncMock()
        task = await self.start_worker(service, cleanup)
        try:
            with patch.object(service.log, 'error') as report_error:
                await service.stop()
            report_error.assert_not_called()
            self.assertTrue(task.cancelled())
            cleanup.assert_awaited_once_with()
            client.indices.delete.assert_not_awaited()
            client.close.assert_awaited_once_with()
            service.db.close.assert_called_once_with()
        finally:
            await asyncio.gather(task, return_exceptions=True)

    async def test_failed_index_deletion_still_closes_client(self):
        service = self.make_service(ElasticSyncService)
        client = service.sync_client
        client.indices.delete.side_effect = RuntimeError('delete failed')
        with self.assertRaisesRegex(RuntimeError, 'delete failed'):
            await service.stop_index(delete=True)
        client.close.assert_awaited_once_with()
        self.assertIsNone(service.sync_client)

    async def test_stop_index_can_be_repeated(self):
        service = self.make_service(ElasticSyncService)
        client = service.sync_client
        await service.stop_index(delete=True)
        await service.stop_index(delete=True)
        client.indices.delete.assert_awaited_once()
        client.close.assert_awaited_once()


class SearchAvailabilityTests(IsolatedAsyncioTestCase):
    async def test_search_during_disconnect_returns_retryable_rpc_error(self):
        session = object.__new__(LBRYElectrumX)
        session.session_manager = Mock()
        session.session_manager.search_index = SearchIndex(Mock(), 'temporary-')
        with self.assertRaises(RPCError) as error:
            await session.claimtrie_search(order_by=['height'])
        self.assertEqual(error.exception.code, -32001)
        self.assertEqual(error.exception.message, 'claim search is temporarily unavailable')

    async def test_failed_search_connection_returns_retryable_rpc_error(self):
        session = object.__new__(LBRYElectrumX)
        session.session_manager = Mock()
        session.session_manager.search_index.cached_search = AsyncMock(
            side_effect=ElasticConnectionError('N/A', 'connection closed', None)
        )
        with self.assertRaises(RPCError) as error:
            await session.claimtrie_search(order_by=['height'])
        self.assertEqual(error.exception.code, -32001)

    async def test_search_becomes_ready_after_index_setup_and_clears_on_stop(self):
        index = SearchIndex(Mock(), 'temporary-', elastic_services=deque([
            (('localhost', 9200), ('localhost', 19081))
        ]))
        sync_client, search_client = Mock(), Mock()
        sync_client.cluster.health = AsyncMock()
        sync_client.indices.create = AsyncMock(return_value={'acknowledged': True})
        configuring = asyncio.Event()
        allow_setup = asyncio.Event()

        async def configure(*args, **kwargs):
            configuring.set()
            await allow_setup.wait()

        sync_client.indices.put_template = AsyncMock(side_effect=configure)
        sync_client.close = AsyncMock()
        search_client.close = AsyncMock()
        with patch('hub.herald.search.AsyncElasticsearch', side_effect=[sync_client, search_client]):
            starting = asyncio.create_task(index.start())
            try:
                await asyncio.wait_for(configuring.wait(), 1)
                self.assertFalse(index.ready.is_set())
                with self.assertRaises(ElasticConnectionError):
                    await index.cached_search({})
            finally:
                allow_setup.set()
                await asyncio.wait_for(starting, 1)
        self.assertTrue(index.ready.is_set())
        await index.stop()
        self.assertFalse(index.ready.is_set())
        sync_client.close.assert_awaited_once()
        search_client.close.assert_awaited_once()
