import os
import tempfile
import unittest

from config import settings
from core.database import DatabaseManager


class TestDatabaseIsolation(unittest.TestCase):
    def test_db_path_follows_user_data_dir(self):
        old = settings.USER_DATA_DIR
        tmp = tempfile.TemporaryDirectory(prefix="jian_db_iso_")
        settings.USER_DATA_DIR = tmp.name
        try:
            db = DatabaseManager()
            self.assertEqual(os.path.dirname(db.db_path), tmp.name)
            self.assertTrue(os.path.exists(db.db_path))
        finally:
            settings.USER_DATA_DIR = old
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
