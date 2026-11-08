"""Regression tests for shared Traefik's public routing contract."""
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parent.parent


class SharedTraefikConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        cls.routes = yaml.safe_load((ROOT / "dynamic/utbildningsintyg.yml").read_text(encoding="utf-8"))
        cls.common = yaml.safe_load((ROOT / "dynamic/tls.yml").read_text(encoding="utf-8"))

    def test_shared_proxy_owns_https_and_reads_file_provider(self):
        config = self.compose["services"]["traefik"]
        command = config["command"]
        self.assertIn("--providers.file.directory=/etc/traefik/dynamic", command)
        self.assertIn("--providers.docker.exposedbydefault=false", command)
        self.assertIn("--entrypoints.websecure.address=:443", command)
        self.assertIn("--entrypoints.websecure.http.tls=true", command)
        self.assertIn("./dynamic:/etc/traefik/dynamic:ro", config["volumes"])
        self.assertTrue(self.compose["networks"]["public_net"]["external"])
        self.assertEqual(self.compose["networks"]["public_net"]["name"], "jk_public_net")

    def test_routes_use_central_tls_security_and_correct_hostnames(self):
        routers = self.routes["http"]["routers"]
        web = routers["utbildningsintyg-web"]
        mta = routers["utbildningsintyg-mta-sts"]
        self.assertEqual(
            web["rule"],
            "Host(`utbildningsintyg.se`) || Host(`www.utbildningsintyg.se`)",
        )
        self.assertEqual(
            mta["rule"],
            "Host(`mta-sts.utbildningsintyg.se`) && Path(`/.well-known/mta-sts.txt`)",
        )
        for router in (web, mta):
            self.assertEqual(router["entryPoints"], ["websecure"])
            self.assertEqual(router["tls"], {})
            self.assertEqual(router["service"], "utbildningsintyg-backend")
            self.assertEqual(router["priority"], 1)
            self.assertIn("security-headers", router["middlewares"])
        self.assertIn("upload-buffer", web["middlewares"])
        self.assertNotIn("upload-buffer", mta["middlewares"])

    def test_backend_address_is_stable_network_alias_not_docker_container_name(self):
        backend = self.routes["http"]["services"]["utbildningsintyg-backend"]
        self.assertEqual(backend["loadBalancer"]["servers"], [{"url": "http://utbildningsintyg-web:80"}])
        self.assertNotIn("labels", self.compose["services"]["traefik"])

    def test_security_headers_and_certificates_remain_in_shared_proxy(self):
        middlewares = self.common["http"]["middlewares"]
        self.assertTrue(middlewares["security-headers"]["headers"]["contentTypeNosniff"])
        self.assertEqual(middlewares["security-headers"]["headers"]["stsSeconds"], 63072000)
        self.assertEqual(middlewares["upload-buffer"]["buffering"]["maxRequestBodyBytes"], 104857600)
        certificates = self.common["tls"]["certificates"]
        self.assertEqual(certificates[0]["certFile"], "/etc/traefik/certs/origin.crt")
        self.assertEqual(certificates[0]["keyFile"], "/etc/traefik/certs/origin.key")


if __name__ == "__main__":
    unittest.main()
