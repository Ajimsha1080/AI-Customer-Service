import time
import logging
from typing import Dict, Any
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("hospitality_agent_cloud.operations.metrics")

class PrometheusMetricsRegistry:
    """
    In-memory Prometheus-compatible metric registry exposing RED metrics
    (Rate, Errors, Duration) and business KPIs per tenant.
    """
    def __init__(self):
        # http_requests_total{method="...", path="...", status="...", org_id="..."}
        self.http_requests_total: Dict[tuple, int] = {}
        # http_request_duration_seconds{method="...", path="...", org_id="..."} -> list of durations
        self.http_request_durations: Dict[tuple, list[float]] = {}
        # llm_tokens_total{provider="...", org_id="..."}
        self.llm_tokens_total: Dict[tuple, int] = {}
        # llm_cost_usd_total{provider="...", org_id="..."}
        self.llm_cost_total: Dict[tuple, float] = {}
        # reservations_created_total{org_id="..."}
        self.reservations_created_total: Dict[str, int] = {}

    def record_http_request(self, method: str, path: str, status_code: int, duration_sec: float, org_id: str = "global"):
        key = (method, path, str(status_code), org_id)
        self.http_requests_total[key] = self.http_requests_total.get(key, 0) + 1

        dur_key = (method, path, org_id)
        if dur_key not in self.http_request_durations:
            self.http_request_durations[dur_key] = []
        if len(self.http_request_durations[dur_key]) < 1000:
            self.http_request_durations[dur_key].append(duration_sec)

    def record_llm_usage(self, provider: str, tokens: int, cost_usd: float, org_id: str = "global"):
        tok_key = (provider, org_id)
        self.llm_tokens_total[tok_key] = self.llm_tokens_total.get(tok_key, 0) + tokens
        self.llm_cost_total[tok_key] = self.llm_cost_total.get(tok_key, 0.0) + cost_usd

    def record_reservation(self, org_id: str):
        self.reservations_created_total[org_id] = self.reservations_created_total.get(org_id, 0) + 1

    def generate_prometheus_format(self) -> str:
        lines = []
        # HELP & TYPE for http_requests_total
        lines.append("# HELP http_requests_total Total number of HTTP requests processed")
        lines.append("# TYPE http_requests_total counter")
        for (m, p, s, o), count in self.http_requests_total.items():
            lines.append(f'http_requests_total{{method="{m}",path="{p}",status="{s}",organization_id="{o}"}} {count}')

        # HELP & TYPE for http_request_duration_seconds
        lines.append("# HELP http_request_duration_seconds Latency summary of HTTP requests")
        lines.append("# TYPE http_request_duration_seconds summary")
        for (m, p, o), durs in self.http_request_durations.items():
            if durs:
                count = len(durs)
                total = sum(durs)
                lines.append(f'http_request_duration_seconds_count{{method="{m}",path="{p}",organization_id="{o}"}} {count}')
                lines.append(f'http_request_duration_seconds_sum{{method="{m}",path="{p}",organization_id="{o}"}} {total:.6f}')

        # HELP & TYPE for llm_tokens_total
        lines.append("# HELP llm_tokens_total Total tokens consumed by AI Concierge")
        lines.append("# TYPE llm_tokens_total counter")
        for (prov, o), tokens in self.llm_tokens_total.items():
            lines.append(f'llm_tokens_total{{provider="{prov}",organization_id="{o}"}} {tokens}')

        # HELP & TYPE for llm_cost_usd_total
        lines.append("# HELP llm_cost_usd_total Total estimated LLM cost in USD")
        lines.append("# TYPE llm_cost_usd_total counter")
        for (prov, o), cost in self.llm_cost_total.items():
            lines.append(f'llm_cost_usd_total{{provider="{prov}",organization_id="{o}"}} {cost:.4f}')

        # HELP & TYPE for reservations_created_total
        lines.append("# HELP reservations_created_total Total confirmed reservations")
        lines.append("# TYPE reservations_created_total counter")
        for o, r_count in self.reservations_created_total.items():
            lines.append(f'reservations_created_total{{organization_id="{o}"}} {r_count}')

        return "\n".join(lines) + "\n"

metrics_registry = PrometheusMetricsRegistry()

class PrometheusMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/metrics":
            return await call_next(request)

        start = time.time()
        response = await call_next(request)
        duration = time.time() - start

        org_id = request.headers.get("X-Tenant-ID") or getattr(request.state, "tenant_id", "global")
        # Standardize path to avoid high-cardinality explosions
        path = request.url.path
        if path.startswith("/api/v1/auth/sessions/"):
            path = "/api/v1/auth/sessions/:id"

        metrics_registry.record_http_request(
            method=request.method,
            path=path,
            status_code=response.status_code,
            duration_sec=duration,
            org_id=org_id
        )
        return response
