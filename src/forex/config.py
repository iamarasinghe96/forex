"""Load and validate the single operator configuration and environment secrets."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from forex.errors import OperatorError


class Secrets(BaseSettings):
    """Secrets read from `.env`; their values are never included in representations."""

    model_config = SettingsConfigDict(
    env_file=".env",
    env_prefix="FOREX_",
    extra="ignore",
    validate_default=True,
)
    mt5_password: str = Field(default="", min_length=1, repr=False)
    telegram_bot_token: str = Field(default="", repr=False)
    telegram_chat_id: str = Field(default="", repr=False)


class BrokerConfig(BaseModel):
    login: int = Field(gt=0)
    server: str = Field(min_length=1)
    terminal_path: str | None = None
    account_currency: str = Field(pattern=r"^[A-Z]{3}$")
    symbols: list[str] = Field(min_length=1)
    symbol_overrides: dict[str, str] = Field(default_factory=dict)
    magic_number: int = Field(gt=0)
    connect_timeout_seconds: int = Field(gt=0, le=300)


class LoggingConfig(BaseModel):
    directory: Path
    max_bytes: int = Field(gt=0)
    backup_count: int = Field(ge=1)


class DatabaseConfig(BaseModel):
    path: Path


class MarketDataConfig(BaseModel):
    stale_h1_hours: int = Field(default=3, gt=0)
    stale_h4_hours: int = Field(default=8, gt=0)
    weekend_close_weekday: int = Field(default=4, ge=0, le=6)
    weekend_close_hour_utc: int = Field(default=22, ge=0, le=23)
    weekend_open_weekday: int = Field(default=6, ge=0, le=6)
    weekend_open_hour_utc: int = Field(default=22, ge=0, le=23)
    history_chunk_days: int = Field(default=90, ge=7, le=366)
    history_retry_count: int = Field(default=3, ge=1, le=10)
    server_clock_tolerance_seconds: int = Field(default=300, gt=0, le=3600)
    # The paper bot builds H4 bars from H1 on these fixed UTC boundaries (0 = 00, 04, 08 ... UTC),
    # exactly like the research databases (`forex import-history`, default 0). MT5's own H4 bars
    # start at the broker's midnight (21:00/22:00 UTC) and would differ from everything tested.
    h4_alignment_hour_utc: int = Field(default=0, ge=0, le=3)


class AnalysisConfig(BaseModel):
    """UNVALIDATED Layer 3 research starting points; Layer 4 may vary every field."""

    strategy_version: str = "layer3-v1"
    parameter_version: str = "unvalidated-v1"
    ema_fast: int = Field(default=20, ge=2)
    ema_slow: int = Field(default=50, ge=3)
    ema_context: int = Field(default=200, ge=4)
    rsi_period: int = Field(default=14, ge=2)
    macd_fast: int = Field(default=12, ge=2)
    macd_slow: int = Field(default=26, ge=3)
    macd_signal: int = Field(default=9, ge=2)
    atr_period: int = Field(default=14, ge=2)
    structure_window: int = Field(default=20, ge=3)
    volatility_window: int = Field(default=100, ge=10)
    slope_lookback: int = Field(default=5, ge=1)
    return_horizons: list[int] = Field(default=[1, 5, 20], min_length=1)
    trend_threshold: float = Field(default=0.55, ge=0, le=1)
    range_threshold: float = Field(default=0.58, ge=0, le=1)
    setup_score_threshold: float = Field(default=0.45, ge=0, le=1)
    extreme_zscore: float = Field(default=1.0, gt=0)
    swing_trend_threshold: float = Field(default=0.68, ge=0, le=1)
    # Setup families allowed to produce candidates; others are recorded as no-trade decisions.
    allowed_setups: list[Literal["TREND_CONTINUATION_BREAKOUT_PULLBACK", "RANGE_MEAN_REVERSION"]] = Field(
        default=["TREND_CONTINUATION_BREAKOUT_PULLBACK", "RANGE_MEAN_REVERSION"], min_length=1)
    # J6-a: when False, a strong H4 trend is labelled a trend even in the top volatility decile.
    high_volatility_blocks_trend: bool = True
    # J6-b: bars for the directional-efficiency trend measure; None keeps structure_window.
    trend_efficiency_window: int | None = Field(default=None, ge=3)

    @model_validator(mode="after")
    def ordered_periods(self) -> AnalysisConfig:
        if not self.ema_fast < self.ema_slow < self.ema_context:
            raise ValueError("analysis EMA periods must satisfy fast < slow < context")
        if self.macd_fast >= self.macd_slow:
            raise ValueError("analysis MACD fast period must be below slow period")
        return self


class BacktestConfig(BaseModel):
    """Explicit, UNVALIDATED Layer 4 research assumptions (never live execution)."""

    forward_horizons_bars: list[int] = Field(default=[6, 24, 120], min_length=1)
    simulation_horizon_bars: int = Field(default=120, ge=1)
    reward_risk: float = Field(default=1.5, ge=1.5)
    breakeven_at_r: float | None = Field(default=1.0, ge=0)
    atr_trailing_multiple: float | None = Field(default=None, gt=0)
    ambiguity_policy: Literal["adverse", "ambiguous"] = "adverse"
    minimum_history_years: float = Field(default=5.0, ge=5.0)
    monte_carlo_iterations: int = Field(default=1000, ge=1)
    monte_carlo_seed: int = 26092801
    train_days: int = Field(default=365 * 2, ge=1)
    test_days: int = Field(default=180, ge=1)
    step_days: int = Field(default=180, ge=1)
    final_holdout_days: int = Field(default=365, ge=0)
    report_directory: Path = Path("reports/backtest")

    @model_validator(mode="after")
    def valid_horizons(self) -> BacktestConfig:
        if any(value < 1 for value in self.forward_horizons_bars):
            raise ValueError("backtest forward horizons must be positive")
        if len(set(self.forward_horizons_bars)) != len(self.forward_horizons_bars):
            raise ValueError("backtest forward horizons must be unique")
        return self


class TelegramConfig(BaseModel):
    enabled: bool
    timeout_seconds: int = Field(gt=0, le=60)


class RiskConfig(BaseModel):
    max_leverage: int = Field(gt=0, le=30)
    minimum_reward_risk: float = Field(ge=1.5)
    max_concurrent_positions: int = Field(gt=0)
    max_simultaneous_risk_percent: float = Field(gt=0, le=20)
    daily_loss_percent: float = Field(gt=0)
    tax_reserve_percent: float = Field(ge=0, le=100)
    conviction_risk_percent: dict[str, float]
    conviction_thresholds: dict[str, float]
    target_trades_per_week: dict[str, int]
    # Size trades so their margin (notional / account leverage) fits the account's free margin.
    enforce_margin: bool = True

    @model_validator(mode="after")
    def valid_conviction_policy(self) -> RiskConfig:
        expected = {"low", "medium", "high"}
        if set(self.conviction_risk_percent) != expected:
            raise ValueError("conviction_risk_percent requires exactly low, medium, high")
        if any(not 0 < value <= 100 for value in self.conviction_risk_percent.values()):
            raise ValueError("conviction risk percentages must be within 0..100")
        risks = self.conviction_risk_percent
        if not risks["low"] <= risks["medium"] <= risks["high"]:
            raise ValueError("conviction risk percentages must be non-decreasing")
        thresholds = self.conviction_thresholds
        if set(thresholds) != {"minimum", "medium", "high"}:
            raise ValueError("conviction_thresholds requires exactly minimum, medium, high")
        if not 0 <= thresholds["minimum"] < thresholds["medium"] < thresholds["high"] <= 100:
            raise ValueError("conviction thresholds must satisfy 0 <= minimum < medium < high <= 100")
        return self


class ContextProviderConfig(BaseModel):
    name: Literal["groq", "gemini", "openrouter"]
    model: str = ""  # Operator selects an available JSON-capable model; no guessed model ID.


class ContextConfig(BaseModel):
    enabled: bool = False
    providers: list[ContextProviderConfig] = Field(default_factory=list)
    timeout_seconds: float = Field(default=15, gt=0, le=120)
    attempts_per_provider: int = Field(default=2, ge=1, le=5)
    retry_backoff_seconds: float = Field(default=1, ge=0, le=30)
    max_output_tokens: int = Field(default=1500, ge=100, le=10000)
    prompt_file: Path = Path("src/forex/prompts/context-review-v1.md")

    @model_validator(mode="after")
    def configured_when_enabled(self) -> ContextConfig:
        if self.enabled and (not self.providers or any(not p.model.strip() for p in self.providers)):
            raise ValueError("enabled context requires provider model IDs; configure them first")
        if len({p.name for p in self.providers}) != len(self.providers):
            raise ValueError("context provider names must be unique")
        return self


class ExecutionConfig(BaseModel):
    demo_enabled: bool = False
    maximum_quote_age_seconds: float = Field(default=30, gt=0)
    maximum_decision_age_seconds: float = Field(default=300, gt=0)
    session_rollover_hour_utc: int | None = Field(default=None, ge=0, le=23)
    session_rollover: Literal["new_york_close"] | None = None

    @model_validator(mode="after")
    def one_session_boundary(self) -> ExecutionConfig:
        if self.session_rollover is not None and self.session_rollover_hour_utc is not None:
            raise ValueError("Choose New York close or a fixed UTC rollover, not both")
        return self

    @property
    def rollover_configured(self) -> bool:
        return self.session_rollover is not None or self.session_rollover_hour_utc is not None


class CloudConfig(BaseModel):
    enabled: bool = False
    emergency_halt_enabled: bool = False
    project_id: str = ""
    poll_seconds: float = Field(default=10, gt=0)
    batch_size: int = Field(default=50, ge=1, le=500)
    retry_base_seconds: float = Field(default=5, gt=0)
    retry_maximum_seconds: float = Field(default=300, gt=0)

    @model_validator(mode="after")
    def valid_cloud(self) -> CloudConfig:
        if self.enabled and not self.project_id.strip():
            raise ValueError("enabled cloud mirror requires a Firebase project ID")
        if self.emergency_halt_enabled and not self.enabled:
            raise ValueError("remote paper halt requires explicitly enabled cloud connection")
        if self.retry_base_seconds > self.retry_maximum_seconds:
            raise ValueError("cloud retry base cannot exceed maximum")
        return self


class PaperConfig(BaseModel):
    enabled: bool = False
    database: Path = Path("data/paper.sqlite3")
    starting_balance_aud: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    poll_seconds: float = Field(default=5, gt=0)
    history_days: int = Field(default=365, ge=60)
    heartbeat_file: Path = Path("data/paper-heartbeat.json")
    # Journal/cloud health records are throttled below the 120-second soak gap threshold;
    # the local heartbeat file is still written every cycle for the watchdog.
    health_journal_seconds: float = Field(default=60, gt=0, le=110)
    # A persistent failure (e.g. weekend quotes) is reported once, then at most this often.
    error_repeat_seconds: float = Field(default=3600, gt=0)
    # Failures shorter than this are logged locally only (no phone alert for one-cycle blips).
    error_grace_seconds: float = Field(default=30, ge=0)
    halt_file: Path = Path("data/HALT_PAPER")
    no_trade_hours: float = Field(default=168, gt=0)
    # Open trades allowed per pair. All research assumed 1; more stacks risk on the same move.
    max_positions_per_pair: int = Field(default=1, ge=1, le=4)
    # A pair without a fresh quote pauses its entries; only a silence longer than this is an error.
    stale_quote_alert_seconds: float = Field(default=900, gt=0)
    # J6-c exits: target in R (None = risk.minimum_reward_risk) and an ATR trailing stop that
    # starts once a trade reaches +1R (None = off). Paper only.
    target_reward_risk: float | None = Field(default=None, ge=1.5, allow_inf_nan=False)
    atr_trailing_multiple: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class LearningConfig(BaseModel):
    """Paper learning loop: trade scoring, AI trade reviews and Telegram-approved strategy patches."""

    enabled: bool = False
    trade_reviews: bool = True        # AI explanation of every closed trade (uses context providers).
    apply_to_sizing: bool = True      # Weak-scoring setups trade smaller; never above configured risk.
    prior_trades: int = Field(default=20, ge=1, le=500)   # Shrinkage: a bucket needs many trades to count.
    min_trades: int = Field(default=10, ge=1, le=500)     # Below this a bucket does not change sizing.
    min_factor: float = Field(default=0.25, gt=0, le=1)   # Smallest size multiplier for a weak bucket.
    skip_below_r: float | None = Field(default=None, ge=-2, le=0)  # Optional: skip clearly losing buckets.
    # A bucket shrinks trades only if its average R stays below 0 after adding this many standard
    # errors (2.5 ~ 1% chance per bucket of acting on a normal losing streak; 0 = any negative average).
    # Deliberately not changeable by a learning review.
    evidence_z: float = Field(default=2.5, ge=0, le=5)
    disabled_pairs: list[str] = Field(default_factory=list)
    telegram_commands: bool = True    # Accept /scores, /review, patches and /approve from the operator chat.
    review_prompt_file: Path = Path("src/forex/prompts/learning-review-v1.md")
    postmortem_prompt_file: Path = Path("src/forex/prompts/trade-postmortem-v1.md")
    # About an hour after each losing trade, write a self-contained review prompt for ChatGPT
    # (Telegram file, /loss command, dashboard copy button). Nothing is sent to an AI service.
    loss_prompts: bool = True
    loss_prompt_file: Path = Path("src/forex/prompts/loss-review-chatgpt-v1.md")


class ScoringConfig(BaseModel):
    """Offline-trained setup model; activation requires acceptance and shadow evidence."""

    enabled: bool = False
    shadow: bool = True
    model_path: Path = Path("data/models/setup-score-v1.json")
    kelly_fraction: float = Field(default=0.25, ge=0.25, le=0.5, allow_inf_nan=False)
    variance_r: float = Field(default=1.1, gt=0, allow_inf_nan=False)
    min_risk_percent: float = Field(default=0.25, ge=0, le=5, allow_inf_nan=False)
    max_risk_percent: float = Field(default=5, gt=0, le=5, allow_inf_nan=False)
    skip_below_expected_r: float = Field(default=0, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered_risk(self) -> ScoringConfig:
        if self.min_risk_percent > self.max_risk_percent:
            raise ValueError("scoring minimum risk must not exceed maximum risk")
        return self


class AppConfig(BaseModel):
    mode: Literal["paper", "live"]
    operator_timezone: str
    broker: BrokerConfig
    logging: LoggingConfig
    database: DatabaseConfig
    market_data: MarketDataConfig = Field(default_factory=MarketDataConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)
    telegram: TelegramConfig
    risk: RiskConfig
    context: ContextConfig = Field(default_factory=lambda: ContextConfig())
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    cloud: CloudConfig = Field(default_factory=CloudConfig)
    paper: PaperConfig = Field(default_factory=PaperConfig)
    learning: LearningConfig = Field(default_factory=LearningConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)

    @model_validator(mode="after")
    def live_requires_deliberate_config(self) -> AppConfig:
        if self.mode == "live" and "Demo" in self.broker.server:
            raise ValueError("live mode cannot be paired with a demo server")
        return self


def load_config(path: Path) -> AppConfig:
    """Read YAML and return a validated configuration or actionable failure."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return AppConfig.model_validate(raw)
    except FileNotFoundError as exc:
        raise OperatorError(
            f"Configuration file {path} was not found. Copy config.yaml beside the command "
            "and run it again."
        ) from exc
    except (OSError, yaml.YAMLError, ValueError) as exc:
        raise OperatorError(
            f"Configuration {path} is invalid: {exc}. Correct the named setting in config.yaml."
        ) from exc
