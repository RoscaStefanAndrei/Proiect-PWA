"""
SmartVest Periodic Tasks (Huey)
===============================
Background tasks for price alerts, portfolio monitoring, and unicorn scanning.

These tasks run in the Huey worker process. In local dev with DEBUG=True and
no Redis, they run synchronously (immediate mode).
"""

import logging
from datetime import date

from django.contrib.auth.models import User
from django.core.cache import cache
from django.utils import timezone
from huey import crontab
from huey.contrib.djhuey import periodic_task

from .models import (
    Notification,
    NotificationPreference,
    PriceAlert,
    SavedPortfolio,
    WatchedUnicorn,
)
from .notifications import send_notification
from .utils import _is_market_open, fetch_prices_cached, get_portfolio_performance

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _alert_dedup_key(user_id, ticker):
    """Cache key to prevent duplicate alerts for the same ticker on the same day."""
    return f"sv_alert_sent_{user_id}_{ticker}_{date.today().isoformat()}"


def _was_alert_sent(user_id, ticker):
    return cache.get(_alert_dedup_key(user_id, ticker)) is not None


def _mark_alert_sent(user_id, ticker):
    cache.set(_alert_dedup_key(user_id, ticker), True, timeout=86400)


# ---------------------------------------------------------------------------
# Task 1: Price Alerts (every 15 minutes during market hours)
# ---------------------------------------------------------------------------

@periodic_task(crontab(minute='*/15'))
def check_price_alerts():
    """Check price targets and significant daily moves for watched stocks."""
    if not _is_market_open():
        return

    logger.info("Running price alert check...")

    # 1. Collect all tickers that need price checks
    # From explicit PriceAlert targets
    active_alerts = PriceAlert.objects.filter(is_triggered=False).select_related('user')

    # From WatchedUnicorn entries with target prices
    watched_with_targets = WatchedUnicorn.objects.filter(
        target_price__isnull=False
    ).select_related('user')

    # From all watched unicorns (for daily % move alerts)
    all_watched = WatchedUnicorn.objects.filter(
        entry_price__isnull=False
    ).select_related('user')

    tickers = set()
    for a in active_alerts:
        tickers.add(a.ticker)
    for w in watched_with_targets:
        tickers.add(w.ticker)
    for w in all_watched:
        tickers.add(w.ticker)

    if not tickers:
        logger.debug("No tickers to check for price alerts")
        return

    # 2. Fetch current prices
    current_prices, prev_closes = fetch_prices_cached(tickers)

    # 3. Check explicit PriceAlert targets
    triggered_alerts = []
    for alert in active_alerts:
        curr = current_prices.get(alert.ticker)
        if curr is None:
            continue

        hit = False
        if alert.direction == PriceAlert.Direction.ABOVE and curr >= float(alert.target_price):
            hit = True
        elif alert.direction == PriceAlert.Direction.BELOW and curr <= float(alert.target_price):
            hit = True

        if hit:
            alert.is_triggered = True
            alert.triggered_at = timezone.now()
            triggered_alerts.append(alert)

            direction_label = "rose above" if alert.direction == PriceAlert.Direction.ABOVE else "dropped below"
            send_notification(
                user=alert.user,
                notification_type=Notification.Type.PRICE_ALERT,
                title=f"{alert.ticker} {direction_label} ${alert.target_price}",
                message=f"{alert.ticker} is now at ${curr:.2f} (target: ${alert.target_price}).",
                link="/unicorns/watchlist/",
            )
            logger.info("Price alert triggered: %s %s $%s for user %s",
                         alert.ticker, direction_label, alert.target_price, alert.user.username)

    if triggered_alerts:
        PriceAlert.objects.bulk_update(triggered_alerts, ['is_triggered', 'triggered_at'])

    # 4. Check WatchedUnicorn target prices
    for w in watched_with_targets:
        curr = current_prices.get(w.ticker)
        if curr is None or _was_alert_sent(w.user_id, w.ticker):
            continue

        target = float(w.target_price)
        if curr >= target:
            send_notification(
                user=w.user,
                notification_type=Notification.Type.PRICE_ALERT,
                title=f"{w.ticker} hit target ${target:.2f}",
                message=f"{w.ticker} reached ${curr:.2f} (your target: ${target:.2f}).",
                link="/unicorns/watchlist/",
            )
            _mark_alert_sent(w.user_id, w.ticker)

    # 5. Check daily % moves against user thresholds
    users_checked = set()
    for w in all_watched:
        curr = current_prices.get(w.ticker)
        prev = prev_closes.get(w.ticker)
        if not curr or not prev or prev == 0:
            continue
        if _was_alert_sent(w.user_id, w.ticker):
            continue

        daily_pct = abs((curr - prev) / prev) * 100
        direction = "up" if curr > prev else "down"

        # Get user's threshold (cache to avoid repeated DB hits for same user)
        if w.user_id not in users_checked:
            users_checked.add(w.user_id)

        prefs, _ = NotificationPreference.objects.get_or_create(user=w.user)
        threshold = float(prefs.price_change_threshold)

        if daily_pct >= threshold:
            send_notification(
                user=w.user,
                notification_type=Notification.Type.PRICE_ALERT,
                title=f"{w.ticker} {direction} {daily_pct:.1f}% today",
                message=f"{w.ticker} moved from ${prev:.2f} to ${curr:.2f} ({'+' if curr > prev else ''}{curr - prev:.2f}).",
                link="/unicorns/watchlist/",
            )
            _mark_alert_sent(w.user_id, w.ticker)

    logger.info("Price alert check complete")


# ---------------------------------------------------------------------------
# Task 2: Portfolio Alerts (daily at 4:30 PM ET / 21:30 UTC)
# ---------------------------------------------------------------------------

@periodic_task(crontab(hour=21, minute=30))
def check_portfolio_alerts():
    """Check for significant portfolio drawdowns or gains."""
    logger.info("Running daily portfolio alert check...")

    # Get all users who have portfolio alerts enabled
    prefs_qs = NotificationPreference.objects.filter(
        portfolio_alerts_enabled=True
    ).select_related('user')

    for prefs in prefs_qs:
        user = prefs.user
        portfolios = list(SavedPortfolio.objects.filter(user=user))
        if not portfolios:
            continue

        # Dedup: one alert per user per day
        dedup_key = f"sv_portfolio_alert_{user.id}_{date.today().isoformat()}"
        if cache.get(dedup_key):
            continue

        try:
            perf_data = get_portfolio_performance(portfolios)
        except Exception:
            logger.exception("Error computing portfolio performance for user %s", user.username)
            continue

        threshold = float(prefs.portfolio_drawdown_threshold)

        for perf in perf_data:
            portfolio = perf['portfolio']
            return_pct = perf['return_pct']

            # Drawdown warning
            if return_pct <= -threshold:
                send_notification(
                    user=user,
                    notification_type=Notification.Type.PORTFOLIO_ALERT,
                    title=f"{portfolio.name} down {abs(return_pct):.1f}%",
                    message=f"Your portfolio '{portfolio.name}' has lost ${abs(perf['profit_loss']):.2f} ({return_pct:.1f}% from initial).",
                    link=f"/portfolios/{portfolio.pk}/",
                )
                cache.set(dedup_key, True, timeout=86400)
                logger.info("Portfolio drawdown alert for user %s: %s at %.1f%%",
                             user.username, portfolio.name, return_pct)

            # Big gain notification (>20%)
            elif return_pct >= 20:
                send_notification(
                    user=user,
                    notification_type=Notification.Type.PORTFOLIO_ALERT,
                    title=f"{portfolio.name} up {return_pct:.1f}%!",
                    message=f"Your portfolio '{portfolio.name}' has gained ${perf['profit_loss']:.2f} (+{return_pct:.1f}%).",
                    link=f"/portfolios/{portfolio.pk}/",
                )
                cache.set(dedup_key, True, timeout=86400)

    logger.info("Portfolio alert check complete")


# ---------------------------------------------------------------------------
# Task 3: Unicorn Scan (daily at 6:00 AM ET / 11:00 UTC)
# ---------------------------------------------------------------------------

_LAST_UNICORN_SCAN_KEY = "sv_last_unicorn_tickers"


@periodic_task(crontab(hour=11, minute=0))
def scan_for_new_unicorns():
    """Run daily unicorn scan and notify users of new 3/3 candidates."""
    logger.info("Running daily unicorn scan...")

    try:
        from unicorn_scanner import scan_for_unicorns
        df_all, _ = scan_for_unicorns()
    except Exception:
        logger.exception("Unicorn scan failed")
        return

    if df_all is None or df_all.empty:
        logger.info("Unicorn scan returned no results")
        return

    # Filter to perfect 3/3 scores
    perfect = df_all[df_all.get('Unicorn_Score', 0) >= 3]
    if perfect.empty:
        logger.info("No 3/3 unicorns found")
        cache.set(_LAST_UNICORN_SCAN_KEY, set(), timeout=172800)
        return

    current_tickers = set(perfect['Ticker'].tolist())
    previous_tickers = cache.get(_LAST_UNICORN_SCAN_KEY) or set()

    # Find NEW unicorns (in current but not in previous scan)
    new_tickers = current_tickers - previous_tickers
    cache.set(_LAST_UNICORN_SCAN_KEY, current_tickers, timeout=172800)  # 48h TTL

    if not new_tickers:
        logger.info("No new unicorns (all %d already known)", len(current_tickers))
        return

    logger.info("Found %d new unicorn(s): %s", len(new_tickers), new_tickers)

    # Get companies info for notification message
    new_stocks = perfect[perfect['Ticker'].isin(new_tickers)]
    ticker_names = dict(zip(
        new_stocks['Ticker'],
        new_stocks.get('Company', new_stocks['Ticker'])
    ))

    # Notify all users with unicorn alerts enabled
    users = NotificationPreference.objects.filter(
        unicorn_alerts_enabled=True
    ).select_related('user')

    for prefs in users:
        for ticker in new_tickers:
            company = ticker_names.get(ticker, ticker)
            send_notification(
                user=prefs.user,
                notification_type=Notification.Type.UNICORN_FOUND,
                title=f"New Unicorn: {ticker}",
                message=f"{company} scored 3/3 on the unicorn scanner. RSI, volume, and 52-week high all bullish.",
                link="/unicorns/",
            )

    logger.info("Unicorn scan complete — notified %d users about %d new unicorns",
                 users.count(), len(new_tickers))


# ---------------------------------------------------------------------------
# Task 4: Portfolio Health Check (weekly, Monday 8 AM ET / 13:00 UTC)
# ---------------------------------------------------------------------------

@periodic_task(crontab(day_of_week='1', hour=13, minute=0))
def weekly_portfolio_health():
    """Check all portfolios for underperforming stocks and notify users."""
    import numpy as np

    logger.info("Running weekly portfolio health check...")

    prefs_qs = NotificationPreference.objects.filter(
        portfolio_alerts_enabled=True
    ).select_related('user')

    notified = 0
    for prefs in prefs_qs:
        user = prefs.user
        portfolios = list(SavedPortfolio.objects.filter(user=user))
        if not portfolios:
            continue

        for portfolio in portfolios:
            # Dedup: one health notification per portfolio per week
            week_num = date.today().isocalendar()[1]
            dedup_key = f"sv_health_notif_{portfolio.pk}_{date.today().year}_{week_num}"
            if cache.get(dedup_key):
                continue

            # Quick underperformer scan (no replacement search)
            from .rebalance import _parse_holdings, _parse_float, LOSS_THRESHOLD, RELATIVE_GAP

            holdings = _parse_holdings(portfolio)
            if not holdings:
                continue

            tickers = [h['ticker'] for h in holdings]
            current_prices, _ = fetch_prices_cached(tickers)

            for h in holdings:
                curr = current_prices.get(h['ticker'], 0)
                h['return_pct'] = (
                    ((curr - h['avg_price']) / h['avg_price'] * 100)
                    if h['avg_price'] > 0 else 0
                )

            avg_return = float(np.mean([h['return_pct'] for h in holdings]))

            flagged = []
            for h in holdings:
                if h['return_pct'] <= LOSS_THRESHOLD:
                    flagged.append(h['ticker'])
                elif avg_return - h['return_pct'] >= RELATIVE_GAP:
                    flagged.append(h['ticker'])

            if not flagged:
                continue

            names = ', '.join(flagged[:5])
            suffix = f' +{len(flagged) - 5} more' if len(flagged) > 5 else ''

            send_notification(
                user=user,
                notification_type=Notification.Type.PORTFOLIO_ALERT,
                title=f"{portfolio.name}: {len(flagged)} stocks flagged",
                message=f"Underperforming: {names}{suffix}. Run a health check for replacement suggestions.",
                link=f"/portfolios/{portfolio.pk}/health/",
            )
            cache.set(dedup_key, True, timeout=604800)  # 1 week
            notified += 1

    logger.info("Portfolio health check complete — sent %d notifications", notified)
