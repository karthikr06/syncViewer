from app.models.alerting import Alert, AlertRule
from app.models.base import Base
from app.models.cloud import CloudAccount, Resource, ResourceType, VmAction
from app.models.identity import Provider, Role, User, Workspace, WorkspaceInvite
from app.models.insights import AgentRun, InsightDigest, Recommendation
from app.models.metrics import Incident, MetricDefinition, MetricSample, UptimeRollup
from app.models.ops import AuditLog, CollectorRun

SYNCED_TABLES = (
    "resources",
    "cloud_accounts",
    "alert_rules",
    "alerts",
    "recommendations",
    "insight_digests",
    "incidents",
    "uptime_rollups",
)

__all__ = [
    "SYNCED_TABLES",
    "AgentRun",
    "Alert",
    "AlertRule",
    "AuditLog",
    "Base",
    "CloudAccount",
    "CollectorRun",
    "Incident",
    "InsightDigest",
    "MetricDefinition",
    "MetricSample",
    "Provider",
    "Recommendation",
    "Resource",
    "ResourceType",
    "Role",
    "UptimeRollup",
    "User",
    "VmAction",
    "Workspace",
    "WorkspaceInvite",
]
