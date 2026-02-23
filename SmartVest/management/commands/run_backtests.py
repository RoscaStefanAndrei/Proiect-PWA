"""
Management command: Automated Backtest Runner
==============================================

Runs backtests continuously with diverse parameters to build a statistical
sample. Results are saved to BacktestRun model.

Usage:
    python manage.py run_backtests                  # Run indefinitely
    python manage.py run_backtests --max-runs 10    # Run 10 then stop
    python manage.py run_backtests --profile balanced  # Only balanced
"""

import datetime
import random
import time
import traceback

from django.core.management.base import BaseCommand
from django.db.models import Count

from SmartVest.models import BacktestRun
from backtester import BacktestEngine


# Profile name mapping for Romanian naming convention
PROFILE_NAMES = {
    'conservative': 'conservator',
    'balanced': 'balansat',
    'aggressive': 'agresiv',
}

# Date range for generating test scenarios
EARLIEST_START = datetime.date(2018, 1, 1)
LATEST_END = datetime.date(2025, 12, 31)
MAX_PERIOD_DAYS = 365  # Max 1 year per backtest


def generate_scenario(profile=None):
    """
    Generate a random backtest scenario.
    Returns (start_date, end_date, profile_type).
    """
    if profile is None:
        profile = random.choice(['conservative', 'balanced', 'aggressive'])

    # Random start date between EARLIEST_START and LATEST_END - 180 days
    latest_start = LATEST_END - datetime.timedelta(days=180)
    days_range = (latest_start - EARLIEST_START).days
    random_offset = random.randint(0, days_range)
    start_date = EARLIEST_START + datetime.timedelta(days=random_offset)

    # Fixed 12-month duration
    duration = MAX_PERIOD_DAYS
    end_date = start_date + datetime.timedelta(days=duration)

    # Clamp end date
    if end_date > LATEST_END:
        end_date = LATEST_END

    return start_date, end_date, profile


def generate_name(profile_type):
    """
    Generate the next sequential name: bkt_agresiv_1, bkt_balansat_2, etc.
    """
    ro_name = PROFILE_NAMES[profile_type]
    prefix = f"bkt_{ro_name}_"

    # Count existing runs for this profile
    existing = BacktestRun.objects.filter(
        name__startswith=prefix
    ).count()

    return f"{prefix}{existing + 1}"


def is_duplicate(start_date, end_date, profile_type):
    """Check if this exact scenario was already run."""
    return BacktestRun.objects.filter(
        profile_type=profile_type,
        start_date=start_date,
        end_date=end_date,
        status='done',
    ).exists()


class Command(BaseCommand):
    help = 'Run backtests continuously to build a statistical sample.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--max-runs', type=int, default=0,
            help='Maximum number of runs (0 = indefinite)',
        )
        parser.add_argument(
            '--profile', type=str, default=None,
            choices=['conservative', 'balanced', 'aggressive'],
            help='Run only this profile type',
        )
        parser.add_argument(
            '--capital', type=float, default=10000.0,
            help='Initial capital for each backtest',
        )

    def handle(self, *args, **options):
        max_runs = options['max_runs']
        profile_filter = options['profile']
        capital = options['capital']

        self.stdout.write(self.style.SUCCESS(
            "\n" + "=" * 60 +
            "\n🤖 SmartVest Automated Backtest Runner" +
            "\n" + "=" * 60
        ))
        self.stdout.write(f"  Perioade: {EARLIEST_START} → {LATEST_END}")
        self.stdout.write(f"  Durată max: {MAX_PERIOD_DAYS} zile (1 an)")
        self.stdout.write(f"  Capital: ${capital:,.0f}")
        self.stdout.write(f"  Profil: {profile_filter or 'TOATE'}")
        self.stdout.write(f"  Max rulări: {max_runs or '∞'}")

        existing_count = BacktestRun.objects.filter(status='done').count()
        self.stdout.write(f"  Rulări existente în DB: {existing_count}")
        self.stdout.write("=" * 60 + "\n")

        run_count = 0

        try:
            while True:
                if max_runs > 0 and run_count >= max_runs:
                    self.stdout.write(self.style.SUCCESS(
                        f"\n✅ Am terminat {max_runs} rulări. Oprire."
                    ))
                    break

                # Generate scenario
                start_date, end_date, profile_type = generate_scenario(profile_filter)

                # Skip duplicates
                retries = 0
                while is_duplicate(start_date, end_date, profile_type) and retries < 20:
                    start_date, end_date, profile_type = generate_scenario(profile_filter)
                    retries += 1

                if retries >= 20:
                    self.stdout.write(self.style.WARNING(
                        "⚠️  Nu am găsit scenarii noi. Încetinire..."
                    ))
                    time.sleep(5)
                    continue

                run_count += 1
                name = generate_name(profile_type)

                self.stdout.write(self.style.HTTP_INFO(
                    f"\n{'─' * 60}"
                    f"\n🔬 Rulare #{run_count}: {name}"
                    f"\n   {start_date} → {end_date} ({(end_date - start_date).days}d)"
                    f"\n   Profil: {profile_type.upper()}"
                    f"\n{'─' * 60}"
                ))

                # Create DB record
                run_record = BacktestRun.objects.create(
                    name=name,
                    status='running',
                    profile_type=profile_type,
                    start_date=start_date,
                    end_date=end_date,
                    initial_capital=capital,
                    rebalance_months=3,
                )

                t_start = time.time()

                try:
                    # Run the backtest
                    engine = BacktestEngine(
                        start_date=start_date.strftime('%Y-%m-%d'),
                        end_date=end_date.strftime('%Y-%m-%d'),
                        profile_type=profile_type,
                        initial_capital=capital,
                        rebalance_months=3,
                        progress_callback=lambda msg, pct: None,  # Silent
                    )

                    result = engine.run()
                    duration = time.time() - t_start
                    result_dict = result.to_dict()
                    metrics = result_dict.get('metrics', {})

                    if metrics.get('error'):
                        run_record.status = 'failed'
                        run_record.error_message = metrics['error']
                        run_record.duration_seconds = duration
                        run_record.save()

                        self.stdout.write(self.style.ERROR(
                            f"   ❌ Eșuat: {metrics['error']}"
                        ))
                        continue

                    # Compute avg stocks per rebalance
                    snapshots = result_dict.get('snapshots', [])
                    n_stocks_list = [s.get('n_stocks', 0) for s in snapshots if s.get('n_stocks', 0) > 0]
                    avg_stocks = sum(n_stocks_list) / len(n_stocks_list) if n_stocks_list else 0

                    # Format snapshot allocations as percentages
                    for snap in snapshots:
                        if snap.get('allocations'):
                            snap['allocations'] = {
                                k: round(v * 100, 1)
                                for k, v in snap['allocations'].items()
                                if v > 0
                            }

                    # Save results
                    run_record.status = 'done'
                    run_record.total_return = metrics.get('total_return')
                    run_record.cagr = metrics.get('cagr')
                    run_record.sharpe_ratio = metrics.get('sharpe_ratio')
                    run_record.sortino_ratio = metrics.get('sortino_ratio')
                    run_record.max_drawdown = metrics.get('max_drawdown')
                    run_record.max_drawdown_duration = metrics.get('max_drawdown_duration')
                    run_record.calmar_ratio = metrics.get('calmar_ratio')
                    run_record.annual_volatility = metrics.get('annual_volatility')
                    run_record.alpha = metrics.get('alpha')
                    run_record.beta = metrics.get('beta')
                    run_record.benchmark_return = metrics.get('benchmark_return')
                    run_record.outperformance = metrics.get('outperformance')
                    run_record.final_value = metrics.get('final_value')
                    run_record.n_trading_days = metrics.get('n_trading_days')
                    run_record.n_rebalances = len(snapshots)
                    run_record.n_stocks_avg = round(avg_stocks, 1)
                    run_record.equity_curve_json = result_dict.get('equity_curve', {})
                    run_record.benchmark_curve_json = result_dict.get('benchmark_curve', {})
                    run_record.snapshots_json = snapshots
                    run_record.duration_seconds = duration
                    run_record.save()

                    # Print summary
                    ret = metrics.get('total_return', 0) or 0
                    sharpe = metrics.get('sharpe_ratio', 0) or 0
                    dd = metrics.get('max_drawdown', 0) or 0
                    color = self.style.SUCCESS if ret >= 0 else self.style.ERROR
                    self.stdout.write(color(
                        f"   ✅ {name} — Return: {ret:+.1f}%, "
                        f"Sharpe: {sharpe:.2f}, MaxDD: {dd:.1f}%, "
                        f"Stocks: {avg_stocks:.0f}, "
                        f"Timp: {duration:.0f}s"
                    ))

                    # Running totals
                    done_count = BacktestRun.objects.filter(status='done').count()
                    self.stdout.write(f"   📊 Total în DB: {done_count} rulări finalizate")

                except Exception as e:
                    duration = time.time() - t_start
                    run_record.status = 'failed'
                    run_record.error_message = str(e)
                    run_record.duration_seconds = duration
                    run_record.save()

                    self.stdout.write(self.style.ERROR(
                        f"   ❌ Eroare: {e}"
                    ))
                    traceback.print_exc()

                # Brief pause between runs
                time.sleep(2)

        except KeyboardInterrupt:
            self.stdout.write(self.style.SUCCESS(
                f"\n\n🛑 Oprit de utilizator după {run_count} rulări."
            ))
            # Mark any 'running' records as failed
            BacktestRun.objects.filter(status='running').update(
                status='failed',
                error_message='Interrupted by user'
            )

        # Final summary
        done = BacktestRun.objects.filter(status='done')
        failed = BacktestRun.objects.filter(status='failed')
        self.stdout.write(self.style.SUCCESS(
            f"\n{'=' * 60}"
            f"\n📊 SUMAR FINAL"
            f"\n   Total finalizate: {done.count()}"
            f"\n   Total eșuate: {failed.count()}"
            f"\n{'=' * 60}"
        ))
