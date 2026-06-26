from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # App
    app_env: str = "production"
    secret_key: str
    log_level: str = "INFO"

    # DB
    database_url: str = Field(
        default="postgresql+psycopg://voiceagent:voiceagent@postgres:5432/voiceagent",
    )

    # Альфа CRM
    alfa_crm_base_url: str = "https://your-tenant.s20.online"
    alfa_crm_api_key: str | None = None
    alfa_crm_email: str | None = None
    alfa_crm_branch_id: int = 1
    # писать ли результат звонаря в карточку лида (нужен маппинг от Бекзата)
    alfa_crm_push_outcome: bool = False
    # JSON-map: {"interested":12,"callback":7,"not_interested":15,"no_answer":3}
    # status_id берутся из Альфа CRM (Settings → Lead statuses).
    alfa_crm_outcome_status_json: str | None = None

    # OnlinePBX
    onlinepbx_domain: str | None = None
    onlinepbx_user: str | None = None
    onlinepbx_password: str | None = None
    onlinepbx_webhook_secret: str | None = None
    # Если =1 → пустой webhook_secret даёт 503 (защита от продовой забывчивости)
    onlinepbx_webhook_secret_required: bool = False

    # Local fallback — если S3-ключи не заданы, складывать локально
    local_recordings_dir: str = "/opt/voiceagent/recordings"
    local_recordings_url_prefix: str = "/recordings"

    # S3 Object Storage (PS.kz pscloud.io)
    s3_endpoint_url: str = "https://object.pscloud.io"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_bucket: str = "voiceagent-recordings"
    s3_region: str = "us-east-1"

    # STT
    assemblyai_api_key: str | None = None
    openai_api_key: str | None = None

    # LLM (OpenAI-only; Anthropic выпилен 2026-05-11)
    anthropic_api_key: str | None = None  # legacy: оставлено для .env-совместимости, не используется
    llm_short_model: str = "gpt-4.1-mini"
    llm_long_model: str = "gpt-4.1"

    # ElevenLabs
    elevenlabs_api_key: str | None = None
    elevenlabs_voice_id: str | None = None

    # TTS audio served via nginx /tts-audio/
    tts_audio_dir: str = "/var/www/tts-audio"
    tts_audio_url_prefix: str = "/tts-audio"

    # Voximplant
    voximplant_account_id: str | None = None
    voximplant_api_key: str | None = None
    voximplant_application_id: str | None = None
    voximplant_email: str | None = None  # для подтверждения, какой аккаунт настроен
    voximplant_rule_id: int | None = None

    # SIP-trunk провайдер (SIP-оператор)
    sip_region: str = "almaty"  # almaty | astana
    sip_accounts_json: str | None = None  # JSON-массив SipAccount, см. shared/sip_settings.py
    sip_public_address: str | None = None  # наш публичный SIP-source (для whitelist SIP-оператор)

    # Green API (WhatsApp)
    green_api_instance_id: str | None = None
    green_api_token: str | None = None
    whatsapp_from_phone: str | None = None

    # Дашборд
    dashboard_base_url: str = "http://localhost"
    session_cookie_secure: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
