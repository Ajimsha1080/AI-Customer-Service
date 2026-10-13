import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

class IncidentManager:
    """
    Manages operational incidents and public status updates.
    """
    def __init__(self):
        self._incidents: List[Dict[str, Any]] = [
            {
                "id": "inc_init_01",
                "title": "Scheduled Enterprise Multi-AZ Hardening",
                "status": "RESOLVED",
                "impact": "NONE",
                "created_at": "2026-10-10T00:00:00Z",
                "resolved_at": "2026-10-10T01:30:00Z",
                "updates": [
                    {
                        "timestamp": "2026-10-10T01:30:00Z",
                        "message": "Zero-downtime maintenance completed successfully across all availability zones."
                    }
                ]
            }
        ]

    def create_incident(self, title: str, impact: str = "MINOR", initial_message: str = "Investigating reported latency.") -> Dict[str, Any]:
        incident = {
            "id": f"inc_{uuid.uuid4().hex[:8]}",
            "title": title,
            "status": "INVESTIGATING",
            "impact": impact,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "resolved_at": None,
            "updates": [
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "message": initial_message
                }
            ]
        }
        self._incidents.insert(0, incident)
        return incident

    def resolve_incident(self, incident_id: str, resolution_message: str = "Issue fully mitigated and verified.") -> Optional[Dict[str, Any]]:
        for inc in self._incidents:
            if inc["id"] == incident_id:
                inc["status"] = "RESOLVED"
                inc["resolved_at"] = datetime.now(timezone.utc).isoformat()
                inc["updates"].append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "message": resolution_message
                })
                return inc
        return None

    def list_incidents(self, active_only: bool = False) -> List[Dict[str, Any]]:
        if active_only:
            return [i for i in self._incidents if i["status"] != "RESOLVED"]
        return list(self._incidents)

incident_manager = IncidentManager()
