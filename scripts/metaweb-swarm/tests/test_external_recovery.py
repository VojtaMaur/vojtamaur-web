"""Cancellation/concurrent-state recovery uses a mock deposit, never Docker/API."""
import asyncio
import threading
import unittest
from unittest.mock import patch

from metaweb_swarm.engine import decide
from tests import test_execution_modes as execution_fixture


class ExternalRecoveryTests(unittest.IsolatedAsyncioTestCase):
    # Reuse only setup helpers, not the parent's entire test suite.
    setUp = execution_fixture.ExecutionModesTests.setUp
    tearDown = execution_fixture.ExecutionModesTests.tearDown
    open_run = execution_fixture.ExecutionModesTests.open_run
    candidate = execution_fixture.ExecutionModesTests.candidate
    prepare_tested_candidate = execution_fixture.ExecutionModesTests.prepare_tested_candidate

    def blocked_connector(self, fail=False):
        started, release = threading.Event(), threading.Event()

        def deposit(resource, file, name, expected, forbidden, timeout):
            started.set()
            if not release.wait(timeout=3):
                raise TimeoutError("Test fixture was not released")
            if fail:
                raise ValueError("Synthetic verification failure")
            return {"location": "fixture://reviewed-deposit", **expected, "host_verified": True,
                    "verification": "Mocked byte read-back; not a real deposit"}

        return deposit, started, release

    async def test_cancelled_success_persists_receipt_and_marks_approval_executed(self):
        idea, _ = await self.prepare_tested_candidate()
        self.engine.state["config"]["approval_required"] = True
        pending = await self.api.deposit_file(idea["id"], "public-deposit", "artifacts/recovery.txt")
        decide(self.engine.store, self.engine.state, pending["approval_id"], "approve", "Approve exact synthetic fixture")
        deposit, started, release = self.blocked_connector()
        with patch("metaweb_swarm.engine.execute_deposit", side_effect=deposit):
            task = asyncio.create_task(self.api.deposit_file(idea["id"], "public-deposit", "artifacts/recovery.txt"))
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 1))
                task.cancel()
                await asyncio.sleep(0)
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            finally:
                release.set()
                if not task.done():
                    await asyncio.gather(task, return_exceptions=True)
        restored = self.engine.store.load()
        self.assertEqual(restored["external_actions"][0]["status"], "VERIFIED")
        self.assertTrue(restored["approvals"][0]["executed"])
        self.assertEqual(restored["ideas"][0]["status"], "COMPLETED")
        self.assertTrue(restored["ideas"][0]["completion_receipts"])

    async def test_cancelled_failed_worker_persists_unknown_and_never_retries(self):
        idea, _ = await self.prepare_tested_candidate()
        deposit, started, release = self.blocked_connector(fail=True)
        with patch("metaweb_swarm.engine.execute_deposit", side_effect=deposit) as connector:
            task = asyncio.create_task(self.api.deposit_file(idea["id"], "public-deposit", "artifacts/recovery.txt"))
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 1))
                task.cancel()
                await asyncio.sleep(0)
                release.set()
                try:
                    await task
                except (asyncio.CancelledError, ValueError):
                    pass
            finally:
                release.set()
                if not task.done():
                    await asyncio.gather(task, return_exceptions=True)
            restored = self.engine.store.load()
            self.assertEqual(restored["external_actions"][0]["status"], "UNKNOWN")
            self.assertFalse(restored["ideas"][0].get("completion_receipts"))
            retry = await self.api.deposit_file(idea["id"], "public-deposit", "artifacts/recovery.txt")
            self.assertEqual(retry["reason"], "UNCERTAIN_PREVIOUS_ACTION_REQUIRES_RECONCILIATION")
            self.assertEqual(connector.call_count, 1)

    async def test_inflight_candidate_revision_keeps_current_aggregate_completion(self):
        idea, _ = await self.prepare_tested_candidate()
        deposit, started, release = self.blocked_connector()
        with patch("metaweb_swarm.engine.execute_deposit", side_effect=deposit):
            task = asyncio.create_task(self.api.deposit_file(idea["id"], "public-deposit", "artifacts/recovery.txt"))
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 1))
                newer = self.candidate(id=idea["id"], summary="Additional reviewed reconstruction guidance")
                self.assertIsNot(newer, idea)
                release.set()
                result = await task
            finally:
                release.set()
                if not task.done():
                    await asyncio.gather(task, return_exceptions=True)
        restored = self.engine.store.load()
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(restored["ideas"][0]["status"], "COMPLETED")
        self.assertTrue(restored["ideas"][0]["completion_receipts"])
        self.assertEqual(len(restored["ideas"][0]["submissions"]), 2)
