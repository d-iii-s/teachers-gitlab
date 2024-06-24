
import json
import logging
import re

import gitlab
import responses

class MockedGitLabApi:
    def __init__(self, rsps):
        self.base_url = "http://localhost/"
        self.unknown_urls = []
        rsps.start()

        self.responses = rsps
        self.logger = logging.getLogger("mocked-api")

    def report_unknown(self):
        def dumping_callback(req):
            log_line = f"{req.method} {req.url}"
            logging.getLogger('DUMPER').error("URL not mocked: %s", log_line)
            self.unknown_urls.append(log_line)
            return (404, {}, json.dumps({"error": "not implemented"}))

        methods = [responses.GET, responses.POST, responses.DELETE]
        for m in methods:
            self.responses.add_callback(
                m,
                re.compile("http://localhost/api/v4/.*"),
                callback=dumping_callback,
            )
        for i, _ in enumerate(methods):
            self.responses.registered()[-(i + 1)]._calls.add_call(None)

    def shutdown(self):
        if self.unknown_urls:
            unknowns = ', '.join(self.unknown_urls)
            raise Exception(f"Following URLs were not mocked: {unknowns}.")

    def make_api_url_(self, suffix):
        return self.base_url + "api/v4/" + suffix

    def escape_path_in_url(self, path_with_namespace):
        import urllib.parse
        return urllib.parse.quote_plus(path_with_namespace)

    def get_python_gitlab(self):
        return gitlab.Gitlab(self.base_url, oauth_token="mock_token")

    def on_api_get(self, url, response_json, helper=False, *args, **kwargs):
        full_url = self.make_api_url_(url)

        kwargs['json'] = response_json

        if not helper:
            return self.responses.get(full_url, *args, **kwargs)

        for _ in [0, 1, 2, 3, 4, 5]:
            result = self.responses.get(full_url, *args, **kwargs)
            result._calls.add_call(None)

    def on_api_post(self, url, request_json, response_json, *args, **kwargs):
        kwargs['body'] = json.dumps(response_json)
        kwargs['match'] = [
            responses.matchers.json_params_matcher(request_json)
        ]
        kwargs['content_type'] = 'application/json'

        return self.responses.post(
            self.make_api_url_(url),
            *args,
            **kwargs,
        )

    def on_api_delete(self, url, *args, **kwargs):
        return self.responses.delete(
            self.make_api_url_(url),
            *args,
            **kwargs,
        )
