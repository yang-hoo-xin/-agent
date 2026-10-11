"""Thin service adapters over the existing query and natural-request owners."""
from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from src.core.query_engine.result_cache import canonical, fingerprint


class BackendError(RuntimeError):
    def __init__(self, code: str, *, safe_retry: bool = False):
        super().__init__(code)
        self.code, self.safe_retry = code, safe_retry


class RedisQueryCache:
    """Same content/version binding as QueryResultCache, with an atomic Redis SET."""

    def __init__(self, client, namespace: str, ttl_seconds: int):
        if type(ttl_seconds) is not int or ttl_seconds <= 0:
            raise ValueError("QUERY_CACHE_TTL_INVALID")
        self.client, self.namespace, self.ttl_seconds = client, namespace, ttl_seconds

    def _key(self, binding):
        return self.namespace + ":query-cache:" + fingerprint(binding)

    def get(self, binding):
        raw = self.client.get(self._key(binding))
        if raw is None:
            return None
        try:
            record = json.loads(raw)
            if (record["version"] == "query_model_cache_v1" and record["binding"] == binding
                    and record["value_sha256"] == fingerprint(record["value"])):
                return deepcopy(record["value"])
        except (ValueError, KeyError, TypeError):
            pass
        return None

    def put(self, binding, value):
        # 为什么要有它：继续由QueryService决定完整结果何时发布；Redis只替换存储，不能缓存半流输出或丢掉来源绑定。
        record = {"version": "query_model_cache_v1", "binding": binding,
                  "value": value, "value_sha256": fingerprint(value)}
        self.client.set(self._key(binding), canonical(record), ex=self.ttl_seconds)


def run_query(payload, config, *, job_id, timeout_seconds, redis_client=None, service_factory=None):
    from src.core.query_engine.query_service import QueryRequest
    from src.core.query_engine.service_factory import create_query_service
    from src.core.settings import QuerySettings, load_settings

    if not isinstance(payload, dict):
        raise BackendError("QUERY_PAYLOAD_REQUIRED")
    payload = dict(payload)
    expected = payload.pop("_settings_sha256", None)
    if not isinstance(expected, str) or hashlib.sha256(Path(config.settings_path).read_bytes()).hexdigest() != expected:
        raise BackendError("QUERY_SETTINGS_BINDING_CHANGED")
    request = QueryRequest.from_dict(payload)
    request = replace(request, request_id=request.request_id or job_id)
    settings = load_settings(config.settings_path)
    if hashlib.sha256(Path(config.settings_path).read_bytes()).hexdigest() != expected:
        raise BackendError("QUERY_SETTINGS_BINDING_CHANGED")
    query = settings.query or QuerySettings()
    # 为什么要有它：服务作业的总限时不可被业务默认180秒放大；缓存绑定、有效性和发布仍走原业务owner。
    query = replace(query, cache_enabled=True, timeout_seconds=min(query.timeout_seconds, timeout_seconds),
                    queue_timeout_seconds=min(query.queue_timeout_seconds, timeout_seconds))
    settings = replace(settings, query=query)
    if redis_client is None:
        import redis
        redis_client = redis.Redis.from_url(config.redis_url, socket_connect_timeout=3, socket_timeout=3)
    try:
        redis_client.ping()
    except Exception as error:
        # This is before retrieval/provider execution; later business failures are not retried here.
        retryable = isinstance(error, (ConnectionError, TimeoutError)) or (
            type(error).__module__.startswith("redis.") and type(error).__name__ in {"ConnectionError", "TimeoutError", "BusyLoadingError"})
        raise BackendError("QUERY_CACHE_UNAVAILABLE_BEFORE_EXECUTION", safe_retry=retryable) from error
    factory = service_factory or create_query_service
    retrieval = getattr(settings, "retrieval", None)
    no_model = (not request.answer and not (query.rewrite_enabled if request.rewrite is None else request.rewrite)
                and not request.rerank and getattr(retrieval, "dense_enabled", None) is False
                and getattr(retrieval, "dense_provider", None) == "disabled")
    # 为什么要有它：纯稀疏查询没有模型参与，可以绑定真实的无模型身份；不能为可能调用模型的路径编造revision来获得缓存命中。
    options = {"model_identity_provider": lambda: {"kind": "no_model_required",
        "scope": "answer_rewrite_dense_rerank_disabled"}} if no_model else {}
    service = factory(settings, collection=request.collection, **options)
    service.cache = RedisQueryCache(redis_client, config.namespace, config.query_cache_ttl)
    return service.query(request).to_dict()  # QueryResponse.evidence is private and never returned.


def _profile(path, description):
    from scripts.dsh_run_request import validate_product_profile

    _, parsed = validate_product_profile(execution_config=str(path), description=description)
    # 为什么要有它：模型位置及源码披露沿用正常产品入口的授权判断，服务层只约束本HTTP入口尚未提供的Apply/游戏效果。
    if (not parsed.defer_approval or not parsed.confirm_isolated_write
            or any(getattr(parsed, name, None) for name in (
                "run_gtfo_runtime", "allow_game_launch", "allow_game_directory_write",
                "runtime_plugin_destination", "resume_initial_findings", "findings_approval_stdin"))):
        raise BackendError("AGENT_SERVICE_PROFILE_EFFECTS_NOT_ALLOWED")
    return parsed


def run_agent(payload, config, *, job_id, routing=None):
    from scripts import dsh_request_routing

    allowed = {"profile_id", "description", "conversation_id", "turn_id", "clarification_for", "_profile_sha256"}
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise BackendError("AGENT_PAYLOAD_FIELDS_INVALID")
    profile_id = payload.get("profile_id")
    if not isinstance(profile_id, str) or profile_id not in config.agent_profiles:
        raise BackendError("AGENT_PROFILE_NOT_REGISTERED")
    description = payload.get("description")
    if not isinstance(description, str) or not description.strip():
        raise BackendError("AGENT_DESCRIPTION_REQUIRED")
    profile = Path(config.agent_profiles[profile_id]).resolve(strict=True)
    raw = profile.read_bytes()
    expected = payload.get("_profile_sha256")
    if not isinstance(expected, str) or hashlib.sha256(raw).hexdigest() != expected:
        raise BackendError("AGENT_PROFILE_BINDING_CHANGED")
    # 为什么要有它：排队时绑定的profile字节在整个路由期间固定；同一内容路径稳定，澄清续接不会因每次attempt换路径而失配。
    directory = Path(config.work_root).resolve() / "profile-bindings"
    directory.mkdir(parents=True, exist_ok=True)
    selected = directory / (fingerprint({"profile_id": profile_id, "sha256": expected}) + ".json")
    if not selected.resolve().is_relative_to(Path(config.work_root).resolve()):
        raise BackendError("AGENT_PROFILE_BINDING_PATH_ESCAPE")
    # 为什么要有它：并发首次使用同一profile时只发布完整字节，不能让另一个worker读到尚未写完的副本。
    temporary = directory / ("." + uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(raw)
        try:
            os.link(temporary, selected)
        except FileExistsError:
            pass
    finally:
        temporary.unlink(missing_ok=True)
    if selected.read_bytes() != raw:
        raise BackendError("AGENT_PROFILE_BINDING_CHANGED")
    _profile(selected, description)
    for field in ("conversation_id", "turn_id", "clarification_for"):
        value = payload.get(field)
        if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 128):
            raise BackendError("AGENT_CONVERSATION_ID_INVALID")
    if payload.get("clarification_for") is not None and not payload.get("conversation_id"):
        raise BackendError("AGENT_CLARIFICATION_CONVERSATION_REQUIRED")
    # 为什么要有它：排队重放须复用原会话/回合，不生成第二个工程；客户端不能传执行器、授权路径或覆盖profile。
    return (routing or dsh_request_routing.run_natural_request)(
        execution_config=str(selected), description=description,
        conversation_id=payload.get("conversation_id") or "service-" + job_id,
        turn_id=payload.get("turn_id") or "job-" + job_id,
        clarification_for=payload.get("clarification_for"))


def public_result(value, secrets=()):
    """Remove provider/private credentials, preserving business statuses and ordinary result fields."""
    hidden = {"raw_response", "api_key", "api_token", "authorization", "password", "secret", "access_token", "redis_url"}
    if isinstance(value, dict):
        return {key: public_result(item, secrets) for key, item in value.items()
                if str(key).casefold() not in hidden}
    if isinstance(value, list):
        return [public_result(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            if isinstance(secret, str) and secret:
                value = value.replace(secret, "[redacted]")
    return value
