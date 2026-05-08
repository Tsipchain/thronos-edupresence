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

    # CORS - comma-separated origins for Flutter/mobile clients
    cors_origins: str = "http://localhost:3000,http://localhost:8080"

    # Login / gov.gr / TaxisNet
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

    # SMS / notifications
    sms_provider: str = "mock"  # mock | twilio | http_get | viber
    sms_dry_run: bool = False
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    generic_sms_url: str = ""
    generic_sms_token: str = ""

    # Viber Business Messages
    viber_bot_token: str = ""
    viber_sender_name: str = "ThrEDuPresence"
    viber_min_api_version: int = 1

    # SMTP email
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_use_tls: bool = True
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "noreply@thronoschain.org"
    smtp_from_name: str = "Thronos EduPresence"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

settings = Settings()
