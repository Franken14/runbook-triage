import unittest
from app.tools import ALL_TOOLS, ToolType, RiskLevel


class TestToolGuardrails(unittest.TestCase):
    def test_all_tools_have_valid_definitions(self):
        self.assertGreater(len(ALL_TOOLS), 0)
        for name, tool in ALL_TOOLS.items():
            self.assertEqual(name, tool.name)
            self.assertIn(tool.tool_type, [ToolType.DIAGNOSTIC, ToolType.REMEDIATION])
            self.assertIn(tool.risk_level, [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL])

    def test_diagnostic_tools_do_not_require_approval(self):
        diagnostic_tools = [t for t in ALL_TOOLS.values() if t.tool_type == ToolType.DIAGNOSTIC]
        self.assertGreater(len(diagnostic_tools), 0)
        for tool in diagnostic_tools:
            self.assertFalse(tool.requires_approval, f"Diagnostic tool '{tool.name}' should not require approval")
            self.assertEqual(tool.risk_level, RiskLevel.LOW)

    def test_remediation_tools_require_approval(self):
        remediation_tools = [t for t in ALL_TOOLS.values() if t.tool_type == ToolType.REMEDIATION]
        self.assertGreater(len(remediation_tools), 0)
        for tool in remediation_tools:
            self.assertTrue(tool.requires_approval, f"Remediation tool '{tool.name}' must require approval")
            self.assertIn(tool.risk_level, [RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL])


if __name__ == "__main__":
    unittest.main()
