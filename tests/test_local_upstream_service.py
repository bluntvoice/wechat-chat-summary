from __future__ import annotations

import unittest
from pathlib import Path

from group_insight.local_upstream_service import (
    LocalUpstreamServiceError,
    derive_upstream_output_dir,
)


class LocalUpstreamServiceTests(unittest.TestCase):
    def test_output_dir_is_derived_from_selected_account(self):
        payload = {
            "default_account": "account-a",
            "accountInfos": [
                {"account": "account-a", "accountDir": "F:/data/wcda/databases/account-a"},
                {"account": "account-b", "accountDir": "F:/data/wcda/databases/account-b"},
            ],
        }
        self.assertEqual(
            derive_upstream_output_dir(payload, "account-b"),
            Path("F:/data/wcda"),
        )

    def test_output_dir_requires_standard_databases_layout(self):
        with self.assertRaises(LocalUpstreamServiceError):
            derive_upstream_output_dir(
                {"accountInfos": [{"account": "account-a", "accountDir": "F:/unexpected/account-a"}]},
                "account-a",
            )


if __name__ == "__main__":
    unittest.main()
