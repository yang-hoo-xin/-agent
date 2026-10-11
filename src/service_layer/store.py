"""Synchronous Redis jobs with atomic idempotency, leases and bounded recovery."""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any
from uuid import uuid4

from redis import Redis


class IdempotencyConflict(ValueError):
    """The supplied key already identifies different request bytes (HTTP 409)."""

    def __init__(self, job_id: str):
        super().__init__("Idempotency key already belongs to a different request")
        self.job_id = job_id


class QueueFull(RuntimeError):
    """The namespace has reached its nonterminal-job admission limit."""


_TERMINAL = frozenset({"completed", "failed", "timed_out", "indeterminate", "cancelled"})
_MAX_PAYLOAD_BYTES = 128 * 1024
_MAX_RESULT_BYTES = 2 * 1024 * 1024
_MAX_ERROR_BYTES = 64 * 1024

# 为什么要有它：幂等判定、队列修改和租约fence必须在同一次Redis原子执行中完成，不能由并发客户端先读后写。
# 为什么要有它：时间统一到毫秒，避免cjson时间精度和zset分值不同而在正常到期边界误报损坏。
_SCRIPT = r"""
local op, prefix = ARGV[1], ARGV[2]
local args = cjson.decode(ARGV[3])
local retention = tonumber(ARGV[4])
local capacity = tonumber(ARGV[5])
local ready, processing, stats = KEYS[1], KEYS[2], KEYS[3]
local stamp = redis.call('TIME')
local now = (tonumber(stamp[1]) * 1000 + math.floor(tonumber(stamp[2]) / 1000)) / 1000
local function seconds(value) return math.ceil(value * 1000) / 1000 end
local function jobkey(id) return prefix .. 'job:' .. id end
local function idemkey(job) return prefix .. 'idem:' .. job._idempotency_digest end
local function count(name) redis.call('HINCRBY', stats, name, 1) end
local function reply(value) return cjson.encode(value) end
local function readjob(id)
    local raw = redis.call('GET', jobkey(id))
    if not raw then return nil end
    return cjson.decode(raw)
end
local function validindex(job)
    local raw = redis.call('GET', idemkey(job))
    if not raw then return false end
    local index = cjson.decode(raw)
    return index.job_id == job.id and index.request_hash == job._request_hash
end
local function saveactive(job)
    redis.call('SET', jobkey(job.id), cjson.encode(job))
    redis.call('PERSIST', idemkey(job))
end
local function saveterminal(job)
    redis.call('ZREM', ready, job.id)
    redis.call('ZREM', processing, job.id)
    job.lease_token = cjson.null
    job.lease_until = cjson.null
    job.finished_at = now
    redis.call('SET', jobkey(job.id), cjson.encode(job), 'PX', retention)
    redis.call('PEXPIRE', idemkey(job), retention)
    count(job.state)
end
local function fence(job, token)
    return job and job.state == 'running' and job.lease_token == token
        and type(job.lease_until) == 'number' and job.lease_until > now
end
local function closeattempt(job, state, result_json, error_json, cost_unknown)
    local attempt = job.attempts_history[#job.attempts_history]
    attempt.state = state
    attempt.finished_at = now
    attempt.result_json = result_json
    attempt.error_json = error_json
    attempt.cost_unknown = cost_unknown
end

if op == 'submit' then
    local ikey = prefix .. 'idem:' .. args.idempotency_digest
    local prior = redis.call('GET', ikey)
    if prior then
        local index = cjson.decode(prior)
        if index.request_hash ~= args.request_hash then
            count('idempotency_conflicts')
            return reply({code='conflict', job_id=index.job_id})
        end
        local job = readjob(index.job_id)
        if not job or not validindex(job) then return redis.error_reply('JOB_INDEX_INCONSISTENT') end
        count('duplicate_submits')
        return reply({code='existing', job=job})
    end
    if redis.call('ZCARD', ready) + redis.call('ZCARD', processing) >= capacity then
        count('queue_rejections')
        return reply({code='full'})
    end
    if redis.call('EXISTS', jobkey(args.job_id)) ~= 0 then return redis.error_reply('JOB_ID_COLLISION') end
    local job = {id=args.job_id, kind=args.kind, payload_json=args.payload_json, state='queued',
        attempt=0, max_attempts=args.max_attempts, timeout_seconds=args.timeout_seconds,
        created_at=now, started_at=cjson.null, finished_at=cjson.null, available_at=now,
        lease_token=cjson.null, lease_until=cjson.null, attempt_deadline_at=cjson.null,
        worker_id=cjson.null, result_json='null', error_json='null', attempts_history={},
        _request_hash=args.request_hash, _idempotency_digest=args.idempotency_digest}
    redis.call('SET', ikey, reply({job_id=job.id,request_hash=args.request_hash}))
    saveactive(job)
    redis.call('ZADD', ready, now, job.id)
    count('submitted')
    return reply({code='created', job=job})
elseif op == 'claim' then
    local ids = redis.call('ZRANGEBYSCORE', ready, '-inf', now, 'LIMIT', 0, 1)
    if #ids == 0 then return reply({code='empty'}) end
    local job = readjob(ids[1])
    if not job or job.state ~= 'queued' or not validindex(job) or job.attempt >= job.max_attempts then
        return redis.error_reply('READY_JOB_INCONSISTENT')
    end
    job.attempt = job.attempt + 1
    job.state = 'running'
    job.started_at = now
    job.attempt_deadline_at = now + seconds(job.timeout_seconds)
    job.lease_until = now + seconds(args.lease_seconds)
    job.lease_token = args.lease_token
    job.worker_id = args.worker_id
    table.insert(job.attempts_history, {attempt=job.attempt, state='running', started_at=now,
        finished_at=cjson.null, lease_token=args.lease_token, worker_id=args.worker_id,
        result_json='null', error_json='null', cost_unknown=cjson.null})
    redis.call('ZREM', ready, job.id)
    redis.call('ZADD', processing, job.lease_until, job.id)
    saveactive(job)
    count('claimed')
    return reply({code='claimed',job=job})
elseif op == 'heartbeat' or op == 'finish' or op == 'retry' then
    local job = readjob(args.job_id)
    if not fence(job,args.lease_token) then
        count('late_writes_rejected')
        return reply({code='rejected'})
    end
    if not validindex(job) then return redis.error_reply('RUNNING_JOB_INDEX_INCONSISTENT') end
    if op == 'heartbeat' then
        job.lease_until = now + seconds(args.lease_seconds)
        redis.call('ZADD',processing,job.lease_until,job.id)
        saveactive(job)
        return reply({code='accepted'})
    elseif op == 'finish' then
        job.state=args.state
        job.result_json=args.result_json
        job.error_json=args.error_json
        closeattempt(job,args.state,args.result_json,args.error_json,
            args.state == 'indeterminate' and true or cjson.null)
        saveterminal(job)
        return reply({code='accepted'})
    else
        if job.kind ~= 'query' then return reply({code='rejected'}) end
        job.error_json=args.error_json
        redis.call('ZREM',processing,job.id)
        if job.attempt >= job.max_attempts then
            job.state='failed'
            closeattempt(job,'failed','null',args.error_json,cjson.null)
            saveterminal(job)
        else
            closeattempt(job,'retry_scheduled','null',args.error_json,cjson.null)
            job.state='queued'
            job.lease_token=cjson.null
            job.lease_until=cjson.null
            job.available_at=now+seconds(args.delay_seconds)
            redis.call('ZADD',ready,job.available_at,job.id)
            saveactive(job)
            count('retries')
        end
        return reply({code='accepted'})
    end
elseif op == 'recover' then
    local ids = redis.call('ZRANGEBYSCORE',processing,'-inf',now,'LIMIT',0,100)
    local jobs={}
    for _,id in ipairs(ids) do
        local job=readjob(id)
        if not job or job.state~='running' or not validindex(job) or job.lease_until>now then
            return redis.error_reply('EXPIRED_JOB_INCONSISTENT')
        end
        table.insert(jobs,job)
    end
    local result={expired=0,queries_requeued=0,queries_exhausted=0,agents_indeterminate=0}
    for _,job in ipairs(jobs) do
        local error_json=reply({code='lease_expired',cost_unknown=true,
            prior_error_json=job.error_json,reason='Worker lease expired; previous execution cost/effects may be unknown'})
        closeattempt(job,'lease_expired','null',error_json,true)
        job.error_json=error_json
        job.lease_token=cjson.null
        job.lease_until=cjson.null
        redis.call('ZREM',processing,job.id)
        if job.kind=='query' and job.attempt<job.max_attempts then
            job.state='queued'
            job.available_at=now
            redis.call('ZADD',ready,now,job.id)
            saveactive(job)
            result.queries_requeued=result.queries_requeued+1
            count('retries')
        else
            job.state=job.kind=='agent' and 'indeterminate' or 'failed'
            saveterminal(job)
            if job.kind=='agent' then result.agents_indeterminate=result.agents_indeterminate+1
            else result.queries_exhausted=result.queries_exhausted+1 end
        end
        result.expired=result.expired+1
        count('expired_leases')
    end
    result.remaining_expired=redis.call('ZCOUNT',processing,'-inf',now)
    return reply(result)
elseif op == 'rate_limit' then
    local key=prefix .. 'rate:' .. args.identity_digest
    local value=redis.call('INCR',key)
    if value==1 then redis.call('PEXPIRE',key,args.window_ms) end
    local ttl=redis.call('PTTL',key)
    if ttl<0 then return redis.error_reply('RATE_LIMIT_EXPIRATION_MISSING') end
    return reply({allowed=value<=args.limit,retry_after=value<=args.limit and 0 or ttl/1000})
elseif op == 'metrics' then
    local raw=redis.call('HGETALL',stats)
    local counters={}
    for i=1,#raw,2 do counters[raw[i]]=tonumber(raw[i+1]) end
    local queued=redis.call('ZCARD',ready)
    local running=redis.call('ZCARD',processing)
    return reply({queued=queued,running=running,pending=queued+running,
        ready=redis.call('ZCOUNT',ready,'-inf',now),expired_leases=redis.call('ZCOUNT',processing,'-inf',now),
        counters=counters,timestamp=now})
end
return redis.error_reply('UNKNOWN_JOB_OPERATION')
"""


def _positive(value: Any, name: str, maximum: float, *, zero: bool = False) -> float:
    if (type(value) not in (int, float) or value < 0 or (not zero and value == 0)
            or value > maximum or not math.isfinite(value)):
        raise ValueError(f"{name} must be a finite {'nonnegative' if zero else 'positive'} number <= {maximum}")
    return float(value)


def _integer(value: Any, name: str, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be an integer between 1 and {maximum}")
    return value


def _text(value: Any, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > maximum:
        raise ValueError(f"{name} must be nonempty UTF-8 text of at most {maximum} bytes")
    return value


def _json(value: Any, maximum: int) -> str:
    def validate(item: Any) -> None:
        if isinstance(item, dict):
            if any(type(key) is not str for key in item):
                raise ValueError("JSON object keys must be strings")
            for child in item.values():
                validate(child)
        elif isinstance(item, list):
            for child in item:
                validate(child)
        elif item is not None and type(item) not in (str, bool, int, float):
            raise ValueError("Only JSON values are accepted")
    try:
        validate(value)
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(text.encode("utf-8")) > maximum:
            raise ValueError("JSON value exceeds UTF-8 size limit")
        return text
    except (TypeError, RecursionError, OverflowError) as exc:
        raise ValueError("Unsupported JSON value") from exc


def _job(value: dict) -> dict:
    result = {key: item for key, item in value.items() if not key.startswith("_")}
    # 为什么要有它：Redis cjson会把空数组重编码为空对象；业务JSON按原始字符串保存，才能保留payload/result/error的完整类型和值。
    for key in ("payload", "result", "error"):
        result[key] = json.loads(result.pop(key + "_json"))
    history = result["attempts_history"]
    if history == {}:
        history = []
    for attempt in history:
        for key in ("result", "error"):
            attempt[key] = json.loads(attempt.pop(key + "_json"))
        for key in ("started_at", "finished_at"):
            if attempt.get(key) is not None:
                attempt[key] = float(attempt[key])
    result["attempts_history"] = history
    for key in ("created_at", "started_at", "finished_at", "available_at", "lease_until", "attempt_deadline_at"):
        if result.get(key) is not None:
            result[key] = float(result[key])
    return result


class RedisJobStore:
    """Single Redis deployment; max_pending bounds queued plus running jobs.

    为什么要有它：活动作业和幂等映射不设TTL；仅终态按保留期一起到期，排队或长任务不能悄悄变成可重复的新任务。
    """

    def __init__(self, client: Redis, namespace: str = "agent-service",
                 retention_seconds: float = 86400, max_pending: int = 1000):
        self.client = client
        self.namespace = _text(namespace, "namespace", 256)
        self.retention_seconds = _positive(retention_seconds, "retention_seconds", 365 * 86400)
        self.max_pending = _integer(max_pending, "max_pending", 100000)
        # 为什么要有它：命名空间、限流身份和幂等标识都只以摘要进入Redis键，键名不暴露问题文本或凭据。
        digest = hashlib.sha256(namespace.encode("utf-8")).hexdigest()
        self.key_prefix = "agent-service:{" + digest + "}:"
        self._keys = [self.key_prefix + name for name in ("ready", "processing", "metrics")]
        self._script = client.register_script(_SCRIPT)

    def _call(self, operation: str, arguments: dict) -> dict:
        value = self._script(keys=self._keys, args=[operation, self.key_prefix,
            json.dumps(arguments, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
            max(1, math.ceil(self.retention_seconds * 1000)), self.max_pending])
        return json.loads(value)

    @staticmethod
    def _id(job_id: str) -> str:
        if not isinstance(job_id, str) or re.fullmatch(r"[0-9a-f]{32}", job_id) is None:
            raise ValueError("Invalid job ID")
        return job_id

    @staticmethod
    def _token(token: str) -> str:
        return _text(token, "lease_token", 256)

    def submit(self, kind: str, payload: dict, idempotency_key: str,
               timeout_seconds: float, max_attempts: int) -> tuple[dict, bool]:
        if not isinstance(kind, str) or kind not in {"query", "agent"} or not isinstance(payload, dict):
            raise ValueError("kind must be query or agent and payload must be an object")
        key = _text(idempotency_key, "idempotency_key", 512)
        timeout = _positive(timeout_seconds, "timeout_seconds", 86400)
        attempts = _integer(max_attempts, "max_attempts", 10)
        body = _json(payload, _MAX_PAYLOAD_BYTES)
        canonical = _json({"kind": kind, "payload": payload, "timeout_seconds": timeout,
                           "max_attempts": attempts}, _MAX_PAYLOAD_BYTES + 1024)
        answer = self._call("submit", {"job_id": uuid4().hex, "kind": kind, "payload_json": body,
            "timeout_seconds": timeout, "max_attempts": attempts,
            "idempotency_digest": hashlib.sha256(key.encode("utf-8")).hexdigest(),
            "request_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest()})
        if answer["code"] == "conflict":
            raise IdempotencyConflict(answer["job_id"])
        if answer["code"] == "full":
            raise QueueFull("Nonterminal job capacity reached")
        return _job(answer["job"]), answer["code"] == "created"

    def get(self, job_id: str) -> dict | None:
        raw = self.client.get(self.key_prefix + "job:" + self._id(job_id))
        return None if raw is None else _job(json.loads(raw))

    def claim(self, worker_id: str, lease_seconds: float) -> dict | None:
        # 为什么要有它：worker负责执行timeout并收尾；独立租约让仍持有所有权的worker能记录timed_out，同时拒绝真正失租的迟到结果。
        answer = self._call("claim", {"worker_id": _text(worker_id, "worker_id", 256),
            "lease_seconds": _positive(lease_seconds, "lease_seconds", 3600), "lease_token": uuid4().hex})
        return None if answer["code"] == "empty" else _job(answer["job"])

    def heartbeat(self, job_id: str, lease_token: str, lease_seconds: float) -> bool:
        return self._call("heartbeat", {"job_id": self._id(job_id), "lease_token": self._token(lease_token),
            "lease_seconds": _positive(lease_seconds, "lease_seconds", 3600)})["code"] == "accepted"

    def finish(self, job_id: str, lease_token: str, state: str,
               result: Any = None, error: Any = None) -> bool:
        if not isinstance(state, str) or state not in _TERMINAL:
            raise ValueError("Unsupported terminal state")
        return self._call("finish", {"job_id": self._id(job_id), "lease_token": self._token(lease_token),
            "state": state, "result_json": _json(result, _MAX_RESULT_BYTES),
            "error_json": _json(error, _MAX_ERROR_BYTES)})["code"] == "accepted"

    def retry(self, job_id: str, lease_token: str, error: Any, delay_seconds: float) -> bool:
        # 为什么要有它：只有只读query可按次数重试；Agent可能已写文件，未知副作用必须由owner核对而非盲重跑。
        return self._call("retry", {"job_id": self._id(job_id), "lease_token": self._token(lease_token),
            "error_json": _json(error, _MAX_ERROR_BYTES),
            "delay_seconds": _positive(delay_seconds, "delay_seconds", 86400, zero=True)})["code"] == "accepted"

    def recover_expired(self) -> dict:
        """Recover at most 100 expired leases per call; retain unknown attempt costs."""
        return self._call("recover", {})

    def rate_limit(self, identity: str, limit: int, window_seconds: float) -> tuple[bool, float]:
        who = _text(identity, "identity", 1024)
        answer = self._call("rate_limit", {"identity_digest": hashlib.sha256(who.encode("utf-8")).hexdigest(),
            "limit": _integer(limit, "limit", 1000000),
            "window_ms": max(1, math.ceil(_positive(window_seconds, "window_seconds", 86400) * 1000))})
        return answer["allowed"], float(answer["retry_after"])

    def metrics(self) -> dict:
        answer = self._call("metrics", {})
        answer["timestamp"] = float(answer["timestamp"])
        answer["counters_scope"] = "Cumulative namespace events, including expired retained terminal records"
        answer["pending_scope"] = "Queued plus running; no terminal records counted toward admission capacity"
        return answer
