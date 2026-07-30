"""
PREDICT — Pydantic Schemas (API request/response models)
"""
from datetime import datetime
from typing import List, Optional

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


class FleetOut(ORMBase):
    id: int
    vehicle_count: Optional[int] = None


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
    fleet_id: Optional[int] = None
    is_active: Optional[bool] = None


class VehicleOut(ORMBase):
    id: int
    health: AssetHealth
    last_seen: Optional[datetime] = None
    fleet_name: Optional[str] = None
    component_count: Optional[int] = None
    active_alert_count: Optional[int] = None
    open_work_order_count: Optional[int] = None


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


class ComponentOut(ORMBase):
    id: int
    vehicle_id: int
    sensor_count: Optional[int] = None


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


class SensorOut(ORMBase):
    id: int
    component_id: int


# =============================================================================
# Rule
# =============================================================================
class RuleBase(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    rule_type: RuleType
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


class RuleOut(ORMBase):
    id: int


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


class WorkOrderTemplateOut(ORMBase):
    id: int


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


class WorkOrderComplete(BaseModel):
    """Technician completion payload."""
    completed_by: str = Field(..., max_length=100)
    completion_notes: Optional[str] = None


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


class UserOut(ORMBase):
    id: int


# =============================================================================
# Generic
# =============================================================================
class MessageOut(BaseModel):
    message: str
    detail: Optional[str] = None


class PaginatedOut(BaseModel):
    items: List
    total: int
    skip: int
    limit: int