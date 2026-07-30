"""
PREDICT — SQLAlchemy ORM Models
Relational models + TimescaleDB time-series model for sensor readings.

Hierarchy: Fleet → Vehicle → Component → Sensor
Flow:       SensorReading → Rule evaluation → Alert → WorkOrder → MaintenanceHistory
"""
import enum
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
    func,
)
from sqlalchemy.orm import relationship

from app.db.database import Base


# ── Helper: timezone-aware UTC now ────────────────────────────────────────────
def utcnow() -> datetime:
    """Return timezone-aware UTC datetime.

    All timestamp columns are ``DateTime(timezone=True)`` (timestamptz), so
    values must be offset-aware. asyncpg rejects aware datetimes bound to
    naive ``timestamp`` columns ("can't subtract offset-naive and offset-aware
    datetimes") and vice versa.
    """
    return datetime.now(timezone.utc)


# ── Enums ─────────────────────────────────────────────────────────────────────
class AssetHealth(str, enum.Enum):
    """Asset health status for dashboard."""
    GREEN = "green"       # Normal
    YELLOW = "yellow"     # Warning
    RED = "red"           # Critical
    GREY = "grey"         # Offline / unknown


class AlertSeverity(str, enum.Enum):
    """Alert priority levels."""
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class AlertStatus(str, enum.Enum):
    """Alert lifecycle status."""
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"


class WorkOrderStatus(str, enum.Enum):
    """Work order lifecycle status."""
    SHADOW = "shadow"           # Generated in shadow mode (review only)
    OPEN = "open"               # Ready for assignment
    IN_PROGRESS = "in_progress" # Technician working
    COMPLETED = "completed"     # Work done, pending close
    CLOSED = "closed"           # Fully closed, written to history
    CANCELLED = "cancelled"     # Discarded (e.g., false positive)


class WorkOrderPriority(str, enum.Enum):
    """Work order priority."""
    URGENT = "urgent"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RuleType(str, enum.Enum):
    """Rule engine evaluation type."""
    THRESHOLD = "threshold"   # value > X or value < Y
    DTC = "dtc"               # diagnostic trouble code match
    SCHEDULED = "scheduled"   # mileage / engine hours interval


class UserRole(str, enum.Enum):
    """User roles."""
    ADMIN = "admin"
    FLEET_MANAGER = "fleet_manager"
    TECHNICIAN = "technician"


# ── Mixin: Timestamps ─────────────────────────────────────────────────────────
class TimestampMixin:
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        nullable=False,
    )


# =============================================================================
# Asset Hierarchy
# =============================================================================

class Fleet(TimestampMixin, Base):
    """Top-level grouping (e.g., 'Delivery Fleet', 'Service Fleet')."""
    __tablename__ = "fleets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True, nullable=False)

    vehicles = relationship("Vehicle", back_populates="fleet", cascade="all, delete-orphan")


class Vehicle(TimestampMixin, Base):
    """A physical asset / vehicle equipped with a telematics device."""
    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True, index=True)
    fleet_id = Column(Integer, ForeignKey("fleets.id"), nullable=True, index=True)

    name = Column(String(100), nullable=False)          # e.g., "Truck-001"
    license_plate = Column(String(20), index=True)
    make = Column(String(50))
    model = Column(String(50))
    year = Column(Integer)
    vin = Column(String(50), index=True)                # Vehicle Identification Number
    imei = Column(String(20), unique=True, index=True)  # FMC150 IMEI (MQTT topic key)

    # Health status (updated by rule engine / ingestion)
    health = Column(SAEnum(AssetHealth), default=AssetHealth.GREY, nullable=False, index=True)
    last_seen = Column(DateTime(timezone=True))         # last telemetry timestamp

    is_active = Column(Boolean, default=True, nullable=False)

    fleet = relationship("Fleet", back_populates="vehicles")
    components = relationship("Component", back_populates="vehicle", cascade="all, delete-orphan")
    sensor_readings = relationship("SensorReading", back_populates="vehicle")
    alerts = relationship("Alert", back_populates="vehicle")
    work_orders = relationship("WorkOrder", back_populates="vehicle")


class Component(TimestampMixin, Base):
    """A sub-system of a vehicle (e.g., 'Engine', 'Transmission', 'Brakes')."""
    __tablename__ = "components"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=False, index=True)

    name = Column(String(100), nullable=False)          # e.g., "Engine"
    component_type = Column(String(50))                 # e.g., "engine", "brake", "tire"
    description = Column(Text)

    vehicle = relationship("Vehicle", back_populates="components")
    sensors = relationship("Sensor", back_populates="component", cascade="all, delete-orphan")


class Sensor(TimestampMixin, Base):
    """A logical sensor / data point mapped to a component.
    Maps FMC150 IO element IDs to readable sensor names."""
    __tablename__ = "sensors"

    id = Column(Integer, primary_key=True, index=True)
    component_id = Column(Integer, ForeignKey("components.id"), nullable=False, index=True)

    name = Column(String(100), nullable=False)          # e.g., "Coolant Temperature"
    sensor_type = Column(String(50), nullable=False)    # e.g., "temperature", "rpm", "pressure"
    unit = Column(String(20))                           # e.g., "°C", "RPM", "km/h"

    # FMC150 IO element ID mapping (for real hardware integration)
    io_element_id = Column(Integer, index=True)         # Teltonika IO ID

    # Operating limits (used by default rules)
    min_value = Column(Float)
    max_value = Column(Float)
    warning_threshold = Column(Float)                   # 80% of limit
    critical_threshold = Column(Float)                  # 90% of limit

    is_active = Column(Boolean, default=True, nullable=False)

    component = relationship("Component", back_populates="sensors")


# =============================================================================
# Rule Engine
# =============================================================================

class Rule(TimestampMixin, Base):
    """A deterministic rule: if condition met, generate alert + work order."""
    __tablename__ = "rules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)

    rule_type = Column(SAEnum(RuleType), nullable=False, index=True)

    # Target: can be sensor-specific or asset-type-wide
    sensor_id = Column(Integer, ForeignKey("sensors.id"), nullable=True, index=True)
    sensor_type = Column(String(50), nullable=True)     # e.g., apply to all "temperature" sensors

    # Threshold rule params
    operator = Column(String(10))                       # ">", "<", ">=", "<=", "=="
    threshold_value = Column(Float)
    duration_seconds = Column(Integer, default=0)       # sustained for N seconds before trigger

    # DTC rule params
    dtc_code = Column(String(20))                       # e.g., "P0128"

    # Scheduled rule params
    interval_value = Column(Float)                       # e.g., 5000 (miles/hours)

    # Output
    severity = Column(SAEnum(AlertSeverity), nullable=False, default=AlertSeverity.WARNING)
    work_order_template_id = Column(Integer, ForeignKey("work_order_templates.id"), nullable=True)

    is_active = Column(Boolean, default=True, nullable=False, index=True)

    work_order_template = relationship("WorkOrderTemplate", back_populates="rules")


class WorkOrderTemplate(TimestampMixin, Base):
    """Template for auto-generating work orders from alerts."""
    __tablename__ = "work_order_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)          # pre-filled work order description
    default_priority = Column(SAEnum(WorkOrderPriority), default=WorkOrderPriority.MEDIUM, nullable=False)
    estimated_duration_minutes = Column(Integer, default=60)
    instructions = Column(Text)                         # technician instructions

    rules = relationship("Rule", back_populates="work_order_template")


# =============================================================================
# Alerts & Work Orders
# =============================================================================

class Alert(TimestampMixin, Base):
    """An alert generated by the rule engine."""
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=False, index=True)
    rule_id = Column(Integer, ForeignKey("rules.id"), nullable=True)
    sensor_id = Column(Integer, ForeignKey("sensors.id"), nullable=True)

    severity = Column(SAEnum(AlertSeverity), nullable=False, index=True)
    status = Column(SAEnum(AlertStatus), default=AlertStatus.ACTIVE, nullable=False, index=True)

    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)

    # The triggering value / data point
    trigger_value = Column(Float)
    trigger_timestamp = Column(DateTime(timezone=True), default=utcnow)

    # Link to generated work order (1:1 typically)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True)

    vehicle = relationship("Vehicle", back_populates="alerts")


class WorkOrder(TimestampMixin, Base):
    """A maintenance work order (auto-generated or manual)."""
    __tablename__ = "work_orders"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=False, index=True)
    alert_id = Column(Integer, ForeignKey("alerts.id"), nullable=True)
    template_id = Column(Integer, ForeignKey("work_order_templates.id"), nullable=True)

    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    priority = Column(SAEnum(WorkOrderPriority), default=WorkOrderPriority.MEDIUM, nullable=False, index=True)
    status = Column(SAEnum(WorkOrderStatus), default=WorkOrderStatus.OPEN, nullable=False, index=True)

    instructions = Column(Text)

    # Assignment
    assigned_to = Column(String(100))                   # technician name (simple)
    assigned_at = Column(DateTime(timezone=True))

    # Completion
    completed_at = Column(DateTime(timezone=True))
    completed_by = Column(String(100))
    completion_notes = Column(Text)

    # Whether this was generated in shadow mode
    is_shadow = Column(Boolean, default=False, nullable=False, index=True)

    vehicle = relationship("Vehicle", back_populates="work_orders")
    alert = relationship("Alert", foreign_keys=[alert_id])


# =============================================================================
# Maintenance History
# =============================================================================

class MaintenanceHistory(Base):
    """Immutable log of completed maintenance events per vehicle."""
    __tablename__ = "maintenance_history"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=False, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True)

    event_type = Column(String(50), nullable=False)     # "repair", "inspection", "shadow_resolved"
    title = Column(String(200), nullable=False)
    description = Column(Text)
    performed_by = Column(String(100))
    event_date = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)


# =============================================================================
# Users (simplified — no auth in PoC)
# =============================================================================

class User(TimestampMixin, Base):
    """System user (admin, fleet manager, technician)."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    display_name = Column(String(100), nullable=False)
    role = Column(SAEnum(UserRole), default=UserRole.TECHNICIAN, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)


# =============================================================================
# System Config
# =============================================================================

class SystemConfig(TimestampMixin, Base):
    """Key-value system configuration (e.g., shadow_mode toggle)."""
    __tablename__ = "system_config"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False)
    description = Column(Text)


# =============================================================================
# Time-Series: Sensor Readings (TimescaleDB hypertable)
# =============================================================================

class SensorReading(Base):
    """Time-series sensor data. Converted to TimescaleDB hypertable via migration.
    Each row = one reading from one sensor at one point in time.

    Note: TimescaleDB requires the partitioning column (timestamp) to be part
    of the primary key. We use a composite PK of (timestamp, id).
    """
    __tablename__ = "sensor_readings"

    # Composite PK: timestamp (for TimescaleDB partitioning) + serial id
    timestamp = Column(DateTime(timezone=True), default=utcnow, nullable=False, primary_key=True, index=True)
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=False, index=True)
    imei = Column(String(20), index=True)               # denormalized for fast lookup

    sensor_type = Column(String(50), nullable=False, index=True)  # "rpm", "temperature", etc.
    sensor_name = Column(String(100))                   # human-readable
    value = Column(Float, nullable=False)
    unit = Column(String(20))
    quality = Column(String(20), default="good")        # "good", "suspect", "bad"

    # GPS data (denormalized for map / location queries)
    latitude = Column(Float)
    longitude = Column(Float)
    speed = Column(Float)                                # km/h
    ignition = Column(Boolean)

    vehicle = relationship("Vehicle", back_populates="sensor_readings")

    __table_args__ = (
        Index("ix_sensor_readings_time_vehicle", "timestamp", "vehicle_id"),
        Index("ix_sensor_readings_vehicle_sensor_time", "vehicle_id", "sensor_type", "timestamp"),
    )