import uuid
import enum
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import (
    Column, String, Text, Boolean, Integer, Float, DateTime, ForeignKey, Enum as SQLEnum, JSON, Numeric, Index
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from services.database.session import Base

def generate_uuid():
    return str(uuid.uuid4())

def get_utc_now():
    return datetime.now(timezone.utc)

class UserRole(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ORGANIZATION_ADMIN = "ORGANIZATION_ADMIN"
    PROPERTY_ADMIN = "PROPERTY_ADMIN"
    MANAGER = "MANAGER"
    RECEPTIONIST = "RECEPTIONIST"
    STAFF = "STAFF"
    SUPPORT_AGENT = "SUPPORT_AGENT"
    ANALYST = "ANALYST"
    GUEST = "GUEST"

class AgentStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    CONFIGURING = "CONFIGURING"
    VALIDATING = "VALIDATING"
    DEPLOYING = "DEPLOYING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    FAILED = "FAILED"
    DISABLED = "DISABLED"

class AgentType(str, enum.Enum):
    CONCIERGE = "CONCIERGE"
    BOOKING = "BOOKING"
    AVAILABILITY = "AVAILABILITY"
    SUPPORT = "SUPPORT"
    ACTIVITIES = "ACTIVITIES"
    RESTAURANT = "RESTAURANT"
    VOICE = "VOICE"
    HOSTEL_AI_AGENT = "HOSTEL_AI_AGENT"

class ConversationStatus(str, enum.Enum):
    AI_ACTIVE = "AI_ACTIVE"
    HUMAN_REQUESTED = "HUMAN_REQUESTED"
    HUMAN_ACTIVE = "HUMAN_ACTIVE"
    WAITING_FOR_CUSTOMER = "WAITING_FOR_CUSTOMER"
    RESOLVED = "RESOLVED"

class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now, onupdate=get_utc_now)

    properties = relationship("Property", back_populates="organization", cascade="all, delete-orphan")
    users = relationship("User", back_populates="organization", cascade="all, delete-orphan")
    agents = relationship("Agent", back_populates="organization", cascade="all, delete-orphan")
    subscriptions = relationship("Subscription", back_populates="organization", cascade="all, delete-orphan")

class Property(Base):
    __tablename__ = "properties"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    property_type: Mapped[str] = mapped_column(String(100), default="resort") # resort, hotel, hostel, homestay
    timezone: Mapped[str] = mapped_column(String(100), default="UTC")
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    contact_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)

    organization = relationship("Organization", back_populates="properties")
    agents = relationship("Agent", back_populates="property", cascade="all, delete-orphan")
    rooms = relationship("Room", back_populates="property", cascade="all, delete-orphan")
    facilities = relationship("Facility", back_populates="property", cascade="all, delete-orphan")
    restaurants = relationship("Restaurant", back_populates="property", cascade="all, delete-orphan")
    activities = relationship("Activity", back_populates="property", cascade="all, delete-orphan")
    live_updates = relationship("LiveUpdate", back_populates="property", cascade="all, delete-orphan")
    reservations = relationship("Reservation", back_populates="property", cascade="all, delete-orphan")

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(SQLEnum(UserRole), default=UserRole.ORGANIZATION_ADMIN)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)

    organization = relationship("Organization", back_populates="users")

class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_type: Mapped[AgentType] = mapped_column(SQLEnum(AgentType), default=AgentType.CONCIERGE)
    status: Mapped[AgentStatus] = mapped_column(SQLEnum(AgentStatus), default=AgentStatus.DRAFT)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    primary_language: Mapped[str] = mapped_column(String(50), default="English")
    supported_languages: Mapped[list] = mapped_column(JSON, default=lambda: ["English"])
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)

    organization = relationship("Organization", back_populates="agents")
    property = relationship("Property", back_populates="agents")
    config = relationship("AgentConfig", back_populates="agent", uselist=False, cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="agent", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="agent", cascade="all, delete-orphan")

class AgentConfig(Base):
    __tablename__ = "agent_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    agent_id: Mapped[str] = mapped_column(String(36), ForeignKey("agents.id", ondelete="CASCADE"), unique=True, nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), default="gpt-4o-mini")
    temperature: Mapped[float] = mapped_column(Float, default=0.2)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    greeting: Mapped[str] = mapped_column(Text, default="Hello! Welcome to our resort. How can I assist you today?")
    tone: Mapped[str] = mapped_column(String(100), default="Friendly, Professional, Courteous")
    guardrail_config: Mapped[dict] = mapped_column(JSON, default=dict)
    memory_config: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled_tools: Mapped[list] = mapped_column(JSON, default=list)
    enabled_channels: Mapped[list] = mapped_column(JSON, default=lambda: ["web_widget"])

    agent = relationship("Agent", back_populates="config")

class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[str] = mapped_column(String(50), default="pdf")
    source_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    content_raw: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)

    agent = relationship("Agent", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")

KnowledgeDocument = Document


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)

    document = relationship("Document", back_populates="chunks")

class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    room_number: Mapped[str] = mapped_column(String(50), nullable=False)
    room_type: Mapped[str] = mapped_column(String(100), nullable=False)
    price_per_night: Mapped[float] = mapped_column(Float, nullable=False)
    max_occupancy: Mapped[int] = mapped_column(Integer, default=2)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    property = relationship("Property", back_populates="rooms")

class Facility(Base):
    __tablename__ = "facilities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(100), default="Open")
    opening_time: Mapped[str] = mapped_column(String(50), default="06:00 AM")
    closing_time: Mapped[str] = mapped_column(String(50), default="10:00 PM")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    property = relationship("Property", back_populates="facilities")

class Restaurant(Base):
    __tablename__ = "restaurants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    cuisine: Mapped[str] = mapped_column(String(100), default="Multicuisine")
    status: Mapped[str] = mapped_column(String(100), default="Open")
    menu_json: Mapped[list] = mapped_column(JSON, default=list)
    operating_hours: Mapped[str] = mapped_column(String(255), default="07:00 AM - 11:00 PM")

    property = relationship("Property", back_populates="restaurants")

class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    time_slot: Mapped[str] = mapped_column(String(100), default="05:00 PM - 06:30 PM")
    price: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(50), default="Scheduled")

    property = relationship("Property", back_populates="activities")

class LiveUpdate(Base):
    __tablename__ = "live_updates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(50), default="ANNOUNCEMENT")
    priority: Mapped[str] = mapped_column(String(20), default="NORMAL")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)

    property = relationship("Property", back_populates="live_updates")

class IntegrationSource(Base):
    __tablename__ = "integration_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), default="REST_API")
    source_url: Mapped[str] = mapped_column(String(512), nullable=False)
    auth_type: Mapped[str] = mapped_column(String(50), default="API_KEY")
    credentials_masked: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="CONNECTED")
    field_mappings: Mapped[dict] = mapped_column(JSON, default=dict)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)

class DataAccessPolicy(Base):
    __tablename__ = "data_access_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_source_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("integration_sources.id", ondelete="CASCADE"), nullable=True, index=True)
    category_key: Mapped[str] = mapped_column(String(100), nullable=False)
    category_name: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    user_scope: Mapped[str] = mapped_column(String(50), default="nobody")
    field_permissions: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_by: Mapped[str] = mapped_column(String(255), default="Hostel Admin")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)


class Reservation(Base):
    __tablename__ = "reservations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    room_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True)
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_email: Mapped[str] = mapped_column(String(255), nullable=False)
    check_in: Mapped[str] = mapped_column(String(50), nullable=False)
    check_out: Mapped[str] = mapped_column(String(50), nullable=False)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="CONFIRMED")
    special_requests: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)

    property = relationship("Property", back_populates="reservations")

class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("idx_conversations_org_status", "organization_id", "status"),
        Index("idx_conversations_prop_agent", "property_id", "agent_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(50), default="web_widget")
    status: Mapped[ConversationStatus] = mapped_column(SQLEnum(ConversationStatus), default=ConversationStatus.AI_ACTIVE)
    customer_name: Mapped[str] = mapped_column(String(255), default="Guest")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)

    agent = relationship("Agent", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")

class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("idx_messages_conv_created", "conversation_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_type: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)

    conversation = relationship("Conversation", back_populates="messages")

class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id: Mapped[str] = mapped_column(String(36), ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    issue_summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="OPEN")
    priority: Mapped[str] = mapped_column(String(20), default="HIGH")
    assigned_to_user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)

class VoiceSession(Base):
    __tablename__ = "voice_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    property_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    provider: Mapped[str] = mapped_column(String(50), default="whisper_elevenlabs")
    status: Mapped[str] = mapped_column(String(50), default="COMPLETED")
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)

class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        Index("idx_usage_events_org_created", "organization_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    conversation_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), default="openai")
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit: Mapped[str] = mapped_column(String(20), default="tokens")
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)

class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_name: Mapped[str] = mapped_column(String(50), default="BUSINESS")
    status: Mapped[str] = mapped_column(String(50), default="ACTIVE")
    monthly_price: Mapped[float] = mapped_column(Float, default=499.0)
    max_agents: Mapped[int] = mapped_column(Integer, default=10)
    max_properties: Mapped[int] = mapped_column(Integer, default=5)
    max_conversations_per_month: Mapped[int] = mapped_column(Integer, default=50000)
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    subscription_status: Mapped[str] = mapped_column(String(50), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)

    organization = relationship("Organization", back_populates="subscriptions")

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    details_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)

class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    token: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=get_utc_now)

