import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase


class ServiceWorkerTests(SimpleTestCase):
    def test_service_worker_is_served_from_root_scope(self):
        response = self.client.get("/sw.js")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            response["Content-Type"].startswith("application/javascript")
        )
        # Must be allowed to control the whole origin, not just /static/.
        self.assertEqual(response["Service-Worker-Allowed"], "/")
        self.assertIn('addEventListener("install"', response.content.decode())


class ManifestTests(SimpleTestCase):
    def setUp(self):
        self.manifest_path = Path(settings.BASE_DIR) / "static" / "manifest.webmanifest"
        with self.manifest_path.open(encoding="utf-8") as fh:
            self.manifest = json.load(fh)

    def test_manifest_has_required_pwa_fields(self):
        for key in ("name", "short_name", "start_url", "scope", "display", "icons"):
            self.assertIn(key, self.manifest)
        self.assertIn(self.manifest["display"], ("standalone", "fullscreen", "minimal-ui"))
        self.assertEqual(self.manifest["scope"], "/")

    def test_manifest_has_installable_icons(self):
        icons = self.manifest["icons"]
        sizes = {icon["sizes"] for icon in icons}
        # Chrome requires at least 192px and 512px icons.
        self.assertIn("192x192", sizes)
        self.assertIn("512x512", sizes)
        self.assertTrue(
            any(icon.get("purpose") == "maskable" for icon in icons),
            "A maskable icon is required for good Android rendering.",
        )

    def test_manifest_icon_files_exist(self):
        for icon in self.manifest["icons"]:
            src = icon["src"]
            # Manifest uses absolute /static/... URLs; map back to disk.
            relative = src.lstrip("/")
            self.assertTrue(
                (Path(settings.BASE_DIR) / relative).exists(),
                f"Missing icon file: {src}",
            )


class PwaHeadAndInstallUiTests(SimpleTestCase):
    """The login page must expose everything a browser needs to offer install."""

    def test_login_page_exposes_pwa_install_metadata(self):
        response = self.client.get("/accounts/login/")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('rel="manifest"', html)
        self.assertIn("manifest.webmanifest", html)
        self.assertIn("pwa.js", html)
        # An install button must be present and NOT hidden by default.
        self.assertIn("pwa-install-btn", html)
        self.assertNotIn('class="btn btn-sm btn-outline-primary d-none pwa-install-btn"', html)

    def test_service_worker_view_is_reachable_without_login(self):
        # Browsers fetch /sw.js anonymously; it must not require auth.
        response = self.client.get("/sw.js")
        self.assertEqual(response.status_code, 200)


class AdminLinkVisibilityTests(TestCase):
    """Only superusers should see the Django admin link in the top bar."""

    def test_superuser_sees_admin_link(self):
        user = get_user_model().objects.create_user(
            username="root", password="pass12345", is_superuser=True, is_staff=True
        )
        self.client.force_login(user)
        html = self.client.get("/").content.decode()
        self.assertIn('href="/admin/"', html)

    def test_regular_user_does_not_see_admin_link(self):
        user = get_user_model().objects.create_user(
            username="plain", password="pass12345"
        )
        self.client.force_login(user)
        html = self.client.get("/").content.decode()
        self.assertNotIn('href="/admin/"', html)
