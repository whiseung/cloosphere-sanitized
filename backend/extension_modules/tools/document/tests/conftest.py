"""Document tools test fixtures.

이 fixture 들은 test_pptx_tool / test_docx_tool / test_xlsx_tool 의 단위 테스트가
production DB 의 PersistentConfig 값에 영향받지 않도록 격리한다.
``DOCUMENT_TEMPLATE_*`` config 가 비어있어야 builder 가 built-in 모드로 동작.
"""

import pytest
from extension_modules.tools.document import _common


@pytest.fixture(autouse=True)
def _isolate_template_config_and_cache():
    """모든 document 툴 테스트가 빈 template config / 빈 cache 로 시작/종료."""
    originals = {kind: cfg.value for kind, cfg in _common._KIND_TO_CONFIG.items()}
    for cfg in _common._KIND_TO_CONFIG.values():
        cfg.value = {}
    _common._TEMPLATE_CACHE.clear()

    yield

    _common._TEMPLATE_CACHE.clear()
    for kind, original in originals.items():
        _common._KIND_TO_CONFIG[kind].value = original
