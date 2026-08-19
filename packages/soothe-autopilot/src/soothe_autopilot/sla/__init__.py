"""SLA monitoring — overdue gap detection and tiered escalation alerts.

Detects goals whose gap items remain unresolved past configured SLA
thresholds and dispatches escalation alerts through the existing
notification infrastructure (email, webhook, Feishu).
"""

from soothe_autopilot.sla.models import SlaBreach, SlaMonitorResult, SlaTier
from soothe_autopilot.sla.monitor import SlaMonitor

__all__ = [
    "SlaBreach",
    "SlaMonitor",
    "SlaMonitorResult",
    "SlaTier",
]
