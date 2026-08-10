from __future__ import annotations

import unittest

from cli import worker_status


class ParseWorkerHostnameTests(unittest.TestCase):
    def test_parses_full_sslip_hostname(self) -> None:
        ref = worker_status.parse_worker_hostname("akamai-003-relay-1.96-126-106-95.sslip.io")
        self.assertIsNotNone(ref)
        assert ref is not None
        self.assertEqual(ref.provider, "akamai")
        self.assertEqual(ref.host, "003")
        self.assertEqual(ref.service, "relay")
        self.assertEqual(ref.index, 1)
        self.assertEqual(ref.container_name, "xaisen-akamai-003-relay-1")

    def test_parses_multi_word_service(self) -> None:
        ref = worker_status.parse_worker_hostname("akamai-001-validator-daemon-1.1-2-3-4.sslip.io")
        self.assertIsNotNone(ref)
        assert ref is not None
        self.assertEqual(ref.service, "validator-daemon")

    def test_rejects_unparseable_hostname(self) -> None:
        self.assertIsNone(worker_status.parse_worker_hostname("not-a-worker"))

    def test_parses_path_based_public_identifier(self) -> None:
        ref = worker_status.parse_worker_hostname("45-79-134-247.sslip.io/akamai-004/relay-1")
        self.assertIsNotNone(ref)
        assert ref is not None
        self.assertEqual(ref.provider, "akamai")
        self.assertEqual(ref.host, "004")
        self.assertEqual(ref.service, "relay")
        self.assertEqual(ref.index, 1)
        self.assertEqual(ref.container_name, "xaisen-akamai-004-relay-1")

    def test_parses_path_based_identifier_without_leading_ip_segment(self) -> None:
        ref = worker_status.parse_worker_hostname("akamai-004/relay-1")
        self.assertIsNotNone(ref)
        assert ref is not None
        self.assertEqual(ref.worker_key, "akamai-004-relay-1")

    def test_parses_path_based_identifier_with_scheme_and_multi_word_service(self) -> None:
        ref = worker_status.parse_worker_hostname("https://45-79-134-247.sslip.io/akamai-004/cp-daemon-1")
        self.assertIsNotNone(ref)
        assert ref is not None
        self.assertEqual(ref.service, "cp-daemon")
        self.assertEqual(ref.index, 1)

    def test_rejects_path_based_identifier_with_unknown_service(self) -> None:
        self.assertIsNone(worker_status.parse_worker_hostname("akamai-004/not-a-service-1"))


if __name__ == "__main__":
    unittest.main()
