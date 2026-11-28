import unittest

from order_budget_controller_regression import make_config, make_controller


class RecoveryTelemetryTests(unittest.TestCase):
    def test_recovery_state_is_published_to_condor(self):
        controller = make_controller(make_config())
        controller.processed_data = {}
        controller.recovery_state = "BLOCKED"

        info = controller.get_custom_info()

        self.assertEqual(info["recovery_state"], "BLOCKED")
        self.assertTrue(info["recovery_blocked"])

        controller.recovery_state = "READY"
        info = controller.get_custom_info()
        self.assertEqual(info["recovery_state"], "READY")
        self.assertFalse(info["recovery_blocked"])


if __name__ == "__main__":
    unittest.main()
