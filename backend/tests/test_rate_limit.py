from concurrent.futures import ThreadPoolExecutor

from app.core.rate_limit import FixedWindowRateLimiter, normalize_client_ip


class Clock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now


def test_fixed_window_allows_limit_then_returns_positive_retry_after():
    clock = Clock()
    limiter = FixedWindowRateLimiter(
        limit=2,
        window_seconds=10,
        capacity=4,
        clock=clock,
    )

    assert limiter.check("client") is None
    assert limiter.check("client") is None
    assert limiter.check("client") == 10
    clock.now = 9.1
    assert limiter.check("client") == 1
    clock.now = 10
    assert limiter.check("client") is None


def test_fixed_window_is_concurrency_safe_and_bounded():
    limiter = FixedWindowRateLimiter(
        limit=12,
        window_seconds=60,
        capacity=3,
        clock=Clock(),
    )
    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(lambda _: limiter.check("client"), range(20)))

    assert results.count(None) == 12
    assert len([result for result in results if result is not None]) == 8

    for key in ("one", "two", "three", "four"):
        limiter.check(key)
    assert limiter.size <= 3


def test_normalize_client_ip_uses_ipv4_address_and_ipv6_prefix():
    assert normalize_client_ip("203.0.113.4") == "203.0.113.4"
    assert normalize_client_ip("2001:db8:1:2::1") == "2001:db8:1:2::/64"
    assert normalize_client_ip("2001:db8:1:2::99") == "2001:db8:1:2::/64"
    assert normalize_client_ip("2001:db8:1:3::1") == "2001:db8:1:3::/64"
    assert normalize_client_ip("not-an-ip") == "unknown"
