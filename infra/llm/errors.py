class LlmError(Exception):
    pass


class LlmResponseError(LlmError):
    def __init__(self, status, body):
        super().__init__("LLM HTTP {}: {}".format(status, body))
        self.status = status
        self.body = body
