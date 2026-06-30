from __future__ import annotations


def _require_acme_deps() -> None:
    try:
        import acme  # noqa: F401
        import josepy  # noqa: F401
        from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: F401
    except ImportError:
        raise SystemExit(
            "HTTPS cert dependencies not installed.\n"
            "Run: pip install acme josepy cryptography"
        )


def _letsencrypt_https(bucket: object, domain: str) -> tuple[str, str]:
    """Obtain a Let's Encrypt cert for `domain` via HTTP-01 challenge using OSS as webroot."""
    _require_acme_deps()

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend
    from acme import client as acme_client_lib, challenges, messages, crypto_util
    import josepy as jose

    print(f"  generating account key ...")
    account_key_rsa = rsa.generate_private_key(65537, 2048, default_backend())
    account_key_pem = account_key_rsa.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    jwk = jose.JWKRSA(key=account_key_rsa)

    print(f"  connecting to Let's Encrypt ...")
    net = acme_client_lib.ClientNetwork(jwk, user_agent="vidctl/1.0")
    directory = acme_client_lib.ClientV2.get_directory(
        "https://acme-v02.api.letsencrypt.org/directory", net
    )
    acme = acme_client_lib.ClientV2(directory, net)
    acme.new_account(
        messages.NewRegistration.from_data(terms_of_service_agreed=True)
    )

    print(f"  generating domain key ...")
    domain_key_rsa = rsa.generate_private_key(65537, 2048, default_backend())
    domain_key_pem = domain_key_rsa.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )

    csr_pem = crypto_util.make_csr(domain_key_pem, [domain])
    orderr = acme.new_order(csr_pem)

    http_chall = None
    for authz in orderr.authorizations:
        for ch in authz.body.challenges:
            if isinstance(ch.chall, challenges.HTTP01):
                http_chall = ch
                break
        if http_chall:
            break

    if not http_chall:
        raise SystemExit("No HTTP-01 challenge available from Let's Encrypt for this domain.")

    chall_key = http_chall.chall.path.lstrip("/")
    chall_response = http_chall.response(jwk)
    bucket.put_object(  # type: ignore[union-attr]
        chall_key,
        chall_response.key_authorization.encode(),
        headers={"Content-Type": "text/plain"},
    )
    print(f"  uploaded challenge: /{chall_key}")

    acme.answer_challenge(http_chall, chall_response)
    print(f"  waiting for Let's Encrypt to validate {domain} ...")
    finalized = acme.poll_and_finalize(orderr)

    try:
        bucket.delete_object(chall_key)  # type: ignore[union-attr]
    except Exception:
        pass

    print(f"  certificate issued")
    return finalized.fullchain_pem, domain_key_pem.decode()


def _bind_domain_https(bucket: object, oss2: object, domain: str, cert_pem: str, key_pem: str) -> None:
    cert_config = oss2.models.CertificateConfig(  # type: ignore[union-attr]
        certificate=cert_pem,
        private_key=key_pem,
        force=True,
    )
    request = oss2.models.PutBucketCnameRequest(domain, cert_config)  # type: ignore[union-attr]
    bucket.put_bucket_cname(request)  # type: ignore[union-attr]
