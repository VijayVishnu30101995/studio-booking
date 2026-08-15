from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from apps.studios.validators import validate_iana_timezone


class IANATimezoneValidatorTests(SimpleTestCase):
    def test_accepts_valid_iana_timezones(self) -> None:
        valid_timezones = [
            "Asia/Kolkata",
            "America/New_York",
            "Europe/London",
        ]

        for timezone in valid_timezones:
            with self.subTest(timezone=timezone):
                validate_iana_timezone(timezone)

    def test_rejects_invalid_timezone(self) -> None:
        invalid_timezones = [
            "hello",
            "IST",
            "invalid/timezone",
        ]

        for timezone in invalid_timezones:
            with self.subTest(timezone=timezone):
                with self.assertRaises(ValidationError):
                    validate_iana_timezone(timezone)
