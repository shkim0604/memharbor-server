import json
import os
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from api.views import reviews


class ReviewsApiTest(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _attach_uid(self, request, uid="u1"):
        request.firebase_uid = uid
        return request

    def test_context_requires_call_id(self):
        req = self._attach_uid(self.factory.get("/api/reviews/context"))
        res = reviews.reviews_context(req)
        body = json.loads(res.content)
        self.assertEqual(res.status_code, 400)
        self.assertFalse(body["ok"])
        self.assertEqual(body["code"], "missing_call_id")

    def test_my_requires_auth(self):
        req = self.factory.get("/api/reviews/my", {"call_id": "c1"})
        res = reviews.reviews_my(req)
        body = json.loads(res.content)
        self.assertEqual(res.status_code, 401)
        self.assertFalse(body["ok"])
        self.assertEqual(body["code"], "unauthorized")

    def test_upsert_rejects_unknown_fields(self):
        req = self._attach_uid(
            self.factory.post(
                "/api/reviews/upsert",
                data=json.dumps({"callId": "c1", "unknown": "x"}),
                content_type="application/json",
            )
        )
        res = reviews.reviews_upsert(req)
        body = json.loads(res.content)
        self.assertEqual(res.status_code, 400)
        self.assertFalse(body["ok"])
        self.assertEqual(body["code"], "invalid_fields")

    def test_upsert_rejects_missing_call_id(self):
        req = self._attach_uid(
            self.factory.post(
                "/api/reviews/upsert",
                data=json.dumps({"listeningScore": 4}),
                content_type="application/json",
            )
        )
        res = reviews.reviews_upsert(req)
        body = json.loads(res.content)
        self.assertEqual(res.status_code, 400)
        self.assertFalse(body["ok"])
        self.assertEqual(body["code"], "missing_call_id")

    def test_upsert_rejects_invalid_json(self):
        req = self._attach_uid(
            self.factory.post(
                "/api/reviews/upsert",
                data="{invalid-json",
                content_type="application/json",
            )
        )
        res = reviews.reviews_upsert(req)
        body = json.loads(res.content)
        self.assertEqual(res.status_code, 400)
        self.assertFalse(body["ok"])
        self.assertEqual(body["code"], "invalid_json")

    @patch("api.views.reviews.firestore_service")
    def test_context_firestore_unavailable(self, mocked_service):
        mocked_service.db = None
        req = self._attach_uid(self.factory.get("/api/reviews/context", {"call_id": "c1"}))
        res = reviews.reviews_context(req)
        body = json.loads(res.content)
        self.assertEqual(res.status_code, 500)
        self.assertFalse(body["ok"])
        self.assertEqual(body["code"], "firestore_unavailable")

    def test_selected_topic_ref(self):
        topic_type, topic_id = reviews._selected_topic_ref(
            {
                "selectedTopicType": "residence",
                "selectedResidenceId": "res_1",
                "selectedTopicId": "ignored",
            }
        )
        self.assertEqual(topic_type, "residence")
        self.assertEqual(topic_id, "res_1")

    @patch("api.views.reviews._get_restricted_questions_visible_date_cached")
    def test_reviews_config_returns_date(self, mocked_get_date):
        mocked_get_date.return_value = "2026-03-10"
        req = self._attach_uid(self.factory.get("/api/reviews/config"))
        res = reviews.reviews_config(req)
        body = json.loads(res.content)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(body.get("restrictedQuestionsVisibleDateEt"), "2026-03-10")

    @patch("api.views.reviews._get_restricted_questions_visible_date_cached")
    def test_reviews_config_returns_empty_when_missing(self, mocked_get_date):
        mocked_get_date.return_value = None
        req = self._attach_uid(self.factory.get("/api/reviews/config"))
        res = reviews.reviews_config(req)
        body = json.loads(res.content)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(body, {})

    def test_parse_yyyy_mm_dd_validation(self):
        self.assertIsNotNone(reviews._parse_yyyy_mm_dd("2026-03-10"))
        self.assertIsNone(reviews._parse_yyyy_mm_dd("2026/03/10"))
        self.assertIsNone(reviews._parse_yyyy_mm_dd("2026-3-10"))

    def test_is_restricted_questions_visible_today_et_invalid_env(self):
        with patch.dict(os.environ, {"REVIEWS_RESTRICTED_QUESTIONS_VISIBLE_DATE_ET": "invalid"}, clear=False):
            reviews._invalidate_reviews_config_cache()
            self.assertFalse(reviews._is_restricted_questions_visible_today_et())
