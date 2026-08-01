"""
PREDICT — Pydantic Schemas (API request/response models)
"""
from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import (
    AlertSeverity,
    AlertStatus,
    AssetHealth,
    RuleType,
    WorkOrderPriority,
    WorkOrderStatus,
    UserRole,
)


# =============================================================================
# Base config
# =============================================================================
class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


# =============================================================================
# Fleet
# =============================================================================
class FleetBase(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    is_active: bool = True


class FleetCreate(FleetBase):
    pass


class FleetUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class FleetOut(FleetBase, ORMBase):
    id: int
    vehicle_count: Optional[int] = None
    created_at: datetime
    updated_at: datetime


# =============================================================================
# Vehicle
# =============================================================================
class VehicleBase(BaseModel):
    name: str = Field(..., max_length=100)
    license_plate: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    vin: Optional[str] = None
    imei: str = Field(..., max_length=20)
    device_type: Literal["fmc001", "fmc150"] = "fmc001"
    sim_phone: Optional[str] = Field(None, max_length=32)
    fleet_id: Optional[int] = None
    is_active: bool = True


class VehicleCreate(VehicleBase):
    pass


class VehicleUpdate(BaseModel):
    name: Optional[str] = None
    license_plate: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    vin: Optional[str] = None
    imei: Optional[str] = None
    device_type: Optional[Literal["fmc001", "fmc150"]] = None
    sim_phone: Optional[str] = Field(None, max_length=32)
    fleet_id: Optional[int] = None
    is_active: Optional[bool] = None


class VehicleOut(VehicleBase, ORMBase):
    id: int
    health: AssetHealth
    last_seen: Optional[datetime] = None
    fleet_name: Optional[str] = None
    component_count: Optional[int] = None
    active_alert_count: Optional[int] = None
    open_work_order_count: Optional[int] = None
    created_at: datetime
    updated_at: datetime


# =============================================================================
# Component
# =============================================================================
class ComponentBase(BaseModel):
    name: str = Field(..., max_length=100)
    component_type: Optional[str] = None
    description: Optional[str] = None


class ComponentCreate(ComponentBase):
    vehicle_id: int


class ComponentUpdate(BaseModel):
    name: Optional[str] = None
    component_type: Optional[str] = None
    description: Optional[str] = None


class ComponentOut(ComponentBase, ORMBase):
    id: int
    vehicle_id: int
    sensor_count: Optional[int] = None
    created_at: datetime
    updated_at: datetime


# =============================================================================
# Sensor
# =============================================================================
class SensorBase(BaseModel):
    name: str = Field(..., max_length=100)
    sensor_type: str = Field(..., max_length=50)
    unit: Optional[str] = None
    io_element_id: Optional[int] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    warning_threshold: Optional[float] = None
    critical_threshold: Optional[float] = None
    is_active: bool = True


class SensorCreate(SensorBase):
    component_id: int


class SensorUpdate(BaseModel):
    name: Optional[str] = None
    sensor_type: Optional[str] = None
    unit: Optional[str] = None
    io_element_id: Optional[int] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    warning_threshold: Optional[float] = None
    critical_threshold: Optional[float] = None
    is_active: Optional[bool] = None


class SensorOut(SensorBase, ORMBase):
    id: int
    component_id: int
    created_at: datetime
    updated_at: datetime


# =============================================================================
# Rule
# =============================================================================
class RuleBase(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    rule_type: RuleType
    vehicle_id: Optional[int] = None    # None = fleet-wide
    sensor_id: Optional[int] = None
    sensor_type: Optional[str] = None
    operator: Optional[str] = None
    threshold_value: Optional[float] = None
    duration_seconds: int = 0
    dtc_code: Optional[str] = None
    interval_value: Optional[float] = None
    severity: AlertSeverity = AlertSeverity.WARNING
    work_order_template_id: Optional[int] = None
    is_active: bool = True


class RuleCreate(RuleBase):
    pass


class RuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    rule_type: Optional[RuleType] = None
    vehicle_id: Optional[int] = None
    sensor_id: Optional[int] = None
    sensor_type: Optional[str] = None
    operator: Optional[str] = None
    threshold_value: Optional[float] = None
    duration_seconds: Optional[int] = None
    dtc_code: Optional[str] = None
    interval_value: Optional[float] = None
    severity: Optional[AlertSeverity] = None
    work_order_template_id: Optional[int] = None
    is_active: Optional[bool] = None


class RuleOut(RuleBase, ORMBase):
    id: int
    dormant: Optional[bool] = None   # active but no provisioned sensor matches
    created_at: datetime
    updated_at: datetime


# =============================================================================
# Work Order Template
# =============================================================================
class WorkOrderTemplateBase(BaseModel):
    name: str = Field(..., max_length=100)
    description: str
    default_priority: WorkOrderPriority = WorkOrderPriority.MEDIUM
    estimated_duration_minutes: int = 60
    instructions: Optional[str] = None


class WorkOrderTemplateCreate(WorkOrderTemplateBase):
    pass


class WorkOrderTemplateOut(WorkOrderTemplateBase, ORMBase):
    id: int
    created_at: datetime
    updated_at: datetime


# =============================================================================
# Alert
# =============================================================================
class AlertOut(ORMBase):
    id: int
    vehicle_id: int
    rule_id: Optional[int] = None
    sensor_id: Optional[int] = None
    severity: AlertSeverity
    status: AlertStatus
    title: str
    message: str
    trigger_value: Optional[float] = None
    trigger_timestamp: Optional[datetime] = None
    work_order_id: Optional[int] = None
    vehicle_name: Optional[str] = None
    created_at: datetime


# =============================================================================
# Work Order
# =============================================================================
class WorkOrderBase(BaseModel):
    title: str = Field(..., max_length=200)
    description: str
    priority: WorkOrderPriority = WorkOrderPriority.MEDIUM
    instructions: Optional[str] = None
    vehicle_id: int


class WorkOrderCreate(WorkOrderBase):
    pass


class WorkOrderUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[WorkOrderPriority] = None
    instructions: Optional[str] = None
    status: Optional[WorkOrderStatus] = None
    assigned_to: Optional[str] = None


class WorkOrderOut(ORMBase):
    id: int
    vehicle_id: int
    alert_id: Optional[int] = None
    template_id: Optional[int] = None
    title: str
    description: str
    priority: WorkOrderPriority
    status: WorkOrderStatus
    instructions: Optional[str] = None
    assigned_to: Optional[str] = None
    assigned_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    completed_by: Optional[str] = None
    completion_notes: Optional[str] = None
    is_shadow: bool
    vehicle_name: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class WorkOrderComplete(BaseModel):
    """Technician completion payload."""
    completed_by: str = Field(..., max_length=100)
    completion_notes: Optional[str] = None
    component: Optional[str] = Field(
        None, max_length=50,
        description="Component type label for ML (engine, electrical, …)",
    )


class WorkOrderAssign(BaseModel):
    """Assign a work order to a technician."""
    assigned_to: str = Field(..., max_length=100)


# =============================================================================
# Sensor Reading (time-series)
# =============================================================================
class SensorReadingOut(ORMBase):
    id: int
    timestamp: datetime
    vehicle_id: int
    sensor_type: str
    sensor_name: Optional[str] = None
    value: float
    unit: Optional[str] = None
    quality: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    speed: Optional[float] = None
    ignition: Optional[bool] = None


# =============================================================================
# Dashboard
# =============================================================================
class DashboardSummary(BaseModel):
    total_vehicles: int
    green_count: int
    yellow_count: int
    red_count: int
    grey_count: int
    active_alerts: int
    critical_alerts: int
    open_work_orders: int
    shadow_work_orders: int
    in_progress_work_orders: int
    shadow_mode: bool


class VehicleHealthItem(BaseModel):
    id: int
    name: str
    imei: str
    health: AssetHealth
    last_seen: Optional[datetime] = None
    license_plate: Optional[str] = None
    active_alert_count: int = 0
    open_work_order_count: int = 0
    latest_readings: Optional[dict] = None


class TriggerRuleInfo(BaseModel):
    """An active threshold rule that can fire on a sensor (its trigger point)."""
    id: int
    name: str
    operator: Optional[str] = None
    threshold_value: Optional[float] = None
    duration_seconds: int = 0
    severity: AlertSeverity = AlertSeverity.WARNING


class LiveSensorItem(BaseModel):
    """A sensor definition merged with its latest live reading and thresholds."""
    sensor_type: str
    name: str
    unit: Optional[str] = None
    value: Optional[float] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    warning_threshold: Optional[float] = None
    critical_threshold: Optional[float] = None
    direction: str = "high"      # "high" = high-is-bad, "low" = low-is-bad
    status: str = "offline"      # ok | warning | critical | offline
    rules: List[TriggerRuleInfo] = []


class VehicleLiveItem(BaseModel):
    """A vehicle with its full live sensor telemetry for the dashboard."""
    id: int
    name: str
    imei: str
    license_plate: Optional[str] = None
    health: AssetHealth
    last_seen: Optional[datetime] = None
    ignition: Optional[bool] = None
    speed: Optional[float] = None
    telemetry_timestamp: Optional[str] = None
    active_alert_count: int = 0
    open_work_order_count: int = 0
    sensors: List[LiveSensorItem] = []


class TelemetryCatalogSensorItem(BaseModel):
    sensor_type: str
    name: str
    unit: str = ""
    component: str
    io_element_id: Optional[int] = None
    source: Literal["standard", "obd", "can"] = "standard"


class TelemetryCatalogFieldItem(BaseModel):
    field: str
    name: str
    unit: str = ""
    io_element_id: Optional[int] = None
    note: Optional[str] = None


class DeviceTelemetryCatalog(BaseModel):
    device_type: str
    label: str
    description: str
    sensors: List[TelemetryCatalogSensorItem]
    meta: List[TelemetryCatalogFieldItem]
    gps: List[TelemetryCatalogFieldItem]


class TelemetryCatalogOut(BaseModel):
    models: List[DeviceTelemetryCatalog]
    note: str


# =============================================================================
# History (time-bucketed sensor series + merged event timeline)
# =============================================================================
class HistoryPoint(BaseModel):
    """One point of a sensor series. Raw points have min == max == value."""
    t: datetime
    value: float
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    count: int = 1


class SensorHistoryOut(BaseModel):
    sensor_type: str
    resolution: Literal["raw", "1m", "1h"]
    points: List[HistoryPoint]


class TimelineEvent(BaseModel):
    """Merged vehicle event stream item."""
    kind: Literal["alert", "work_order", "maintenance", "health", "dtc", "driving"]
    id: int
    timestamp: datetime
    title: str
    description: Optional[str] = None
    severity: Optional[str] = None     # alerts / dtc
    status: Optional[str] = None       # alerts + work orders + health to_health
    work_order_id: Optional[int] = None
    alert_id: Optional[int] = None


# =============================================================================
# Driving behavior
# =============================================================================
class BehaviorScorecard(BaseModel):
    vehicle_id: int
    vehicle_name: str
    license_plate: Optional[str] = None
    score: Optional[float] = None
    date: Optional[date] = None
    trips: int = 0
    distance_km: float = 0.0
    idle_ratio: float = 0.0
    events_per_100km: dict = {}


class BehaviorScorePoint(BaseModel):
    date: date
    score: float
    trips: int
    distance_km: float
    idle_ratio: float
    events_per_100km: dict = {}


class BehaviorVehicleOut(BaseModel):
    vehicle_id: int
    vehicle_name: str
    scores: List[BehaviorScorePoint]
    event_breakdown: dict  # event_type → count (window)


class DrivingEventOut(ORMBase):
    id: int
    vehicle_id: int
    trip_id: Optional[int] = None
    ts: datetime
    event_type: str
    value: Optional[float] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    source: str


class TripOut(ORMBase):
    id: int
    vehicle_id: int
    start_ts: datetime
    end_ts: Optional[datetime] = None
    start_odometer: Optional[float] = None
    end_odometer: Optional[float] = None
    distance_km: Optional[float] = None
    duration_seconds: Optional[int] = None
    max_speed: Optional[float] = None
    avg_speed: Optional[float] = None
    fuel_start: Optional[float] = None
    fuel_end: Optional[float] = None
    idle_seconds: int = 0
    is_open: bool = False


class TripDetailOut(TripOut):
    events: List[DrivingEventOut] = []


# =============================================================================
# Maintenance History
# =============================================================================
class MaintenanceHistoryOut(ORMBase):
    id: int
    vehicle_id: int
    work_order_id: Optional[int] = None
    event_type: str
    title: str
    description: Optional[str] = None
    performed_by: Optional[str] = None
    component: Optional[str] = None
    event_date: datetime


# =============================================================================
# System Config
# =============================================================================
class SystemConfigOut(ORMBase):
    id: int
    key: str
    value: str
    description: Optional[str] = None


class SystemConfigUpdate(BaseModel):
    value: str


# =============================================================================
# User
# =============================================================================
class UserBase(BaseModel):
    username: str = Field(..., max_length=50)
    display_name: str = Field(..., max_length=100)
    role: UserRole = UserRole.TECHNICIAN
    is_active: bool = True


class UserCreate(UserBase):
    pass


class UserOut(UserBase, ORMBase):
    id: int


# =============================================================================
# Generic
# =============================================================================
class MessageOut(BaseModel):
    message: str
    detail: Optional[str] = None
