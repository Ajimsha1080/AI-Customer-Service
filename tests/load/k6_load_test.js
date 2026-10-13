import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '30s', target: 50 },
    { duration: '1m', target: 200 }, // 200 concurrent guest chats
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    http_req_duration: ['p(95)<3000'], // p95 response time < 3000ms
    http_req_failed: ['rate<0.01'],    // error rate < 1%
  },
};

const BASE_URL = __ENV.API_BASE || 'http://localhost:8000';

export default function () {
  const payload = JSON.stringify({
    message: 'What are the pool and restaurant operating hours today?',
    channel: 'web_widget',
  });

  const params = {
    headers: {
      'Content-Type': 'application/json',
    },
  };

  const res = http.post(`${BASE_URL}/api/v1/agents/agt_test_concierge/chat`, payload, params);

  check(res, {
    'status is 200 or 404 (agent not found)': (r) => r.status === 200 || r.status === 404,
    'response under 3s': (r) => r.timings.duration < 3000,
  });

  sleep(1);
}
