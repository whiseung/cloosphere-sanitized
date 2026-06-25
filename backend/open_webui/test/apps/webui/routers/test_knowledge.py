"""Knowledge router 통합 테스트.

핵심 회귀 케이스 — `access_control=None` (공개) 으로 토글 시 DB 가 실제로
``access_control IS NULL`` 로 갱신되는지. 이전에는
``form_data.model_dump(exclude_none=True)`` 가 명시 None 을 dump 결과에서
누락시켜 setattr 가 호출되지 않았다. (`models/knowledge.py:185-188`)
"""

from test.util.abstract_integration_test import AbstractPostgresTest
from test.util.mock_user import mock_webui_user


class TestKnowledge(AbstractPostgresTest):
    BASE_PATH = "/api/v1/knowledge"

    def _create_kb(self, user_id: str, name: str = "kb1", access_control=None):
        with mock_webui_user(id=user_id):
            response = self.fast_api_client.post(
                self.create_url("/create"),
                json={
                    "name": name,
                    "description": "test",
                    "access_control": access_control,
                },
            )
        assert response.status_code == 200, response.text
        return response.json()

    def _get_kb(self, user_id: str, kb_id: str):
        with mock_webui_user(id=user_id, role="admin"):
            response = self.fast_api_client.get(self.create_url(f"/{kb_id}"))
        assert response.status_code == 200, response.text
        return response.json()

    def test_update_knowledge_explicit_null_access_control(self):
        """비공개({}) -> 공개(null) 토글이 DB 까지 반영되는지."""
        kb = self._create_kb(user_id="2", access_control={})
        kb_id = kb["id"]

        with mock_webui_user(id="2"):
            response = self.fast_api_client.post(
                self.create_url(f"/{kb_id}/update"),
                json={
                    "name": kb["name"],
                    "description": kb["description"],
                    "access_control": None,  # 명시 null = public
                },
            )
        assert response.status_code == 200, response.text

        refreshed = self._get_kb(user_id="2", kb_id=kb_id)
        assert refreshed["access_control"] is None

    def test_update_knowledge_explicit_dict_access_control(self):
        """공개(null) -> 비공개({}) 회귀: 기존에도 동작했어야 하므로 보장."""
        kb = self._create_kb(user_id="2", access_control=None)
        kb_id = kb["id"]
        assert kb["access_control"] is None

        with mock_webui_user(id="2"):
            response = self.fast_api_client.post(
                self.create_url(f"/{kb_id}/update"),
                json={
                    "name": kb["name"],
                    "description": kb["description"],
                    "access_control": {},
                },
            )
        assert response.status_code == 200, response.text

        refreshed = self._get_kb(user_id="2", kb_id=kb_id)
        assert refreshed["access_control"] == {}

    def test_update_knowledge_omitted_access_control_preserved(self):
        """access_control 을 누락하면 기존 값이 그대로 보존되어야 한다.
        (exclude_none + model_fields_set 분기의 핵심 회귀 보장)
        """
        kb = self._create_kb(
            user_id="2",
            access_control={"read": {"group_ids": [], "user_ids": ["other"]}},
        )
        kb_id = kb["id"]
        original_acl = kb["access_control"]
        assert original_acl is not None

        with mock_webui_user(id="2"):
            response = self.fast_api_client.post(
                self.create_url(f"/{kb_id}/update"),
                json={
                    "name": "renamed",
                    "description": kb["description"],
                    # access_control 누락 — 기존 값 보존되어야
                },
            )
        assert response.status_code == 200, response.text

        refreshed = self._get_kb(user_id="2", kb_id=kb_id)
        assert refreshed["access_control"] == original_acl
        assert refreshed["name"] == "renamed"
