import json
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
