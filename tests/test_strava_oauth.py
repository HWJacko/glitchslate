from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path

from scripts.strava_oauth import update_env_value


class StravaOAuthTests(unittest.TestCase):
    def test_update_env_value_protects_credentials_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("STRAVA_CLIENT_ID=client\n", encoding="utf-8")
            path.chmod(0o644)

            update_env_value(path, "STRAVA_REFRESH_TOKEN", "refresh")

            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertIn("STRAVA_REFRESH_TOKEN=refresh", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
