import unittest
from app.resilience.idempotent_runner import IdempotentToolRunner


class TestIdempotentToolRunner(unittest.TestCase):
    def setUp(self):
        self.runner = IdempotentToolRunner()

    def test_idempotency_key_canonical_ordering(self):
        params_1 = {"namespace": "prod", "deployment": "auth-svc", "replicas": 5}
        params_2 = {"replicas": 5, "namespace": "prod", "deployment": "auth-svc"}
        
        key_1 = self.runner.generate_idempotency_key("scale_service_replicas", params_1, "INC-001")
        key_2 = self.runner.generate_idempotency_key("scale_service_replicas", params_2, "INC-001")
        self.assertEqual(key_1, key_2)

    def test_idempotency_key_differs_by_incident(self):
        params = {"namespace": "prod", "deployment": "auth-svc"}
        key_a = self.runner.generate_idempotency_key("restart_pod", params, "INC-001")
        key_b = self.runner.generate_idempotency_key("restart_pod", params, "INC-002")
        self.assertNotEqual(key_a, key_b)

    def test_idempotency_key_differs_by_tool(self):
        params = {"target": "auth-svc"}
        key_a = self.runner.generate_idempotency_key("restart_pod", params, "INC-001")
        key_b = self.runner.generate_idempotency_key("drain_node", params, "INC-001")
        self.assertNotEqual(key_a, key_b)


if __name__ == "__main__":
    unittest.main()
