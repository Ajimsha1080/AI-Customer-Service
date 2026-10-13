from typing import Dict, Any, Optional
from fastapi import HTTPException, status

SUPPORTED_REGIONS = {"US", "EU", "IN"}

REGION_ENDPOINTS: Dict[str, Dict[str, str]] = {
    "US": {
        "db_cluster": "us-east-1.db.internal",
        "vector_store": "https://vector-us-east-1.pinecone.io",
        "storage_bucket": "s3-us-east-1-hospitality-vault",
        "llm_endpoint": "https://api.openai.com/v1"
    },
    "EU": {
        "db_cluster": "eu-central-1.db.internal",
        "vector_store": "https://vector-eu-central-1.pinecone.io",
        "storage_bucket": "s3-eu-central-1-hospitality-vault",
        "llm_endpoint": "https://eu.api.anthropic.com/v1"
    },
    "IN": {
        "db_cluster": "ap-south-1.db.internal",
        "vector_store": "https://vector-ap-south-1.pinecone.io",
        "storage_bucket": "s3-ap-south-1-hospitality-vault",
        "llm_endpoint": "https://in.api.google.com/v1"
    }
}

class DataResidencyRouter:
    """Enterprise Data Residency Enforcement.
    Pins DB, Vector Store, File Storage, and LLM routing strictly within the tenant's designated legal region.
    Prevents cross-border data transfers violating GDPR / DPDP statutes.
    """
    def __init__(self):
        self.endpoints = REGION_ENDPOINTS

    def get_region_config(self, region: str) -> Dict[str, str]:
        reg_clean = region.upper() if region else "US"
        if reg_clean not in SUPPORTED_REGIONS:
            raise ValueError(f"Unsupported data residency region '{region}'. Must be one of {SUPPORTED_REGIONS}")
        return self.endpoints[reg_clean]

    def validate_regional_call(self, tenant_region: str, target_resource_region: str) -> bool:
        """Verifies an outbound call does not violate the tenant's data residency boundary."""
        t_reg = (tenant_region or "US").upper()
        res_reg = (target_resource_region or "US").upper()
        if t_reg != res_reg:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"DATA_RESIDENCY_VIOLATION: Tenant pinned to {t_reg} cannot transmit data to {res_reg} infrastructure."
            )
        return True

data_residency_router = DataResidencyRouter()
