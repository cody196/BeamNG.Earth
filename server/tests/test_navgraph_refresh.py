"""Autodrive can refresh an incomplete road graph while the player is stationary."""
import sys
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import navgraph


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.tracker = navgraph.Tracker()
        self.tracker.aid, self.tracker.centre = 2, (100, 200)
        self.tracker.pool = Mock()
        self.loop, self.conn = Mock(), Mock()
        self.future = Future()
        self.loop.run_in_executor.return_value = self.future

    def pose(self):
        self.tracker.on_pose(self.conn, 2, 100, 200, self.loop, Mock())

    def test_stationary_refresh_builds_and_publishes_once(self):
        self.pose()
        self.loop.run_in_executor.assert_not_called()
        self.assertTrue(self.tracker.request_refresh())
        self.pose()
        self.loop.run_in_executor.assert_called_once()
        self.future.set_result(('/temp/fresh.json', 10, 9))
        self.assertEqual(self.conn.send.call_args.args[0]['path'], '/temp/fresh.json')
        self.pose()
        self.loop.run_in_executor.assert_called_once()

    def test_request_during_build_is_not_lost_or_run_concurrently(self):
        self.tracker.centre = None
        self.pose()
        self.assertTrue(self.tracker.building)
        self.tracker.request_refresh()
        self.pose()
        self.loop.run_in_executor.assert_called_once()
        self.future.set_result(('/temp/old.json', 10, 9))
        self.loop.run_in_executor.return_value = Future()
        self.pose()
        self.assertEqual(self.loop.run_in_executor.call_count, 2)
        self.assertFalse(self.tracker.refresh_pending)

    def test_repeated_toggles_are_rate_limited(self):
        with patch('time.monotonic', side_effect=[100, 101, 119.9, 120]):
            self.assertTrue(self.tracker.request_refresh())
            self.assertFalse(self.tracker.request_refresh())
            self.assertFalse(self.tracker.request_refresh())
            self.assertTrue(self.tracker.request_refresh())

    def test_failed_build_can_be_requested_again(self):
        with patch('time.monotonic', side_effect=[100, 121]):
            self.tracker.request_refresh()
            self.pose()
            self.future.set_exception(ValueError('road data unavailable'))
            self.assertFalse(self.tracker.building)
            self.assertTrue(self.tracker.request_refresh())
            self.loop.run_in_executor.return_value = Future()
            self.pose()
            self.assertEqual(self.loop.run_in_executor.call_count, 2)

    def test_protocol_message_reaches_tracker(self):
        import earthd
        conn = earthd.Connection.__new__(earthd.Connection)
        conn.nav, conn.focus = self.tracker, (100, 200)
        conn.dispatch({'type': 'navgraph_refresh'})
        self.assertTrue(self.tracker.refresh_pending)


if __name__ == '__main__':
    unittest.main()
