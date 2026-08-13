import unittest

from core.sanitizer import DataSanitizer


class DataSanitizerTests(unittest.TestCase):
    def test_clean_line_normalizes_case_and_whitespace(self):
        sanitizer = DataSanitizer()

        self.assertEqual("привіт, світе!", sanitizer.clean_line("Привіт,   Світе!"))


if __name__ == '__main__':
    unittest.main()
