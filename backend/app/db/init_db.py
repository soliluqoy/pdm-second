"""
PREDICT — Database Initialization & Seed Data
Creates all tables, enables TimescaleDB, converts sensor_readings to hypertable,
migrates legacy naive timestamp columns to timestamptz, and seeds OPERATIONAL
data only (users, work-order templates, rules, system config).

No demo fleet/vehicles are seeded — real vehicles are registered via
POST /api/v1/assets/vehicles/register and provisioned from
app/services/provisioning.py (SENSOR_CATALOG with real Teltonika AVL IDs).
"""
import asyncio
import logging

from sqlalchemy import text

from app.db.database import Base, engine, async_session_factory
from app.db.models import (
    AlertSeverity,
    Rule,
    RuleType,
    SystemConfig,
    User,
    UserRole,
    WorkOrderPriority,
    WorkOrderTemplate,
)

logger = logging.getLogger("predict.init")


# Work order templates
SEED_TEMPLATES = [
    {"name": "Engine Overheat Inspection", "description": "Investigate engine coolant temperature exceeding critical threshold. Check coolant level, thermostat, water pump, and radiator.",
     "default_priority": WorkOrderPriority.URGENT, "estimated_duration_minutes": 90,
     "instructions": "1. Allow engine to cool\n2. Check coolant level and condition\n3. Inspect thermostat operation\n4. Check water pump and radiator for leaks\n5. Test cooling fan operation"},
    {"name": "High RPM Investigation", "description": "Engine RPM exceeding safe operating range. Inspect throttle position sensor, idle control, and transmission load.",
     "default_priority": WorkOrderPriority.HIGH, "estimated_duration_minutes": 60,
     "instructions": "1. Check throttle position sensor\n2. Inspect idle air control valve\n3. Review transmission load data\n4. Check for vacuum leaks"},
    {"name": "Low Fuel Alert", "description": "Fuel level below warning threshold. Schedule refueling or check for fuel system leaks.",
     "default_priority": WorkOrderPriority.LOW, "estimated_duration_minutes": 15,
     "instructions": "1. Verify fuel level with dipstick\n2. Check for fuel leaks\n3. Schedule refueling"},
    {"name": "DTC Diagnostic", "description": "Diagnostic Trouble Code detected. Connect OBD-II scanner, retrieve code, and perform manufacturer-recommended diagnostic procedure.",
     "default_priority": WorkOrderPriority.HIGH, "estimated_duration_minutes": 60,
     "instructions": "1. Connect OBD-II scanner\n2. Retrieve and document all DTCs\n3. Follow manufacturer diagnostic chart\n4. Repair or replace faulty component\n5. Clear codes and verify repair"},
    {"name": "Low Battery Voltage", "description": "Battery voltage below safe threshold. Test battery, alternator, and charging system.",
     "default_priority": WorkOrderPriority.HIGH, "estimated_duration_minutes": 45,
     "instructions": "1. Test battery voltage and load\n2. Check alternator output\n3. Inspect battery terminals and cables\n4. Replace battery if needed"},
    {"name": "Tire Pressure Check", "description": "Tire pressure outside normal range. Inspect and adjust tire pressure, check for punctures.",
     "default_priority": WorkOrderPriority.MEDIUM, "estimated_duration_minutes": 30,
     "instructions": "1. Check all tire pressures\n2. Inflate to manufacturer spec\n3. Inspect for punctures or damage\n4. Check valve stems"},
    {"name": "Scheduled Maintenance", "description": "Vehicle is approaching (or past) its manufacturer service interval. Book a service appointment and perform the scheduled inspection.",
     "default_priority": WorkOrderPriority.MEDIUM, "estimated_duration_minutes": 120,
     "instructions": "1. Review service countdown and odometer\n2. Book service appointment\n3. Perform manufacturer scheduled maintenance items\n4. Reset service interval on the vehicle"},
]

# Rules (threshold + DTC). Templates are referenced by NAME ("work_order_template")
# and resolved to real IDs at seed time — hardcoding numeric IDs breaks whenever
# the templates' identity sequence has advanced (sequences survive rollbacks).
SEED_RULES = [
    # Threshold rules
    {"name": "Critical Coolant Temperature", "description": "Coolant temp > 110°C",
     "rule_type": RuleType.THRESHOLD, "sensor_type": "coolant_temperature",
     "operator": ">", "threshold_value": 110, "duration_seconds": 300,
     "severity": AlertSeverity.CRITICAL, "work_order_template": "Engine Overheat Inspection"},
    {"name": "Warning Coolant Temperature", "description": "Coolant temp > 100°C",
     "rule_type": RuleType.THRESHOLD, "sensor_type": "coolant_temperature",
     "operator": ">", "threshold_value": 100, "duration_seconds": 300,
     "severity": AlertSeverity.WARNING, "work_order_template": "Engine Overheat Inspection"},
    {"name": "Critical Engine RPM", "description": "Engine RPM > 5500",
     "rule_type": RuleType.THRESHOLD, "sensor_type": "engine_rpm",
     "operator": ">", "threshold_value": 5500, "duration_seconds": 60,
     "severity": AlertSeverity.CRITICAL, "work_order_template": "High RPM Investigation"},
    {"name": "Low Fuel Warning", "description": "Fuel level < 20%",
     "rule_type": RuleType.THRESHOLD, "sensor_type": "fuel_level",
     "operator": "<", "threshold_value": 20, "duration_seconds": 0,
     "severity": AlertSeverity.WARNING, "work_order_template": "Low Fuel Alert"},
    {"name": "Critical Fuel Level", "description": "Fuel level < 10%",
     "rule_type": RuleType.THRESHOLD, "sensor_type": "fuel_level",
     "operator": "<", "threshold_value": 10, "duration_seconds": 0,
     "severity": AlertSeverity.CRITICAL, "work_order_template": "Low Fuel Alert"},
    {"name": "Low Battery Voltage", "description": "Battery voltage < 11.5V",
     "rule_type": RuleType.THRESHOLD, "sensor_type": "battery_voltage",
     "operator": "<", "threshold_value": 11.5, "duration_seconds": 60,
     "severity": AlertSeverity.CRITICAL, "work_order_template": "Low Battery Voltage"},
    {"name": "High Engine Load", "description": "Engine load > 95%",
     "rule_type": RuleType.THRESHOLD, "sensor_type": "engine_load",
     "operator": ">", "threshold_value": 95, "duration_seconds": 300,
     "severity": AlertSeverity.WARNING, "work_order_template": "High RPM Investigation"},
    {"name": "Low Tire Pressure", "description": "Tire pressure < 200 kPa",
     "rule_type": RuleType.THRESHOLD, "sensor_type": "tire_pressure_fl",
     "operator": "<", "threshold_value": 200, "duration_seconds": 0,
     "severity": AlertSeverity.WARNING, "work_order_template": "Tire Pressure Check"},
    {"name": "Service Due Soon", "description": "Less than 1000 km to scheduled service",
     "rule_type": RuleType.THRESHOLD, "sensor_type": "distance_until_service",
     "operator": "<", "threshold_value": 1000, "duration_seconds": 0,
     "severity": AlertSeverity.WARNING, "work_order_template": "Scheduled Maintenance"},
    {"name": "Service Overdue", "description": "Less than 100 km to scheduled service",
     "rule_type": RuleType.THRESHOLD, "sensor_type": "distance_until_service",
     "operator": "<", "threshold_value": 100, "duration_seconds": 0,
     "severity": AlertSeverity.CRITICAL, "work_order_template": "Scheduled Maintenance"},
    {"name": "High Engine Oil Temperature", "description": "Engine oil temp > 125°C",
     "rule_type": RuleType.THRESHOLD, "sensor_type": "engine_oil_temperature",
     "operator": ">", "threshold_value": 125, "duration_seconds": 300,
     "severity": AlertSeverity.WARNING, "work_order_template": "Engine Overheat Inspection"},
    {"name": "Low Control Module Voltage", "description": "ECU supply voltage < 12V (charging system)",
     "rule_type": RuleType.THRESHOLD, "sensor_type": "control_module_voltage",
     "operator": "<", "threshold_value": 12, "duration_seconds": 300,
     "severity": AlertSeverity.WARNING, "work_order_template": "Low Battery Voltage"},
    # DTC rules
    {"name": "DTC P0128 - Thermostat", "description": "Engine coolant thermostat below regulating temperature",
     "rule_type": RuleType.DTC, "dtc_code": "P0128",
     "severity": AlertSeverity.WARNING, "work_order_template": "DTC Diagnostic"},
    {"name": "DTC P0300 - Misfire", "description": "Random/multiple cylinder misfire detected",
     "rule_type": RuleType.DTC, "dtc_code": "P0300",
     "severity": AlertSeverity.CRITICAL, "work_order_template": "DTC Diagnostic"},
    {"name": "DTC P0420 - Catalyst", "description": "Catalyst system efficiency below threshold",
     "rule_type": RuleType.DTC, "dtc_code": "P0420",
     "severity": AlertSeverity.WARNING, "work_order_template": "DTC Diagnostic"},
    {"name": "DTC P0171 - Lean", "description": "System too lean (Bank 1)",
     "rule_type": RuleType.DTC, "dtc_code": "P0171",
     "severity": AlertSeverity.WARNING, "work_order_template": "DTC Diagnostic"},
    {"name": "DTC P0500 - Speed Sensor", "description": "Vehicle Speed Sensor malfunction",
     "rule_type": RuleType.DTC, "dtc_code": "P0500",
     "severity": AlertSeverity.WARNING, "work_order_template": "DTC Diagnostic"},
    {"name": "DTC P0115 - Coolant Circuit", "description": "Engine Coolant Temperature Circuit malfunction",
     "rule_type": RuleType.DTC, "dtc_code": "P0115",
     "severity": AlertSeverity.CRITICAL, "work_order_template": "DTC Diagnostic"},
]

SEED_USERS = [
    {"username": "admin", "display_name": "System Admin", "role": UserRole.ADMIN},
    {"username": "manager", "display_name": "Fleet Manager", "role": UserRole.FLEET_MANAGER},
    {"username": "tech1", "display_name": "John Technician", "role": UserRole.TECHNICIAN},
    {"username": "tech2", "display_name": "Sarah Technician", "role": UserRole.TECHNICIAN},
]


# ── Migration: naive timestamp → timestamptz ──────────────────────────────────
# Legacy databases created with DateTime (naive) columns must be converted to
# timestamptz so asyncpg can bind timezone-aware datetimes. Existing values are
# interpreted as UTC (which is how utcnow() wrote them). Idempotent: on a fresh
# database every column is already timestamptz and the loop finds nothing.
MIGRATE_TO_TIMESTAMPTZ_SQL = """
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT c.table_name, c.column_name
        FROM information_schema.columns c
        JOIN information_schema.tables t
          ON t.table_schema = c.table_schema AND t.table_name = c.table_name
        WHERE c.table_schema = 'public'
          AND t.table_type = 'BASE TABLE'
          AND c.data_type = 'timestamp without time zone'
    LOOP
        BEGIN
            EXECUTE format(
                'ALTER TABLE %I ALTER COLUMN %I TYPE timestamptz '
                'USING %I AT TIME ZONE ''UTC''',
                r.table_name, r.column_name, r.column_name
            );
            RAISE NOTICE 'Converted %.% to timestamptz', r.table_name, r.column_name;
        EXCEPTION WHEN OTHERS THEN
            RAISE WARNING 'timestamptz migration skipped for %.%: %',
                r.table_name, r.column_name, SQLERRM;
        END;
    END LOOP;
END $$;
"""


async def _migrate_naive_timestamps():
    """Convert any legacy naive timestamp columns to timestamptz (best effort)."""
    async with engine.begin() as conn:
        await conn.execute(text(MIGRATE_TO_TIMESTAMPTZ_SQL))
    logger.info("Legacy timestamp migration (naive → timestamptz) applied.")


async def _migrate_device_type():
    """Add vehicles.device_type on databases created before dual-tracker support.

    create_all() never alters existing tables, so do it here. Idempotent;
    existing vehicles default to 'fmc001' (the original OBD profile).
    """
    async with engine.begin() as conn:
        await conn.execute(text(
            "ALTER TABLE vehicles "
            "ADD COLUMN IF NOT EXISTS device_type VARCHAR(20) NOT NULL DEFAULT 'fmc001'"
        ))
    logger.info("device_type migration applied (vehicles).")


async def init_database():
    """Create all tables and set up TimescaleDB hypertable."""
    # Import all models to register them with Base
    from app.db import models  # noqa: F401

    logger.info("Creating database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Enable TimescaleDB and convert sensor_readings to hypertable
    logger.info("Enabling TimescaleDB and creating hypertable...")
    async with engine.begin() as conn:
        # Enable extension
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;"))
        # Convert sensor_readings to hypertable (idempotent)
        try:
            await conn.execute(text(
                "SELECT create_hypertable('sensor_readings', 'timestamp', "
                "if_not_exists => TRUE, migrate_data => TRUE);"
            ))
        except Exception as e:
            logger.warning("Hypertable creation (may already exist): %s", e)

    # Migrate any pre-existing naive timestamp columns to timestamptz
    await _migrate_naive_timestamps()

    # Add columns introduced after the first schema (existing DBs only)
    await _migrate_device_type()

    logger.info("Database tables created successfully.")


async def seed_database():
    """Seed OPERATIONAL data only: users, work-order templates, rules, config.

    No demo fleet/vehicles — real vehicles are registered via the API and
    provisioned from app/services/provisioning.py.
    """
    async with async_session_factory() as session:
        # Check if already seeded (users table is our idempotency marker)
        result = await session.execute(text("SELECT COUNT(*) FROM users"))
        if result.scalar() > 0:
            logger.info("Database already seeded, skipping.")
            return

        logger.info("Seeding operational data (users, templates, rules)...")

        # ── System Config ──────────────────────────────────────────────────────
        session.add(SystemConfig(
            key="shadow_mode", value="true",
            description="When true, generated work orders are created in shadow status for review.",
        ))

        # ── Users ──────────────────────────────────────────────────────────────
        for u in SEED_USERS:
            session.add(User(**u))

        # ── Work Order Templates ───────────────────────────────────────────────
        templates = []
        for t in SEED_TEMPLATES:
            tpl = WorkOrderTemplate(**t)
            session.add(tpl)
            templates.append(tpl)
        await session.flush()

        # ── Rules ──────────────────────────────────────────────────────────────
        # Resolve template names → actual IDs assigned by the database.
        template_ids = {tpl.name: tpl.id for tpl in templates}
        for rdata in SEED_RULES:
            rule_kwargs = dict(rdata)
            tpl_name = rule_kwargs.pop("work_order_template", None)
            if tpl_name is not None:
                rule_kwargs["work_order_template_id"] = template_ids.get(tpl_name)
            session.add(Rule(**rule_kwargs))

        await session.commit()
        logger.info("Database seeded: %d templates, %d rules, %d users "
                    "(no demo fleet — register real vehicles via API)",
                    len(SEED_TEMPLATES), len(SEED_RULES), len(SEED_USERS))



async def run_init():
    """Full initialization: create tables + seed data."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    await init_database()
    await seed_database()
    await engine.dispose()
    logger.info("Database initialization complete.")


if __name__ == "__main__":
    asyncio.run(run_init())