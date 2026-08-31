import unittest
from unittest.mock import Mock, patch

import requests

import api_client


class NormalizeApiKeyTests(unittest.TestCase):
    def test_removes_copied_header_syntax(self):
        self.assertEqual(api_client._normalize_api_key(" X-API-KEY: 'key-value' "), "key-value")
        copied_header = "Authorization" + ": " + "Bearer " + "key-value"
        self.assertEqual(api_client._normalize_api_key(copied_header), "key-value")


class RequestTests(unittest.TestCase):
    @patch("api_client.requests.request")
    def test_invalid_key_response_is_actionable(self, request):
        response = Mock(status_code=422)
        response.json.return_value = {"detail": "Invalid authorization key"}
        response.raise_for_status.side_effect = requests.HTTPError(
            "422 Client Error", response=response
        )
        request.return_value = response

        with self.assertRaisesRegex(
            requests.HTTPError, "Enter a valid, active Rendi API key"
        ):
            api_client._request("POST", "/v1/files/init-upload", "invalid-key")

        self.assertEqual(request.call_args.kwargs["headers"]["X-API-KEY"], "invalid-key")


if __name__ == "__main__":
    unittest.main()
