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
    # NOTE: no tire-pressure rule — neither FMC001 nor FMC150 provisions a
    # tire-pressure sensor (see provisioning.py). Add the sensor + rule together
    # if dedicated TPMS hardware is installed.
    {"name": "Low Vehicle Battery (CAN)", "description": "CAN-reported vehicle battery < 11.5V (FMC150)",
     "rule_type": RuleType.THRESHOLD, "sensor_type": "vehicle_battery_voltage",
     "operator": "<", "threshold_value": 11.5, "duration_seconds": 60,
     "severity": AlertSeverity.CRITICAL, "work_order_template": "Low Battery Voltage"},
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
    # Scheduled maintenance (odometer interval)
    {"name": "Scheduled Service 10,000 km", "description": "Service due every 10,000 km of odometer travel",
     "rule_type": RuleType.SCHEDULED, "sensor_type": "odometer",
     "interval_value": 10000,
     "severity": AlertSeverity.WARNING, "work_order_template": "Scheduled Maintenance"},
    # Behavior: more than 5 harsh-brake events in a day
    {"name": "Excessive Harsh Braking", "description": "More than 5 harsh-brake events in a calendar day",
     "rule_type": RuleType.BEHAVIOR, "sensor_type": "harsh_brake",
     "operator": ">=", "threshold_value": 5, "duration_seconds": 86400,
     "severity": AlertSeverity.WARNING, "work_order_template": "High RPM Investigation"},
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


async def _migrate_sim_phone():
    """Add vehicles.sim_phone for external SMS config notes."""
    async with engine.begin() as conn:
        await conn.execute(text(
            "ALTER TABLE vehicles "
            "ADD COLUMN IF NOT EXISTS sim_phone VARCHAR(32)"
        ))
    logger.info("sim_phone migration applied (vehicles).")


async def _migrate_rule_vehicle_id():
    """Add rules.vehicle_id for optional per-vehicle rule scoping."""
    async with engine.begin() as conn:
        await conn.execute(text(
            "ALTER TABLE rules "
            "ADD COLUMN IF NOT EXISTS vehicle_id INTEGER REFERENCES vehicles(id) ON DELETE CASCADE"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_rules_vehicle_id ON rules (vehicle_id)"
        ))
    logger.info("rule vehicle_id migration applied (rules).")


async def _migrate_maintenance_component():
    """Add maintenance_history.component for ML labels."""
    async with engine.begin() as conn:
        await conn.execute(text(
            "ALTER TABLE maintenance_history "
            "ADD COLUMN IF NOT EXISTS component VARCHAR(50)"
        ))
    logger.info("maintenance_history.component migration applied.")


async def _migrate_rule_type_enum():
    """Add new RuleType enum values on existing DBs.

    Historical SAEnum columns store the *member name* (THRESHOLD, DTC,
    SCHEDULED), not the lowercase Python value — keep that convention.
    """
    async with engine.begin() as conn:
        for value in ("BEHAVIOR", "ANOMALY"):
            try:
                await conn.execute(text(
                    f"ALTER TYPE ruletype ADD VALUE IF NOT EXISTS '{value}'"
                ))
            except Exception as e:
                logger.debug("ruletype enum add %s: %s", value, e)
    logger.info("ruletype enum migration applied (BEHAVIOR, ANOMALY).")


# FK delete behavior. create_all() never alters existing constraints, so
# re-create them with the correct ON DELETE action on legacy databases.
# (table, column, referenced_table, on_delete)
_FK_ONDELETE_SPEC = [
    ("vehicles", "fleet_id", "fleets", "SET NULL"),
    ("components", "vehicle_id", "vehicles", "CASCADE"),
    ("sensors", "component_id", "components", "CASCADE"),
    ("sensor_readings", "vehicle_id", "vehicles", "CASCADE"),
    ("alerts", "vehicle_id", "vehicles", "CASCADE"),
    ("alerts", "rule_id", "rules", "SET NULL"),
    ("alerts", "sensor_id", "sensors", "SET NULL"),
    ("alerts", "work_order_id", "work_orders", "SET NULL"),
    ("work_orders", "vehicle_id", "vehicles", "CASCADE"),
    ("work_orders", "alert_id", "alerts", "SET NULL"),
    ("work_orders", "template_id", "work_order_templates", "SET NULL"),
    ("maintenance_history", "vehicle_id", "vehicles", "CASCADE"),
    ("maintenance_history", "work_order_id", "work_orders", "SET NULL"),
    ("rules", "sensor_id", "sensors", "SET NULL"),
    ("rules", "vehicle_id", "vehicles", "CASCADE"),
    ("rules", "work_order_template_id", "work_order_templates", "SET NULL"),
    ("trips", "vehicle_id", "vehicles", "CASCADE"),
    ("driving_events", "vehicle_id", "vehicles", "CASCADE"),
    ("driving_events", "trip_id", "trips", "SET NULL"),
    ("driver_scores", "vehicle_id", "vehicles", "CASCADE"),
    ("sensor_baselines", "vehicle_id", "vehicles", "CASCADE"),
    ("component_risk", "vehicle_id", "vehicles", "CASCADE"),
]


async def _migrate_fk_ondelete():
    """Ensure every FK has the intended ON DELETE action (idempotent).

    Without this, deleting a vehicle/rule/template with dependent rows raises
    an FK violation and surfaces as HTTP 500.
    """
    sql = """
    DO $$
    DECLARE
        spec RECORD;
        con RECORD;
    BEGIN
        FOR spec IN
            SELECT * FROM (VALUES {values}) AS t(tbl, col, ref_tbl, action)
        LOOP
            -- Find the existing FK on (tbl.col) whose delete rule differs
            FOR con IN
                SELECT c.conname
                FROM pg_constraint c
                JOIN pg_class r ON r.oid = c.conrelid
                JOIN pg_attribute a ON a.attrelid = c.conrelid
                     AND a.attnum = ANY (c.conkey)
                WHERE c.contype = 'f'
                  AND r.relname = spec.tbl
                  AND a.attname = spec.col
                  AND c.confdeltype <> (CASE spec.action
                        WHEN 'CASCADE' THEN 'c' WHEN 'SET NULL' THEN 'n' ELSE 'a' END)
            LOOP
                EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I', spec.tbl, con.conname);
                EXECUTE format(
                    'ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY (%I) REFERENCES %I (id) ON DELETE %s',
                    spec.tbl, con.conname, spec.col, spec.ref_tbl, spec.action);
                RAISE NOTICE 'FK %.% now ON DELETE %', spec.tbl, spec.col, spec.action;
            END LOOP;
        END LOOP;
    END $$;
    """
    values = ",\n".join(
        f"('{t}', '{c}', '{rt}', '{a}')" for t, c, rt, a in _FK_ONDELETE_SPEC
    )
    async with engine.begin() as conn:
        await conn.execute(text(sql.replace("{values}", values)))
    logger.info("FK ON DELETE migration applied.")


async def _ensure_system_config(session, key: str, value: str, description: str) -> None:
    existing = await session.execute(
        text("SELECT 1 FROM system_config WHERE key = :k LIMIT 1"), {"k": key}
    )
    if existing.scalar() is None:
        session.add(SystemConfig(key=key, value=value, description=description))


async def _migrate_seed_rules_fixup():
    """Data fix on existing databases: retire dormant seeded rules and add
    the FMC150 battery rule (fresh DBs get the corrected SEED_RULES)."""
    async with async_session_factory() as session:
        # The tire-pressure rule can never fire: no catalog/bridge source.
        await session.execute(text(
            "UPDATE rules SET is_active = false "
            "WHERE sensor_type = 'tire_pressure_fl' AND is_active = true"
        ))
        # FMC150 reports vehicle battery as vehicle_battery_voltage (AVL 168).
        existing = await session.execute(text(
            "SELECT 1 FROM rules WHERE sensor_type = 'vehicle_battery_voltage' LIMIT 1"
        ))
        if existing.scalar() is None:
            tpl = await session.execute(text(
                "SELECT id FROM work_order_templates WHERE name = 'Low Battery Voltage' LIMIT 1"
            ))
            tpl_id = tpl.scalar()
            await session.execute(text(
                "INSERT INTO rules (name, description, rule_type, sensor_type, operator, "
                " threshold_value, duration_seconds, severity, work_order_template_id, "
                " is_active, created_at, updated_at) "
                "VALUES ('Low Vehicle Battery (CAN)', "
                " 'CAN-reported vehicle battery < 11.5V (FMC150)', 'threshold', "
                " 'vehicle_battery_voltage', '<', 11.5, 60, 'critical', :tpl, true, now(), now())"
            ), {"tpl": tpl_id})

        # Phase 5/6 config keys + scheduled/behavior seed rules on upgraded DBs.
        await _ensure_system_config(
            session, "behavior.speed_limit_kmh", "120",
            "Fleet speeding threshold (km/h) for Tier-2 behavior detection.")
        await _ensure_system_config(
            session, "behavior.idle_minutes", "5",
            "Minutes of ignition-on + near-zero speed before an idling event.")
        await _ensure_system_config(
            session, "behavior.accel_threshold_ms2", "3.0",
            "|Δv/Δt| (m/s²) above which harsh accel/brake is flagged (derived).")
        await _ensure_system_config(
            session, "behavior.high_rpm_threshold", "4000",
            "RPM while moving above which high_rpm events are derived.")
        await _ensure_system_config(
            session, "behavior.score_weights",
            '{"harsh_accel":8,"harsh_brake":10,"harsh_corner":8,"speeding":6,"idling":3,"high_rpm":4}',
            "Penalty points per event per 100 km for the daily driving score.")

        sched = await session.execute(text(
            "SELECT 1 FROM rules WHERE name = 'Scheduled Service 10,000 km' LIMIT 1"
        ))
        if sched.scalar() is None:
            tpl = await session.execute(text(
                "SELECT id FROM work_order_templates WHERE name = 'Scheduled Maintenance' LIMIT 1"
            ))
            tpl_id = tpl.scalar()
            # ruletype enum stores member NAMES (SCHEDULED), not values.
            await session.execute(text(
                "INSERT INTO rules (name, description, rule_type, sensor_type, "
                " interval_value, severity, work_order_template_id, is_active, "
                " created_at, updated_at) "
                "VALUES ('Scheduled Service 10,000 km', "
                " 'Service due every 10,000 km of odometer travel', 'SCHEDULED', "
                " 'odometer', 10000, 'WARNING', :tpl, true, now(), now())"
            ), {"tpl": tpl_id})

        beh = await session.execute(text(
            "SELECT 1 FROM rules WHERE name = 'Excessive Harsh Braking' LIMIT 1"
        ))
        if beh.scalar() is None:
            tpl = await session.execute(text(
                "SELECT id FROM work_order_templates WHERE name = 'High RPM Investigation' LIMIT 1"
            ))
            tpl_id = tpl.scalar()
            await session.execute(text(
                "INSERT INTO rules (name, description, rule_type, sensor_type, operator, "
                " threshold_value, duration_seconds, severity, work_order_template_id, "
                " is_active, created_at, updated_at) "
                "VALUES ('Excessive Harsh Braking', "
                " 'More than 5 harsh-brake events in a calendar day', 'BEHAVIOR', "
                " 'harsh_brake', '>=', 5, 86400, 'WARNING', :tpl, true, now(), now())"
            ), {"tpl": tpl_id})

        await session.commit()
    logger.info("Seed-rule fixup applied (Phase 5/6 rules + behavior config ensured).")


# ── TimescaleDB lifecycle: compression, retention, continuous aggregates ──────
async def _setup_timescale_policies():
    """Compression + retention + 1m/1h continuous aggregates (all idempotent).

    Without these, sensor_readings grows unbounded and long-range history
    queries scan raw 10-second data.
    """
    from app.config import settings as cfg

    autocommit = await engine.connect()
    try:
        conn = await autocommit.execution_options(isolation_level="AUTOCOMMIT")

        # Compression (segment by vehicle + sensor for efficient per-sensor scans)
        try:
            await conn.execute(text(
                "ALTER TABLE sensor_readings SET ("
                "  timescaledb.compress,"
                "  timescaledb.compress_segmentby = 'vehicle_id, sensor_type',"
                "  timescaledb.compress_orderby = 'timestamp DESC'"
                ")"
            ))
            await conn.execute(text(
                "SELECT add_compression_policy('sensor_readings', INTERVAL '7 days', "
                "if_not_exists => TRUE)"
            ))
        except Exception as e:
            logger.warning("Compression setup skipped: %s", e)

        # Retention
        try:
            await conn.execute(text(
                f"SELECT add_retention_policy('sensor_readings', "
                f"INTERVAL '{int(cfg.READINGS_RETENTION_DAYS)} days', if_not_exists => TRUE)"
            ))
        except Exception as e:
            logger.warning("Retention setup skipped: %s", e)

        # Continuous aggregates (1 minute + 1 hour rollups)
        for view, bucket, start_off, end_off, sched in (
            ("sensor_readings_1m", "1 minute", "2 hours", "10 minutes", "10 minutes"),
            ("sensor_readings_1h", "1 hour", "2 days", "1 hour", "1 hour"),
        ):
            try:
                await conn.execute(text(
                    f"CREATE MATERIALIZED VIEW IF NOT EXISTS {view} "
                    f"WITH (timescaledb.continuous) AS "
                    f"SELECT time_bucket(INTERVAL '{bucket}', timestamp) AS bucket, "
                    f"       vehicle_id, sensor_type, "
                    f"       avg(value) AS avg_value, min(value) AS min_value, "
                    f"       max(value) AS max_value, count(*) AS sample_count "
                    f"FROM sensor_readings "
                    f"GROUP BY bucket, vehicle_id, sensor_type "
                    f"WITH NO DATA"
                ))
                await conn.execute(text(
                    f"SELECT add_continuous_aggregate_policy('{view}', "
                    f"start_offset => INTERVAL '{start_off}', "
                    f"end_offset => INTERVAL '{end_off}', "
                    f"schedule_interval => INTERVAL '{sched}', if_not_exists => TRUE)"
                ))
            except Exception as e:
                logger.warning("Continuous aggregate %s skipped: %s", view, e)

        logger.info("TimescaleDB policies applied (compression, retention, aggregates).")
    finally:
        await autocommit.close()


async def audit_dormant_rules():
    """Log active rules whose sensor_type matches no provisioned sensor.

    These rules can never fire — usually a typo or a sensor that is not in
    the provisioning catalog. Surfaced in logs and via GET /api/v1/rules.
    """
    async with async_session_factory() as session:
        result = await session.execute(text(
            "SELECT r.id, r.name, r.sensor_type FROM rules r "
            "WHERE r.is_active = true AND r.rule_type = 'THRESHOLD' "
            "  AND r.sensor_type IS NOT NULL "
            "  AND NOT EXISTS (SELECT 1 FROM sensors s WHERE s.sensor_type = r.sensor_type)"
        ))
        rows = result.all()
        for rid, name, stype in rows:
            logger.warning(
                "DORMANT RULE: id=%s %r targets sensor_type=%r which no "
                "registered vehicle provisions — it will never fire.",
                rid, name, stype,
            )
        return [row[0] for row in rows]


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
    await _migrate_sim_phone()
    await _migrate_rule_vehicle_id()
    await _migrate_maintenance_component()
    await _migrate_rule_type_enum()
    await _migrate_fk_ondelete()

    # Compression / retention / continuous aggregates
    await _setup_timescale_policies()

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
            logger.info("Database already seeded, skipping (applying rule fixups).")
            await _migrate_seed_rules_fixup()
            return

        logger.info("Seeding operational data (users, templates, rules)...")

        # ── System Config ──────────────────────────────────────────────────────
        session.add(SystemConfig(
            key="shadow_mode", value="true",
            description="When true, generated work orders are created in shadow status for review.",
        ))
        session.add(SystemConfig(
            key="behavior.speed_limit_kmh", value="120",
            description="Fleet speeding threshold (km/h) for Tier-2 behavior detection.",
        ))
        session.add(SystemConfig(
            key="behavior.idle_minutes", value="5",
            description="Minutes of ignition-on + near-zero speed before an idling event.",
        ))
        session.add(SystemConfig(
            key="behavior.accel_threshold_ms2", value="3.0",
            description="|Δv/Δt| (m/s²) above which harsh accel/brake is flagged (derived).",
        ))
        session.add(SystemConfig(
            key="behavior.high_rpm_threshold", value="4000",
            description="RPM while moving above which high_rpm events are derived.",
        ))
        session.add(SystemConfig(
            key="behavior.score_weights",
            value='{"harsh_accel":8,"harsh_brake":10,"harsh_corner":8,"speeding":6,"idling":3,"high_rpm":4}',
            description="Penalty points per event per 100 km for the daily driving score.",
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