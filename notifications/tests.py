from django.test import TestCase

from config.test_factories import make_owner
from .models import NotificationSetting


class NotificationSettingIsolationTests(TestCase):
    def setUp(self):
        self.owner_a = make_owner("owner_a")
        self.owner_b = make_owner("owner_b")

    def test_each_owner_gets_their_own_settings_row(self):
        setting_a = NotificationSetting.for_owner(self.owner_a)
        setting_b = NotificationSetting.for_owner(self.owner_b)

        self.assertNotEqual(setting_a.pk, setting_b.pk)
        self.assertEqual(setting_a.owner, self.owner_a)
        self.assertEqual(setting_b.owner, self.owner_b)

    def test_for_owner_is_idempotent_and_isolated(self):
        setting_a = NotificationSetting.for_owner(self.owner_a)
        setting_a.rent_reminder_days_before = 9
        setting_a.save()

        # Re-fetching the same owner returns the same row with the change.
        self.assertEqual(
            NotificationSetting.for_owner(self.owner_a).rent_reminder_days_before, 9
        )
        # The other owner keeps the default.
        self.assertEqual(
            NotificationSetting.for_owner(self.owner_b).rent_reminder_days_before, 3
        )

    def test_for_owner_none_returns_unsaved_defaults(self):
        setting = NotificationSetting.for_owner(None)
        self.assertIsNone(setting.owner)
        self.assertIsNone(setting.pk)
