from cli.scenario.fast_health_poller import healthz_url


def test_healthz_url_uses_path_based_routing() -> None:
    url = healthz_url("45.79.134.247", "akamai", "001", "relay", 1)
    assert url == "https://45-79-134-247.sslip.io/akamai-001/relay-1/healthz"
