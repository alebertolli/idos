from idos.workers.scheduler.service import SchedulerService, ScheduledJob
from idos.workers.data.scout_worker import ScoutWorker
from idos.workers.data.refresh_worker import DataRefreshWorker
from idos.workers.data.digest_worker import DigestWorker
from idos.workers.data.git_queue_worker import GitQueueWorker
from idos.workers.ai.research_worker import ResearchWorker
from idos.workers.ai.decision_board_worker import DecisionBoardWorker
from idos.workers.portfolio.entry_monitor_worker import EntryMonitorWorker
from idos.workers.portfolio.rebalance_worker import RebalanceWorker, RiskMonitorWorker
from idos.workers.learning.post_mortem_worker import PostMortemWorker


def build_scheduler(base_path: str, config: dict | None = None) -> SchedulerService:
    """Builds the IDOS scheduler with all workers per IPOR rhythms.

    Rhythms per IPOR (SDD-9 §6):
    - Daily: RiskMonitorWorker, EntryMonitorWorker, GitQueueWorker
    - Weekly: ScoutWorker (discovery)
    - Monthly: RebalanceWorker, DataRefreshWorker (full refresh)
    - Quarterly: ResearchWorker (DDD/AOIF), PostMortemWorker
    - Weekly (Friday): DigestWorker
    """
    cfg = config or {}
    scheduler = SchedulerService()
    bp = base_path

    common_ctx = {"base_path": bp}

    # DAILY (pre-market ~08:00)
    scheduler.register(ScheduledJob(
        name="risk_monitor",
        worker=RiskMonitorWorker(cfg.get("risk")),
        interval_type="days",
        interval_value=1,
        at_time="08:00",
        context=common_ctx,
    ))

    scheduler.register(ScheduledJob(
        name="entry_monitor",
        worker=EntryMonitorWorker(cfg.get("entry")),
        interval_type="days",
        interval_value=1,
        at_time="09:30",
        context=common_ctx,
    ))

    scheduler.register(ScheduledJob(
        name="git_queue",
        worker=GitQueueWorker(),
        interval_type="minutes",
        interval_value=10,
        context=common_ctx,
    ))

    # WEEKLY (Monday 09:00 - Discovery)
    scheduler.register(ScheduledJob(
        name="scout_weekly",
        worker=ScoutWorker(cfg.get("scout")),
        interval_type="monday",
        at_time="09:00",
        context={**common_ctx, "force_refresh": False},
    ))

    # WEEKLY (Friday 17:00 - Digest)
    scheduler.register(ScheduledJob(
        name="weekly_digest",
        worker=DigestWorker(cfg.get("digest")),
        interval_type="friday",
        at_time="17:00",
        context=common_ctx,
    ))

    # MONTHLY (1st day 09:00 - Rebalance & Full Refresh)
    scheduler.register(ScheduledJob(
        name="monthly_rebalance",
        worker=RebalanceWorker(cfg.get("rebalance")),
        interval_type="days",
        interval_value=30,
        at_time="09:00",
        context=common_ctx,
    ))

    scheduler.register(ScheduledJob(
        name="monthly_full_refresh",
        worker=DataRefreshWorker(cfg.get("data_refresh")),
        interval_type="days",
        interval_value=30,
        at_time="06:00",
        context={**common_ctx, "max_tickers": 500, "force_refresh": True},
    ))

    # QUARTERLY (every 90 days - Deep Research & Post-Mortems)
    scheduler.register(ScheduledJob(
        name="quarterly_research",
        worker=ResearchWorker(cfg.get("research")),
        interval_type="quarterly",
        at_time="09:00",
        context=common_ctx,
    ))

    scheduler.register(ScheduledJob(
        name="quarterly_post_mortem",
        worker=PostMortemWorker(cfg.get("post_mortem")),
        interval_type="quarterly",
        at_time="10:00",
        context=common_ctx,
    ))

    return scheduler