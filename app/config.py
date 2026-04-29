from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Thronos EduPresence"
    environment: str = "development"
    database_url: str = "sqlite:///./data/edupresence_v4.db"
    public_base_url: str = "http://localhost:8000"
    token_secret: str = "change-me-use-a-long-random-secret"
    token_issuer: str = "thronos-edupresence"
    qr_ttl_seconds: int = 70
    student_link_ttl_hours: int = 8
    thronos_attest_url: str = ""
    thronos_attest_api_key: str = ""
    auto_seed_demo: bool = True

    # Login / gov.gr / TaxisNet entrypoint.
    # mock mode keeps the app usable for field tests without real gov credentials.
    auth_required: bool = False
    auth_provider: str = "mock"  # mock | gov
    session_cookie_name: str = "thronos_edu_session"
    session_ttl_hours: int = 12
    mock_user_full_name: str = "ΓΙΩΡΓΟΣ ΔΗΜΟΠΟΥΛΟΣ"
    mock_user_tax_id: str = "000000000"
    mock_user_role: str = "teacher"
    gov_oauth_authorize_url: str = ""
    gov_oauth_token_url: str = ""
    gov_oauth_userinfo_url: str = ""
    gov_oauth_client_id: str = ""
    gov_oauth_client_secret: str = ""
    gov_oauth_redirect_uri: str = ""

    # SMS / notification settings.
    # Default mock mode writes messages to the SMS outbox without calling a real provider.
    sms_provider: str = "mock"  # mock | twilio | http_get
    sms_dry_run: bool = False
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    generic_sms_url: str = ""
    generic_sms_token: str = ""

settings = Settings()
