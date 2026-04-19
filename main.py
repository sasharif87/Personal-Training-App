# main.py
"""
AI Coaching System — entry point.

Modes:
  python main.py                  Run the pipeline once right now
  python main.py --dry-run        Generate plan but skip device pushes
  python main.py --skip-sync      Skip Garmin sync (use existing InfluxDB data)
  python main.py --daemon         Run as a daemon with APScheduler (3 AM cron)
  python main.py --status         Print current CTL/ATL/TSB and HRV to stdout

Environment:
  PIPELINE_CRON   cron expression for daemon mode (default: "0 3 * * *")
  TZ              timezone for scheduler (default: Australia/Melbourne)

Usage in Docker:
  CMD ["python", "main.py", "--daemon"]
"""

import argparse
import logging
import os
import sys
from datetime import datetime

# ---------------------------------------------------------------------------
# Logging setup — console + file
# ---------------------------------------------------------------------------
log_dir = os.environ.get("LOG_DIR", "/data/logs")
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(log_dir, "pipeline.log")),
    ],
)
logger = logging.getLogger("main")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(description="AI Coaching System pipeline runner")
    parser.add_argument("--daemon",       action="store_true", help="Run as scheduled daemon (APScheduler)")
    parser.add_argument("--dry-run",      action="store_true", help="Generate plan only, skip device push")
    parser.add_argument("--skip-sync",    action="store_true", help="Skip Garmin Connect sync step")
    parser.add_argument("--status",       action="store_true", help="Print current fitness state and exit")
    parser.add_argument("--run-weekly",   action="store_true", help="Manually trigger the Weekly Review pipeline immediately")
    parser.add_argument("--run-monthly",  action="store_true", help="Manually trigger the Monthly Generation pipeline immediately")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Single run
# ---------------------------------------------------------------------------
def run_pipeline(dry_run: bool = False, skip_sync: bool = False) -> int:
    from backend.orchestration.daily_pipeline import DailyPipeline
    pipeline = DailyPipeline()
    try:
        result = pipeline.run(skip_sync=skip_sync, dry_run=dry_run)
        logger.info(
            "Pipeline succeeded — status=%s recommendation=%s",
            result.get("status", "ok"),
            result.get("recommendation", "n/a"),
        )
        return 0
    except Exception as exc:
        logger.error("Daily Pipeline failed: %s", exc, exc_info=True)
        return 1

def run_weekly_pipeline(dry_run: bool = False) -> int:
    from backend.orchestration.weekly_pipeline import WeeklyPipeline
    pipeline = WeeklyPipeline()
    try:
        plan = pipeline.run(dry_run=dry_run)
        logger.info("Weekly Pipeline succeeded — week %d revised", plan.week_number)
        return 0
    except Exception as exc:
        logger.error("Weekly Pipeline failed: %s", exc, exc_info=True)
        return 1

def run_monthly_pipeline(dry_run: bool = False) -> int:
    # Assuming standard pattern for MonthlyPipeline
    from backend.orchestration.monthly_pipeline import MonthlyPipeline
    pipeline = MonthlyPipeline()
    try:
        plan = pipeline.run(dry_run=dry_run)
        logger.info("Monthly Pipeline succeeded — Generated 4-week block.")
        return 0
    except Exception as exc:
        logger.error("Monthly Pipeline failed: %s", exc, exc_info=True)
        return 1


# ---------------------------------------------------------------------------
# Status check
# ---------------------------------------------------------------------------
def print_status() -> None:
    from backend.storage.influx_client import InfluxClient
    from backend.analysis.fitness_models import calculate_ctl_atl_tsb

    influx = InfluxClient()
    tss = influx.get_daily_tss(days=120)
    hrv = influx.get_hrv_trend(days=14)

    if tss.empty:
        print("No TSS data in InfluxDB — run a sync first.")
        return

    ctl, atl, tsb = calculate_ctl_atl_tsb(tss)
    print(f"\n{'='*40}")
    print(f"  Fitness Status — {datetime.now().strftime('%Y-%m-%d')}")
    print(f"{'='*40}")
    print(f"  CTL (Fitness)  : {ctl.iloc[-1]:.1f}")
    print(f"  ATL (Fatigue)  : {atl.iloc[-1]:.1f}")
    print(f"  TSB (Form)     : {tsb.iloc[-1]:.1f}")
    print(f"  HRV Trend      : {hrv}")
    print(f"{'='*40}\n")
    influx.close()


# ---------------------------------------------------------------------------
# Daemon mode — APScheduler
# ---------------------------------------------------------------------------
def run_daemon() -> None:
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logger.error("APScheduler not installed — add 'apscheduler' to requirements.txt")
        sys.exit(1)

    cron_daily = os.environ.get("CRON_DAILY", "0 3 * * *")
    cron_weekly = os.environ.get("CRON_WEEKLY", "0 2 * * 1")
    cron_monthly = os.environ.get("CRON_MONTHLY", "0 1 1 * *")
    tz = os.environ.get("TZ", "Australia/Melbourne")

    scheduler = BlockingScheduler(timezone=tz)

    def _write_heartbeat():
        """Touch /tmp/scheduler_heartbeat so Docker's healthcheck can verify the scheduler is alive."""
        import pathlib
        hb = pathlib.Path("/tmp/scheduler_heartbeat")
        hb.touch()

    # Heartbeat every 5 minutes — Docker healthcheck tests for mtime < 6 min
    from apscheduler.triggers.interval import IntervalTrigger
    scheduler.add_job(_write_heartbeat, IntervalTrigger(minutes=5), id="heartbeat")
    _write_heartbeat()  # Write immediately so the container passes its start_period check

    scheduler.add_job(
        run_monthly_pipeline,
        CronTrigger.from_crontab(cron_monthly, timezone=tz),
        id="monthly_pipeline",
        misfire_grace_time=3600
    )
    scheduler.add_job(
        run_weekly_pipeline,
        CronTrigger.from_crontab(cron_weekly, timezone=tz),
        id="weekly_pipeline",
        misfire_grace_time=3600
    )
    scheduler.add_job(
        run_pipeline,
        CronTrigger.from_crontab(cron_daily, timezone=tz),
        id="daily_pipeline",
        misfire_grace_time=3600
    )

    logger.info(f"Daemon started in {tz} timezone")
    logger.info(f"  Monthly Cron : '{cron_monthly}'")
    logger.info(f"  Weekly Cron  : '{cron_weekly}'")
    logger.info(f"  Daily Cron   : '{cron_daily}'")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Daemon shutting down")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    args = parse_args()

    if args.status:
        print_status()
        sys.exit(0)

    if args.daemon:
        run_daemon()
    elif args.run_monthly:
        exit_code = run_monthly_pipeline(dry_run=args.dry_run)
        sys.exit(exit_code)
    elif args.run_weekly:
        exit_code = run_weekly_pipeline(dry_run=args.dry_run)
        sys.exit(exit_code)
    else:
        # Default behavior is to trigger the daily routine manually
        exit_code = run_pipeline(dry_run=args.dry_run, skip_sync=args.skip_sync)
        sys.exit(exit_code)
