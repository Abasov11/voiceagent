"""Доменные таблицы VoiceAgent. Описаны в docs/ARCHITECTURE.md."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.db import Base


class LeadSegment(StrEnum):
    naborki = "naborki"
    academy = "academy"
    branch = "branch"
    special = "special"
    unknown = "unknown"


class CallDirection(StrEnum):
    inbound = "inbound"
    outbound = "outbound"


class CallOutcome(StrEnum):
    interested = "interested"
    not_interested = "not_interested"
    no_answer = "no_answer"
    callback = "callback"
    error = "error"


class DashboardRole(StrEnum):
    owner = "owner"
    director = "director"
    rop = "rop"
    manager = "manager"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Lead(Base, TimestampMixin):
    __tablename__ = "leads"
    id: Mapped[int] = mapped_column(primary_key=True)
    alfa_crm_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    phone: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str | None] = mapped_column(String(256))
    segment: Mapped[str] = mapped_column(String(32), default=LeadSegment.unknown.value)
    status: Mapped[str | None] = mapped_column(String(64))
    interested: Mapped[bool | None] = mapped_column(Boolean)
    raw: Mapped[dict | None] = mapped_column(JSONB)

    zvonar_calls: Mapped[list["ZvonarCall"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan"
    )
    whatsapp_sends: Mapped[list["WhatsappSend"]] = relationship(
        back_populates="lead", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("phone", name="uq_leads_phone"),)


class Manager(Base, TimestampMixin):
    __tablename__ = "managers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    phone: Mapped[str | None] = mapped_column(String(32))
    onlinepbx_extension: Mapped[str | None] = mapped_column(String(32), index=True)
    role: Mapped[str] = mapped_column(String(32), default="sales")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    calls: Mapped[list["ManagerCall"]] = relationship(
        back_populates="manager", cascade="all, delete-orphan"
    )


class ManagerCall(Base, TimestampMixin):
    __tablename__ = "manager_calls"
    id: Mapped[int] = mapped_column(primary_key=True)
    manager_id: Mapped[int | None] = mapped_column(
        ForeignKey("managers.id", ondelete="SET NULL"), index=True
    )
    onlinepbx_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(32), index=True)
    direction: Mapped[str] = mapped_column(String(16), default=CallDirection.inbound.value)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_s: Mapped[int] = mapped_column(Integer, default=0)
    recording_url_remote: Mapped[str | None] = mapped_column(Text)  # OnlinePBX URL
    recording_url_cloudinary: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict | None] = mapped_column(JSONB)

    manager: Mapped[Manager | None] = relationship(back_populates="calls")
    transcript: Mapped["Transcript | None"] = relationship(
        back_populates="call", uselist=False, cascade="all, delete-orphan"
    )
    scores: Mapped[list["LlmScore"]] = relationship(
        back_populates="call", cascade="all, delete-orphan"
    )
    summary: Mapped["CallSummary | None"] = relationship(
        back_populates="call", uselist=False, cascade="all, delete-orphan"
    )


class Transcript(Base, TimestampMixin):
    __tablename__ = "transcripts"
    id: Mapped[int] = mapped_column(primary_key=True)
    call_id: Mapped[int] = mapped_column(
        ForeignKey("manager_calls.id", ondelete="CASCADE"), unique=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)
    lang: Mapped[str | None] = mapped_column(String(8))
    duration_s: Mapped[int | None] = mapped_column(Integer)
    cost_cents: Mapped[int | None] = mapped_column(Integer)
    raw: Mapped[dict | None] = mapped_column(JSONB)

    call: Mapped[ManagerCall] = relationship(back_populates="transcript")


class LlmScore(Base, TimestampMixin):
    __tablename__ = "llm_scores"
    id: Mapped[int] = mapped_column(primary_key=True)
    call_id: Mapped[int] = mapped_column(
        ForeignKey("manager_calls.id", ondelete="CASCADE"), index=True
    )
    criterion: Mapped[str] = mapped_column(String(64))
    score: Mapped[float] = mapped_column(Numeric(4, 2))
    comment: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(64))

    call: Mapped[ManagerCall] = relationship(back_populates="scores")


class CallSummary(Base, TimestampMixin):
    __tablename__ = "call_summaries"
    id: Mapped[int] = mapped_column(primary_key=True)
    call_id: Mapped[int] = mapped_column(
        ForeignKey("manager_calls.id", ondelete="CASCADE"), unique=True, index=True
    )
    total_score: Mapped[float | None] = mapped_column(Numeric(4, 2))
    funnel_stage: Mapped[str | None] = mapped_column(String(32))  # dialog/deal/lost
    summary: Mapped[str | None] = mapped_column(Text)
    # Двухтрековый коучинговый анализ (ФВР/STAR/GROW). Заполняется при наличии
    # OpenAI-ключа; если LLM упал — оба поля остаются NULL.
    report_for_manager: Mapped[str | None] = mapped_column(Text)
    report_for_rop: Mapped[str | None] = mapped_column(Text)

    call: Mapped[ManagerCall] = relationship(back_populates="summary")


class ZvonarCall(Base, TimestampMixin):
    __tablename__ = "zvonar_calls"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), index=True
    )
    voximplant_session_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_s: Mapped[int] = mapped_column(Integer, default=0)
    outcome: Mapped[str] = mapped_column(String(32), default=CallOutcome.no_answer.value)
    transcript: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict | None] = mapped_column(JSONB)

    lead: Mapped[Lead] = relationship(back_populates="zvonar_calls")


class WhatsappSend(Base, TimestampMixin):
    __tablename__ = "whatsapp_sends"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), index=True
    )
    template: Mapped[str] = mapped_column(String(128))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    green_api_message_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    read: Mapped[bool] = mapped_column(Boolean, default=False)

    lead: Mapped[Lead] = relationship(back_populates="whatsapp_sends")


class DashboardUser(Base, TimestampMixin):
    __tablename__ = "dashboard_users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    full_name: Mapped[str | None] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(32), default=DashboardRole.manager.value)
    manager_id: Mapped[int | None] = mapped_column(
        ForeignKey("managers.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ExistingClient(Base, TimestampMixin):
    """Уже-клиенты школы (do-not-call список + кандидаты на upsell).

    Источник — выгрузка от клиента «база_клиентов.xlsx» 2026-05-02
    (839 строк, ~1098 нормализованных номеров с учётом нескольких
    телефонов в ячейке). Лиду из CRM с совпадающим телефоном звонарь
    не звонит — родитель уже в школе. Используется через
    `shared.existing_clients.is_existing_client()`.
    """
    __tablename__ = "existing_clients"
    id: Mapped[int] = mapped_column(primary_key=True)
    phone: Mapped[str] = mapped_column(String(32), index=True)
    full_name: Mapped[str | None] = mapped_column(String(256))
    active_groups: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(64), default="manual_import")

    __table_args__ = (UniqueConstraint("phone", name="uq_existing_clients_phone"),)


class ApiCallLog(Base, TimestampMixin):
    """Аудит-лог внешних API (для оценки расходов и отладки)."""
    __tablename__ = "api_call_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    operation: Mapped[str] = mapped_column(String(64))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    cost_cents: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(String(16))
    request: Mapped[dict | None] = mapped_column(JSONB)
    response: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)


class AgentSetting(Base, TimestampMixin):
    """Простые настройки агента (имя, голос, школа). Key-value.

    Редактируется клиентом через `/admin/settings`. Читается через
    `shared.agent_config.get_setting(key)` с кэшем TTL 60с.
    """
    __tablename__ = "agent_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(256))


class ContentBlock(Base, TimestampMixin):
    """Редактируемый блок контента для system_prompt / WhatsApp-шаблона.

    Клиент через `/admin/scripts` может править существующие блоки и
    создавать новые. `is_system=true` — блок нельзя удалить, только править
    или восстановить из `default_body`. `scopes=['voice','whatsapp']` —
    куда попадает блок при сборке. Порядок задаётся `order_index`.
    """
    __tablename__ = "content_blocks"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    format: Mapped[str] = mapped_column(String(16), default="text")
    order_index: Mapped[int] = mapped_column(Integer, default=100, index=True)
    scopes: Mapped[list[str]] = mapped_column(JSONB, default=lambda: ["voice"])
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    default_body: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[str | None] = mapped_column(String(256))

    versions: Mapped[list["ContentBlockVersion"]] = relationship(
        back_populates="block", cascade="all, delete-orphan",
        order_by="desc(ContentBlockVersion.created_at)",
    )


class ContentBlockVersion(Base):
    """История изменений content_blocks (для отката)."""
    __tablename__ = "content_block_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    block_id: Mapped[int] = mapped_column(
        ForeignKey("content_blocks.id", ondelete="CASCADE"), index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(String(16), default="text")
    updated_by: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    block: Mapped[ContentBlock] = relationship(back_populates="versions")


class Promotion(Base, TimestampMixin):
    """Акция/промо — временный блок текста, инжектится в промпт+WhatsApp.

    `active_from`/`active_to` могут быть NULL → «активна сразу/без срока».
    `is_active` — мастер-выключатель для немедленного отключения без
    удаления. `scopes` определяет где будет видно (voice/whatsapp).
    """
    __tablename__ = "promotions"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    active_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    scopes: Mapped[list[str]] = mapped_column(
        JSONB, default=lambda: ["voice", "whatsapp"]
    )
    updated_by: Mapped[str | None] = mapped_column(String(256))


class QualificationCategory(Base, TimestampMixin):
    """Категория фраз для классификации диалога.

    Системные категории (`is_system=true`): training_interest, camp_interest,
    not_interested, callback. Клиент может добавить произвольные категории
    с любым `kind` (interest/not_interested/callback/custom).
    """
    __tablename__ = "qualification_categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    phrases: Mapped[list[str]] = mapped_column(JSONB, default=list)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    default_phrases: Mapped[list[str] | None] = mapped_column(JSONB)
    updated_by: Mapped[str | None] = mapped_column(String(256))


class CallCostBreakdown(Base, TimestampMixin):
    """Unit-economics одного звонка по компонентам.

    Source-of-truth для дашборда: показывает разбивку cost_cents по
    SIP-минутам / TTS-секундам / STT-минутам / LLM-токенам.
    Один ряд = один входящий менеджерский звонок ИЛИ один исходящий звонарь-звонок
    (XOR — заполнен либо manager_call_id, либо zvonar_call_id).
    """
    __tablename__ = "call_cost_breakdown"
    id: Mapped[int] = mapped_column(primary_key=True)
    manager_call_id: Mapped[int | None] = mapped_column(
        ForeignKey("manager_calls.id", ondelete="CASCADE"), index=True
    )
    zvonar_call_id: Mapped[int | None] = mapped_column(
        ForeignKey("zvonar_calls.id", ondelete="CASCADE"), index=True
    )
    sip_seconds: Mapped[int] = mapped_column(Integer, default=0)
    tts_seconds: Mapped[int] = mapped_column(Integer, default=0)
    stt_seconds: Mapped[int] = mapped_column(Integer, default=0)
    llm_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    llm_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    sip_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    tts_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    stt_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    llm_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    provider_notes: Mapped[dict | None] = mapped_column(JSONB)
