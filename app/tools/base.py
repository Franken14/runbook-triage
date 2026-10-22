from enum import Enum
from typing import Callable, Dict, Any, Optional

try:
    from pydantic import BaseModel, Field

    class ToolDefinition(BaseModel):
        name: str
        description: str
        tool_type: Any
        risk_level: Any
        parameters_schema: Dict[str, Any]
        requires_approval: bool = False

except ImportError:
    from dataclasses import dataclass

    @dataclass
    class ToolDefinition:  # type: ignore
        name: str
        description: str
        tool_type: Any
        risk_level: Any
        parameters_schema: Dict[str, Any]
        requires_approval: bool = False


class ToolType(str, Enum):
    DIAGNOSTIC = "DIAGNOSTIC"     # Safe, Read-Only, No approval required
    REMEDIATION = "REMEDIATION"   # Mutating, State-altering, Approval required


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
