class HttpError(Exception):
    pass


class HttpResponseError(HttpError):
    def __init__(self, status, body):
        super().__init__("HTTP {}: {}".format(status, body))
        self.status = status
        self.body = body
