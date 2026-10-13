import zlib
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("hospitality_agent_cloud.operations.feature_flags")

class FeatureFlagManager:
    """
    Enterprise Feature Flagging Engine:
    1. Global toggles.
    2. Per-organization targeted rollouts.
    3. Percentage-based deterministic gradual rollouts (consistent hash).
    4. Emergency operational kill switches.
    """
    def __init__(self):
        # flag_key -> {enabled: bool, rollout_pct: int, enabled_orgs: set, disabled_orgs: set}
        self._flags: Dict[str, Dict[str, Any]] = {
            # Operational kill switches (default False means feature active; set True to kill)
            "kill_switch_voice": {"enabled": False, "rollout_pct": 0, "enabled_orgs": set(), "disabled_orgs": set()},
            "kill_switch_llm_tools": {"enabled": False, "rollout_pct": 0, "enabled_orgs": set(), "disabled_orgs": set()},
            "kill_switch_integrations": {"enabled": False, "rollout_pct": 0, "enabled_orgs": set(), "disabled_orgs": set()},

            # Feature flags
            "ai_multilingual_v2": {"enabled": True, "rollout_pct": 100, "enabled_orgs": set(), "disabled_orgs": set()},
            "pms_realtime_sync": {"enabled": True, "rollout_pct": 50, "enabled_orgs": set(), "disabled_orgs": set()},
            "beta_voice_streaming": {"enabled": False, "rollout_pct": 0, "enabled_orgs": set(), "disabled_orgs": set()},
        }

    def set_flag(
        self,
        key: str,
        enabled: bool,
        rollout_pct: int = 100,
        enabled_orgs: Optional[list[str]] = None,
        disabled_orgs: Optional[list[str]] = None
    ):
        self._flags[key] = {
            "enabled": enabled,
            "rollout_pct": max(0, min(100, rollout_pct)),
            "enabled_orgs": set(enabled_orgs or []),
            "disabled_orgs": set(disabled_orgs or [])
        }
        logger.info(f"[FeatureFlags] Flag '{key}' updated: enabled={enabled}, pct={rollout_pct}")

    def activate_kill_switch(self, switch_name: str):
        """Immediately halts traffic for the specified subsystem."""
        self._flags[switch_name] = {
            "enabled": True,
            "rollout_pct": 100,
            "enabled_orgs": set(),
            "disabled_orgs": set()
        }
        logger.critical(f"[KILL_SWITCH_ENGAGED] Critical kill switch '{switch_name}' has been ENGAGED.")

    def deactivate_kill_switch(self, switch_name: str):
        """Deactivates kill switch, resuming normal service."""
        self._flags[switch_name] = {
            "enabled": False,
            "rollout_pct": 0,
            "enabled_orgs": set(),
            "disabled_orgs": set()
        }
        logger.info(f"[KILL_SWITCH_DISENGAGED] Kill switch '{switch_name}' disengaged.")

    def is_kill_switch_active(self, switch_name: str) -> bool:
        flag = self._flags.get(switch_name)
        return bool(flag and flag.get("enabled", False))

    def is_enabled(self, key: str, org_id: str = "global") -> bool:
        # Check associated kill switch if applicable
        if key == "voice" and self.is_kill_switch_active("kill_switch_voice"):
            return False
        if key == "llm_tools" and self.is_kill_switch_active("kill_switch_llm_tools"):
            return False
        if key == "integrations" and self.is_kill_switch_active("kill_switch_integrations"):
            return False

        flag = self._flags.get(key)
        if not flag:
            return False

        # Specific organization blacklist
        if org_id in flag["disabled_orgs"]:
            return False

        # Specific organization whitelist
        if org_id in flag["enabled_orgs"]:
            return True

        if not flag["enabled"]:
            return False

        rollout_pct = flag.get("rollout_pct", 100)
        if rollout_pct >= 100:
            return True
        if rollout_pct <= 0:
            return False

        # Deterministic hashing: crc32(key:org_id) % 100
        h = zlib.crc32(f"{key}:{org_id}".encode("utf-8")) % 100
        return h < rollout_pct

feature_flags = FeatureFlagManager()
