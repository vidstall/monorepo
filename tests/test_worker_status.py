from __future__ import annotations

import unittest

from cli import worker_status


class ParseWorkerHostnameTests(unittest.TestCase):
    def test_parses_full_sslip_hostname(self) -> None:
        ref = worker_status.parse_worker_hostname("akamai-003-signaling-1.96-126-106-95.sslip.io")
        self.assertIsNotNone(ref)
        assert ref is not None
        self.assertEqual(ref.provider, "akamai")
        self.assertEqual(ref.host, "003")
        self.assertEqual(ref.service, "signaling")
        self.assertEqual(ref.index, 1)
        self.assertEqual(ref.container_name, "xaisen-akamai-003-signaling-1")

    def test_parses_multi_word_service(self) -> None:
        ref = worker_status.parse_worker_hostname("akamai-001-validator-daemon-1.1-2-3-4.sslip.io")
        self.assertIsNotNone(ref)
        assert ref is not None
        self.assertEqual(ref.service, "validator-daemon")

    def test_rejects_unparseable_hostname(self) -> None:
        self.assertIsNone(worker_status.parse_worker_hostname("not-a-worker"))


if __name__ == "__main__":
    unittest.main()
