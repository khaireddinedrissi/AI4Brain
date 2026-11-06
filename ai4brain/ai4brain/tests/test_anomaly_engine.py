"""Regression tests for the six CISTAC challenge anomalies."""
import unittest
import anomaly_engine


class AnomalyEngineChecks(unittest.TestCase):
    def test_button_masher_flags_fast_inaccurate_round(self):
        result = anomaly_engine.detect_button_masher([0.2, 0.3, 0.4, 0.5], 35)
        self.assertTrue(result["detected"])
        self.assertEqual(result["status"], "high_uncertainty")

    def test_button_masher_does_not_flag_fast_accurate_round(self):
        self.assertFalse(anomaly_engine.detect_button_masher([0.2, 0.3, 0.4], 95)["detected"])

    def test_plateau_detected_and_short_history_is_not_overclaimed(self):
        self.assertTrue(anomaly_engine.detect_plateau([70, 71, 70, 70])["detected"])
        self.assertEqual(anomaly_engine.detect_plateau([70, 70])["status"], "insufficient_data")

    def test_why_audit_exposes_numeric_evidence(self):
        result = anomaly_engine.explain_recommendation({"WM": 40, "AT": 90, "PS": 60}, "WM")
        self.assertTrue(result["explainable"])
        self.assertEqual(result["observed_score"], 40)
        self.assertIn("AT", result["evidence"])

    def test_pushback_is_acknowledged_not_dismissed(self):
        result = anomaly_engine.detect_pushback("I disagree, I was distracted")
        self.assertTrue(result["detected"])
        self.assertIn("uncertain", result["handling"])

    def test_future_prediction_uses_uncertainty_language(self):
        result = anomaly_engine.guard_prediction("What exactly will my cognitive score be next month?")
        self.assertTrue(result["guarded"])
        self.assertIn("estimate", result["response"])
        self.assertIn("range", result["response"])

    def test_asymmetric_profile_creates_split_plan(self):
        result = anomaly_engine.detect_asymmetry({"WM": 95, "AT": 20, "PS": 60, "SP": 50})
        self.assertTrue(result["detected"])
        self.assertEqual(result["plan"], {"focus": "AT", "maintenance": "WM"})

    def test_analyze_returns_all_six_checks(self):
        result = anomaly_engine.analyze({"response_times": [0.1, 0.2, 0.3], "accuracy": 20,
            "score_history": [50, 50, 51, 50], "dimension_scores": {"WM": 90, "AT": 20},
            "recommended_dimension": "AT", "user_message": "I disagree; I was distracted"})
        self.assertEqual(len([k for k in result if k != "disclaimer"]), 6)


if __name__ == "__main__":
    unittest.main()
