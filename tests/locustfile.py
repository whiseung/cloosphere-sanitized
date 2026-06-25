"""
Cloosphere Load Test

Usage:
    # Web UI (브라우저에서 설정)
    locust -f tests/locustfile.py --host https://cloosphere.azurewebsites.net

    # API만 테스트 (LLM 비용 없음)
    LOCUST_API_KEY=sk-xxx locust -f tests/locustfile.py \
        --host https://cloosphere.azurewebsites.net --tags api

    # 채팅 포함 (LLM 비용 발생 주의)
    LOCUST_API_KEY=sk-xxx LOCUST_CHAT_MODEL=cloosphere locust -f tests/locustfile.py \
        --host https://cloosphere.azurewebsites.net --tags chat

Environment Variables:
    LOCUST_API_KEY: API key for authentication (required)
    LOCUST_CHAT_MODEL: Model ID for chat test (default: first available model)
"""

import os
import random
import uuid

from locust import HttpUser, between, events, tag, task

# ─────────────────────────────────
# 테스트 시나리오 정의
# - 단독 질의: 문자열 1개
# - 순차 질의: 리스트 (이전 대화 컨텍스트 유지)
# ─────────────────────────────────
CHAT_SCENARIOS = [
    # 1. 단독 — 간단한 인사
    "안녕하세요",
    # 2. 단독 — 단순 계산
    "1+1은 뭐야?",
    # 3. 단독 — 긴 응답 유도
    "Python의 주요 특징 5가지를 설명해줘",
    # 4. 단독 — 코드 생성
    "Python으로 피보나치 수열 함수를 작성해줘",
    # 5. 단독 — 번역
    "다음 문장을 영어로 번역해줘: 오늘 회의는 3시에 시작합니다",
    # 6. 순차 — 데이터 분석 시나리오
    [
        "최근 한 달간 일별 매출 추이를 알려줘",
        "그 중 매출이 가장 높은 날은 언제야?",
        "그 날의 상세 내역을 보여줘",
    ],
    # 7. 순차 — 보고서 작성
    [
        "우리 회사 서비스 현황을 요약해줘",
        "개선이 필요한 부분을 3가지 뽑아줘",
    ],
    # 8. 단독 — 긴 입력
    "다음 텍스트를 요약해줘: 인공지능(AI)은 인간의 학습능력, 추론능력, 지각능력을 인공적으로 구현하려는 컴퓨터 과학의 세부분야로, 정보공학 분야에 포함되기도 한다. 인공지능이란 용어는 1956년 존 매카시가 제안했으며, 현재는 기계학습과 딥러닝을 중심으로 빠르게 발전하고 있다.",
    # 9. 순차 — 비교 분석
    [
        "AWS와 Azure의 차이점을 알려줘",
        "비용 측면에서는 어떤 게 유리해?",
        "중소기업에 추천하는 건?",
    ],
    # 10. 단독 — JSON 생성
    "사용자 프로필 JSON 예시를 만들어줘. 이름, 이메일, 나이, 취미 포함",
]


# 최대 실행 시간 (기본 10분, LOCUST_MAX_RUN_TIME 환경변수로 변경 가능)
MAX_RUN_TIME = os.environ.get("LOCUST_MAX_RUN_TIME", "10m")


@events.init.add_listener
def on_init(environment, **kwargs):
    environment.parsed_options.run_time = MAX_RUN_TIME


class CloosphereUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        api_key = os.environ.get("LOCUST_API_KEY", "")
        if not api_key:
            raise ValueError(
                "LOCUST_API_KEY environment variable is required. "
                "Set it to your Cloosphere API key."
            )
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self.chat_model = os.environ.get("LOCUST_CHAT_MODEL", "")
        self.models = []
        self.session_id = str(uuid.uuid4())
        self.user_name = "LoadTest User"

    # ─────────────────────────────────
    # API Tests (tag: api)
    # ─────────────────────────────────

    @tag("api")
    @task(5)
    def get_config(self):
        self.client.get("/api/config", name="/api/config")

    @tag("api")
    @task(3)
    def get_models(self):
        resp = self.client.get("/api/models", headers=self.headers, name="/api/models")
        if resp.status_code == 200:
            data = resp.json()
            self.models = [m["id"] for m in data.get("data", [])]

    @tag("api")
    @task(3)
    def get_chats(self):
        self.client.get(
            "/api/v1/chats/?page=1",
            headers=self.headers,
            name="/api/v1/chats",
        )

    @tag("api")
    @task(2)
    def get_user(self):
        self.client.get(
            "/api/v1/users/",
            headers=self.headers,
            name="/api/v1/users",
        )

    @tag("api")
    @task(1)
    def get_knowledge(self):
        self.client.get(
            "/api/v1/knowledge/",
            headers=self.headers,
            name="/api/v1/knowledge",
        )

    @tag("api")
    @task(1)
    def get_prompts(self):
        self.client.get(
            "/api/v1/prompts/",
            headers=self.headers,
            name="/api/v1/prompts",
        )

    @tag("api")
    @task(1)
    def get_tools(self):
        self.client.get(
            "/api/v1/tools/",
            headers=self.headers,
            name="/api/v1/tools",
        )

    # ─────────────────────────────────
    # Chat Tests (tag: chat)
    # 프론트엔드와 동일한 payload 구조
    # ─────────────────────────────────

    def _build_chat_payload(self, model, messages, chat_id, message_id, is_first):
        """프론트엔드 Chat.svelte와 동일한 payload 구성"""
        payload = {
            "stream": False,
            "model": model,
            "messages": messages,
            "chat_id": chat_id,
            "id": message_id,
            "session_id": self.session_id,
            "params": {},
            "features": {
                "image_generation": False,
                "web_search": False,
            },
            "variables": {
                "user_name": self.user_name,
            },
        }

        # 첫 메시지일 때만 background_tasks 포함
        if is_first:
            payload["background_tasks"] = {
                "title_generation": True,
                "tags_generation": True,
            }

        return payload

    @tag("chat")
    @task(1)
    def chat_completion(self):
        model = self.chat_model
        if not model and self.models:
            model = random.choice(self.models)
        if not model:
            resp = self.client.get(
                "/api/models", headers=self.headers, name="/api/models"
            )
            if resp.status_code == 200:
                self.models = [m["id"] for m in resp.json().get("data", [])]
                if self.models:
                    model = self.models[0]
            if not model:
                return

        scenario = random.choice(CHAT_SCENARIOS)
        chat_id = str(uuid.uuid4())

        # 단독 질의
        if isinstance(scenario, str):
            message_id = str(uuid.uuid4())
            payload = self._build_chat_payload(
                model=model,
                messages=[{"role": "user", "content": scenario}],
                chat_id=chat_id,
                message_id=message_id,
                is_first=True,
            )
            self.client.post(
                "/api/chat/completions",
                headers=self.headers,
                json=payload,
                name="/api/chat/completions [single]",
                timeout=120,
            )
            return

        # 순차 질의 — 대화 히스토리 유지
        messages = []
        for i, question in enumerate(scenario):
            message_id = str(uuid.uuid4())
            messages.append({"role": "user", "content": question})

            payload = self._build_chat_payload(
                model=model,
                messages=messages.copy(),
                chat_id=chat_id,
                message_id=message_id,
                is_first=(i == 0),
            )
            resp = self.client.post(
                "/api/chat/completions",
                headers=self.headers,
                json=payload,
                name=f"/api/chat/completions [multi Q{i + 1}/{len(scenario)}]",
                timeout=120,
            )

            if resp.status_code == 200:
                try:
                    data = resp.json()
                    assistant_msg = (
                        data.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                    )
                    messages.append({"role": "assistant", "content": assistant_msg})
                except Exception:
                    break
            else:
                break
