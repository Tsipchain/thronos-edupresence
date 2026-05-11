from pydantic_settings import BaseSettings
from functools import cached_property

class Settings(BaseSettings):
    app_name: str = "Thronos EduPresence"
    environment: str = "development"

    database_url: str = "sqlite:////data/edupresence_v4.db"
    public_base_url: str = "http://localhost:8000"

    # Auth
    auth_provider: str = "mock"  # mock | gov
    auth_required: bool = False
    gov_oauth_authorize_url: str = ""
    gov_oauth_client_id: str = ""
    gov_oauth_redirect_uri: str = ""

    # Mock teacher user
    mock_user_tax_id: str = "123456789"
    mock_user_full_name: str = "Teacher Demo"
    mock_user_role: str = "teacher"

    # Session / tokens
    token_secret: str = "change-me-use-a-long-random-secret"
    token_issuer: str = "thronos-edupresence"
    session_ttl_hours: int = 24
    session_cookie_name: str = "thronos_session"

    qr_ttl_seconds: int = 70
    student_link_ttl_hours: int = 8
    auto_seed_demo: bool = True

    cors_origins: str = (
        "http://localhost:3000,http://localhost:8081,"
        "http://localhost:19006,http://localhost:19007,exp://localhost:8081"
    )

    # SMS Providers: viber | telesign | mock
    sms_provider: str = "mock"
    sms_dry_run: bool = False

    # Viber Bot API
    viber_bot_token: str = ""
    viber_sender_name: str = "ThrEDU"

    # Telesign SMS API
    telesign_customer_id: str = ""
    telesign_api_key: str = ""
    telesign_phone_number: str = "+1234567890"

    # SMTP Email
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@thronoschain.org"

    # L2E Integration (main chain)
    l2e_enabled: bool = False
    l2e_base_url: str = "https://api.thronoschain.org"
    l2e_api_key: str = ""
    l2e_tenant_id: str = "ministry_edu"
    l2e_attendance_threshold_pct: int = 80

    # Thronos attestation chain (optional)
    thronos_attest_url: str = ""
    thronos_attest_api_key: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"  # ignore unknown env vars (Railway injects many)

settings = Settings()
