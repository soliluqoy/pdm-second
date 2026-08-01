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
    Date,
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
from sqlalchemy.dialects.postgresql import JSONB
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
    SCHEDULED = "scheduled"   # mileage / engine hours interval (odometer, engine_hours)
    BEHAVIOR = "behavior"     # driving-event count thresholds (harsh brake, speeding, …)
    ANOMALY = "anomaly"       # statistical baseline deviation / domain PdM detectors


class DrivingEventType(str, enum.Enum):
    HARSH_ACCEL = "harsh_accel"
    HARSH_BRAKE = "harsh_brake"
    HARSH_CORNER = "harsh_corner"
    SPEEDING = "speeding"
    IDLING = "idling"
    HIGH_RPM = "high_rpm"


class DrivingEventSource(str, enum.Enum):
    DEVICE = "device"
    DERIVED = "derived"


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

    # Deleting a fleet detaches its vehicles (fleet_id SET NULL), never deletes them.
    vehicles = relationship("Vehicle", back_populates="fleet", passive_deletes=True)


class Vehicle(TimestampMixin, Base):
    """A physical asset / vehicle equipped with a telematics device."""
    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True, index=True)
    fleet_id = Column(Integer, ForeignKey("fleets.id", ondelete="SET NULL"), nullable=True, index=True)

    name = Column(String(100), nullable=False)          # e.g., "Truck-001"
    license_plate = Column(String(20), index=True)
    make = Column(String(50))
    model = Column(String(50))
    year = Column(Integer)
    vin = Column(String(50), index=True)                # Vehicle Identification Number
    imei = Column(String(20), unique=True, index=True)  # Teltonika device IMEI (MQTT topic key)
    device_type = Column(String(20), default="fmc001", nullable=False)  # "fmc001" (OBD-II) or "fmc150" (CAN)
    sim_phone = Column(String(32))  # SIM MSISDN for external SMS config (not used by the stack)

    # Health status (updated by rule engine / ingestion)
    health = Column(SAEnum(AssetHealth), default=AssetHealth.GREY, nullable=False, index=True)
    last_seen = Column(DateTime(timezone=True))         # last telemetry timestamp

    is_active = Column(Boolean, default=True, nullable=False)

    fleet = relationship("Fleet", back_populates="vehicles")
    # passive_deletes: let the database CASCADE handle child rows on hard delete
    # instead of the ORM loading and deleting them one by one.
    components = relationship("Component", back_populates="vehicle",
                              cascade="all, delete-orphan", passive_deletes=True)
    sensor_readings = relationship("SensorReading", back_populates="vehicle", passive_deletes=True)
    alerts = relationship("Alert", back_populates="vehicle", passive_deletes=True)
    work_orders = relationship("WorkOrder", back_populates="vehicle", passive_deletes=True)


class Component(TimestampMixin, Base):
    """A sub-system of a vehicle (e.g., 'Engine', 'Transmission', 'Brakes')."""
    __tablename__ = "components"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)

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
    component_id = Column(Integer, ForeignKey("components.id", ondelete="CASCADE"), nullable=False, index=True)

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

    # Target: fleet-wide by default; optionally scoped to a single vehicle
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=True, index=True)
    sensor_id = Column(Integer, ForeignKey("sensors.id", ondelete="SET NULL"), nullable=True, index=True)
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
    work_order_template_id = Column(Integer, ForeignKey("work_order_templates.id", ondelete="SET NULL"), nullable=True)

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
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    rule_id = Column(Integer, ForeignKey("rules.id", ondelete="SET NULL"), nullable=True)
    sensor_id = Column(Integer, ForeignKey("sensors.id", ondelete="SET NULL"), nullable=True)

    severity = Column(SAEnum(AlertSeverity), nullable=False, index=True)
    status = Column(SAEnum(AlertStatus), default=AlertStatus.ACTIVE, nullable=False, index=True)

    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)

    # The triggering value / data point
    trigger_value = Column(Float)
    trigger_timestamp = Column(DateTime(timezone=True), default=utcnow)

    # Link to generated work order (1:1 typically). use_alter breaks the
    # alerts <-> work_orders circular FK so create_all orders deterministically.
    work_order_id = Column(
        Integer,
        ForeignKey("work_orders.id", ondelete="SET NULL", use_alter=True,
                   name="fk_alerts_work_order_id"),
        nullable=True,
    )

    vehicle = relationship("Vehicle", back_populates="alerts")


class WorkOrder(TimestampMixin, Base):
    """A maintenance work order (auto-generated or manual)."""
    __tablename__ = "work_orders"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    alert_id = Column(Integer, ForeignKey("alerts.id", ondelete="SET NULL"), nullable=True)
    template_id = Column(Integer, ForeignKey("work_order_templates.id", ondelete="SET NULL"), nullable=True)

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
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id", ondelete="SET NULL"), nullable=True)

    event_type = Column(String(50), nullable=False)     # "repair", "inspection", "shadow_resolved"
    title = Column(String(200), nullable=False)
    description = Column(Text)
    performed_by = Column(String(100))
    component = Column(String(50))                      # e.g. engine, electrical — ML label
    event_date = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)


class VehicleHealthEvent(Base):
    """Immutable log of vehicle health transitions (for the vehicle timeline)."""
    __tablename__ = "vehicle_health_events"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    from_health = Column(SAEnum(AssetHealth), nullable=False)
    to_health = Column(SAEnum(AssetHealth), nullable=False)
    reason = Column(String(100))
    timestamp = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    __table_args__ = (
        Index("ix_vehicle_health_events_vehicle_time", "vehicle_id", "timestamp"),
    )


class DtcEvent(Base):
    """Diagnostic trouble codes received from a tracker (regardless of rule match)."""
    __tablename__ = "dtc_events"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    dtc_code = Column(String(20), nullable=False, index=True)
    description = Column(Text)
    severity = Column(String(20), default="warning")
    alert_id = Column(Integer, ForeignKey("alerts.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (
        Index("ix_dtc_events_vehicle_time", "vehicle_id", "timestamp"),
    )


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
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
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


# =============================================================================
# Driving behavior (Phase 5)
# =============================================================================

class Trip(Base):
    """A driving trip segmented by ignition (or movement/speed fallback)."""
    __tablename__ = "trips"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    start_ts = Column(DateTime(timezone=True), nullable=False, index=True)
    end_ts = Column(DateTime(timezone=True), nullable=True, index=True)
    start_odometer = Column(Float)
    end_odometer = Column(Float)
    distance_km = Column(Float)
    duration_seconds = Column(Integer)
    max_speed = Column(Float)
    avg_speed = Column(Float)
    fuel_start = Column(Float)
    fuel_end = Column(Float)
    idle_seconds = Column(Integer, default=0, nullable=False)
    is_open = Column(Boolean, default=True, nullable=False, index=True)

    __table_args__ = (
        Index("ix_trips_vehicle_start", "vehicle_id", "start_ts"),
    )


class DrivingEvent(Base):
    """Harsh driving / speeding / idle / high-RPM event (device or derived)."""
    __tablename__ = "driving_events"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    trip_id = Column(Integer, ForeignKey("trips.id", ondelete="SET NULL"), nullable=True, index=True)
    ts = Column(DateTime(timezone=True), nullable=False, index=True)
    event_type = Column(SAEnum(DrivingEventType), nullable=False, index=True)
    value = Column(Float)
    latitude = Column(Float)
    longitude = Column(Float)
    source = Column(SAEnum(DrivingEventSource), nullable=False, default=DrivingEventSource.DERIVED)

    __table_args__ = (
        Index("ix_driving_events_vehicle_ts", "vehicle_id", "ts"),
        Index("ix_driving_events_vehicle_type_ts", "vehicle_id", "event_type", "ts"),
    )


class DriverScore(Base):
    """Daily per-vehicle driving score (stands in for driver in single-tenant PoC)."""
    __tablename__ = "driver_scores"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    trips = Column(Integer, default=0, nullable=False)
    distance_km = Column(Float, default=0.0, nullable=False)
    events_per_100km = Column(JSONB, default=dict)
    idle_ratio = Column(Float, default=0.0, nullable=False)
    score = Column(Float, default=100.0, nullable=False)

    __table_args__ = (
        UniqueConstraint("date", "vehicle_id", name="uq_driver_scores_date_vehicle"),
    )


# =============================================================================
# Predictive maintenance foundation (Phase 6)
# =============================================================================

class SensorBaseline(Base):
    """Per-vehicle, per-sensor statistical baseline from 1h aggregates."""
    __tablename__ = "sensor_baselines"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    sensor_type = Column(String(50), nullable=False, index=True)
    window = Column(String(20), nullable=False, default="30d")  # e.g. 30d
    mean = Column(Float, nullable=False)
    std = Column(Float, nullable=False)
    p95 = Column(Float)
    sample_count = Column(Integer, default=0, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("vehicle_id", "sensor_type", "window",
                         name="uq_sensor_baselines_vehicle_sensor_window"),
    )


class ComponentRisk(Base):
    """Placeholder for offline ML component risk scores (schema only)."""
    __tablename__ = "component_risk"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True)
    component = Column(String(50), nullable=False, index=True)
    risk_score = Column(Float, nullable=False, default=0.0)
    model_version = Column(String(50))
    updated_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("vehicle_id", "component", name="uq_component_risk_vehicle_component"),
    )