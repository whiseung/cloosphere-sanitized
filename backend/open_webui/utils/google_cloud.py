def resolve_gcp_credentials(app, feature_specific_key: str = "") -> str:
    """
    GCP 서비스 계정 키 3단계 폴백:
    1. 기능별 키 → 2. 전역 키 → 3. "" (호출자가 ADC 처리)
    """
    if feature_specific_key:
        return feature_specific_key
    global_key = getattr(
        getattr(getattr(app, "state", None), "config", None),
        "GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY",
        "",
    )
    return global_key or ""
