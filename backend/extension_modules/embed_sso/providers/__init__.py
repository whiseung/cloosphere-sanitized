"""SSO provider implementations.

새 provider 추가 방법:
    1. 이 디렉토리에 새 모듈 작성 (예: `okta.py`)
    2. `BaseSSOProvider` 상속 후 `verify()` 구현
    3. 모듈 최하단에서 `register_provider("okta", OktaProvider)` 호출
    4. `extension_modules/embed_sso/registry.py`의 import 목록에 추가
"""

from .base import BaseSSOProvider

__all__ = ["BaseSSOProvider"]
