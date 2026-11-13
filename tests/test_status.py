import unittest

from stacksense.status import decide

INFO = {"code": "X", "severity": "info", "message": "m", "fields": []}
WARN = {"code": "Y", "severity": "warning", "message": "m", "fields": []}
CRIT = {"code": "Z", "severity": "critical", "message": "m", "fields": []}
ERR = [{"field": "team.size", "message": "Required field is missing."}]


class StatusTruthTable(unittest.TestCase):
    def test_stat_01_errors_win_over_everything(self):
        self.assertEqual(decide(ERR, [CRIT], ["budget"], False), "invalid_input")

    def test_stat_02_errors_alone(self):
        self.assertEqual(decide(ERR, [], [], True), "invalid_input")

    def test_stat_03_infeasible(self):
        self.assertEqual(decide([], [CRIT], [], False), "infeasible")

    def test_stat_04_infeasible_without_warnings(self):
        self.assertEqual(decide([], [], ["budget"], False), "infeasible")

    def test_stat_05_relaxed_soft_constraint(self):
        self.assertEqual(decide([], [], ["budget"], True), "ok_with_warnings")

    def test_stat_06_warning_severity(self):
        self.assertEqual(decide([], [INFO, WARN], [], True), "ok_with_warnings")

    def test_stat_07_critical_severity(self):
        self.assertEqual(decide([], [CRIT], [], True), "ok_with_warnings")

    def test_stat_08_info_only_or_nothing_is_ok(self):
        self.assertEqual(decide([], [INFO], [], True), "ok")
        self.assertEqual(decide([], [], [], True), "ok")
        self.assertEqual(decide(None, None, None, True), "ok")


if __name__ == "__main__":
    unittest.main()
