import time
import uuid
from locust import HttpUser, task, between

class GuestChatUser(HttpUser):
    wait_time = between(0.5, 2.0)

    def on_start(self):
        self.agent_id = "agt_test_concierge"
        self.session_id = f"guest_session_{uuid.uuid4().hex[:8]}"

    @task(3)
    def test_guest_chat_latency(self):
        """Simulate concurrent guest inquiry and assert first token latency < 3s."""
        payload = {
            "message": "What time is checkout and what dining options are open today?",
            "channel": "web_widget",
            "session_id": self.session_id
        }
        start = time.time()
        with self.client.post(
            f"/api/v1/agents/{self.agent_id}/chat",
            json=payload,
            catch_response=True
        ) as response:
            latency = time.time() - start
            if response.status_code == 200:
                if latency > 3.0:
                    response.failure(f"SLA Violation: Latency {latency:.2f}s > 3.0s")
                else:
                    response.success()
            else:
                response.failure(f"HTTP {response.status_code}: {response.text}")

    @task(1)
    def test_health_check(self):
        """Monitor API health endpoint."""
        self.client.get("/health")
