import unittest
from app.resilience.deduplicator import AlertDeduplicator


class TestAlertDeduplicator(unittest.TestCase):
    def setUp(self):
        self.deduplicator = AlertDeduplicator(window_seconds=60)

    def test_fingerprint_deterministic(self):
        alert_a = {
            "service": "checkout-svc",
            "alert_name": "High5xxRate",
            "severity": "CRITICAL",
            "entity": "checkout-pod-1"
        }
        alert_b = {
            "entity": "checkout-pod-1",
            "severity": "CRITICAL",
            "alert_name": "High5xxRate",
            "service": "checkout-svc"
        }
        fp_a = self.deduplicator.compute_fingerprint(alert_a)
        fp_b = self.deduplicator.compute_fingerprint(alert_b)
        self.assertEqual(fp_a, fp_b)
        self.assertEqual(len(fp_a), 64)  # Valid SHA-256 hex string

    def test_fingerprint_distinct_for_different_services(self):
        alert_a = {"service": "checkout-svc", "alert_name": "High5xxRate", "severity": "CRITICAL"}
        alert_b = {"service": "payment-svc", "alert_name": "High5xxRate", "severity": "CRITICAL"}
        self.assertNotEqual(
            self.deduplicator.compute_fingerprint(alert_a),
            self.deduplicator.compute_fingerprint(alert_b)
        )

    def test_fingerprint_distinct_for_different_severities(self):
        alert_a = {"service": "order-svc", "alert_name": "HighLatency", "severity": "WARNING"}
        alert_b = {"service": "order-svc", "alert_name": "HighLatency", "severity": "CRITICAL"}
        self.assertNotEqual(
            self.deduplicator.compute_fingerprint(alert_a),
            self.deduplicator.compute_fingerprint(alert_b)
        )


if __name__ == "__main__":
    unittest.main()
