"""Redact configured secret values at MCP output and logging boundaries."""
import logging
import os
import re


class Redactor:
    def __init__(self, secrets=()):
        self.secrets = tuple(sorted({value for value in secrets if isinstance(value, str) and len(value) >= 8}, key=len, reverse=True))

    @classmethod
    def configured(cls, settings=None):
        values = [value for key, value in os.environ.items()
                  if re.search(r"(?:KEY|TOKEN|SECRET|PASSWORD|CANARY)$", key, re.I)]
        if settings is not None:
            values.extend(getattr(getattr(settings, key, None), "api_key", None)
                          for key in ("llm", "embedding", "vision_llm"))
        return cls(values)

    def __call__(self, value):
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, "[REDACTED]")
            return re.sub(r"(?i)((?:api[_-]?key|authorization|password|secret|token)\s*[:=]\s*)([^\s,;\"'}]+)",
                          r"\1[REDACTED]", value)
        if isinstance(value, dict):
            return {self(str(key)): self(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self(item) for item in value]
        return value


def install_log_redaction(redactor):
    original = logging.getLogRecordFactory()
    def factory(*args, **kwargs):
        record = original(*args, **kwargs)
        record.msg = redactor(record.getMessage())
        record.args = ()
        if record.exc_info:
            record.exc_text = redactor(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return record
    logging.setLogRecordFactory(factory)
    return original


class RedactingTraceCollector:
    def __init__(self, collector, redactor):
        self.collector, self.redactor = collector, redactor

    def collect(self, trace):
        redactor = self.redactor
        class View:
            trace_id = trace.trace_id
            @property
            def finished_at(self):
                return trace.finished_at
            def finish(self):
                trace.finish()
            def to_dict(self):
                return redactor(trace.to_dict())
        self.collector.collect(View())


class RedactingTextStream:
    def __init__(self, stream, redactor):
        self.stream, self.redactor = stream, redactor

    def write(self, value):
        return self.stream.write(self.redactor(value))

    def __getattr__(self, name):
        return getattr(self.stream, name)
