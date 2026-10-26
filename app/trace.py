"""OpenTelemetry tracing seam for the planning pipeline.

Every run gets a short ``run_id``. Spans (``pipeline.run``, ``node.*``,
``mcp.*``, ``rag.retrieve``, ``validation``, ``gen_ai.chat``) are emitted to the
configured OpenTelemetry collector when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set
(e.g. the local Phoenix container); otherwise the tracer is a cheap no-op, so
tests, the headless demo and CI never need a backend.

The same run also feeds a small in-memory :class:`RunTrace` collector that the
Streamlit UI reads to render the audit section of the Trace tab. Console logs
stay human-readable text; full LLM prompts go to spans (visible in Phoenix),
and console logging shows the same prompts at INFO, bounded by
``LLM_LOG_PAYLOAD_LIMIT`` so one runaway prompt cannot flood the console.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

from langchain_core.callbacks import BaseCallbackHandler
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, Status, StatusCode

from app.settings import get_settings

logger = logging.getLogger(__name__)

#: Console log truncation for individual LLM messages. Applied at INFO and
#: above, so a single oversized prompt can never flood the console.
LLM_LOG_PAYLOAD_LIMIT = 2000
#: Hard cap for message content attached to spans, so one runaway response
#: cannot flood the trace backend. Full prompts stay well under this.
SPAN_PAYLOAD_LIMIT = 50_000
SERVICE_NAME = "termina-companion"
#: OpenInference attributes the Phoenix dashboard reads for its Kind and
#: Input/Output columns (Status comes from the OTel status code instead).
SPAN_KIND_ATTR = "openinference.span.kind"
INPUT_VALUE_ATTR = "input.value"
OUTPUT_VALUE_ATTR = "output.value"
#: Tell Phoenix the payload is JSON so it pretty-prints instead of showing a
#: raw string. Set only when the payload is not already a plain string.
INPUT_MIME_TYPE_ATTR = "input.mime_type"
OUTPUT_MIME_TYPE_ATTR = "output.mime_type"
JSON_MIME_TYPE = "application/json"

_run_id: ContextVar[str] = ContextVar("termina_run_id", default="")
_span_id: ContextVar[str] = ContextVar("termina_span_id", default="")
_trace_id: ContextVar[str] = ContextVar("termina_trace_id", default="")
_setup_done = False
_exporter_active = False


@dataclass
class RunTrace:
    """In-memory audit record of one planning run, rendered by the UI."""

    run_id: str
    goal: str = ""
    # OTel ids of the pipeline.run root span (hex, no 0x), so an evaluation
    # report can be linked back to this run's trace in Phoenix.
    span_id: str = ""
    trace_id: str = ""
    started_at: float = field(default_factory=time.time)
    nodes: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)

    def add_node(self, name: str, duration_s: float, status: str, detail: str = "") -> None:
        """Record one finished graph node."""
        self.nodes.append(
            {"name": name, "duration_s": duration_s, "status": status, "detail": detail}
        )

    def add_error(self, source: str, message: str, detail: str = "") -> None:
        """Record one failed tool, LLM call or pipeline step."""
        self.errors.append({"source": source, "message": message, "detail": detail})

    def duration_s(self) -> float:
        """Wall-clock seconds since the run started."""
        return time.time() - self.started_at


_current: RunTrace | None = None


def _otlp_traces_url(endpoint: str) -> str:
    """Resolve the base OTLP endpoint to the full OTLP/HTTP traces URL.

    ``OTEL_EXPORTER_OTLP_ENDPOINT`` is a **base** URL (standard OTel
    semantics), but the exporter's constructor ``endpoint`` argument is a
    full signal URL used as-is, with no path appended. Phoenix serves the
    OTLP/HTTP receiver on ``:6006`` at ``/v1/traces`` (same port as the web
    UI; it has no ``:4318`` listener), so the signal path is appended here.

    args:
        endpoint (str): base endpoint, e.g. ``http://localhost:6006``.

    returns:
        str: the full traces URL, e.g. ``http://localhost:6006/v1/traces``.
    """
    base = endpoint.strip().removesuffix("/")
    if base.endswith("/v1/traces"):
        return base
    return f"{base}/v1/traces"


def setup_tracing() -> None:
    """Configure the global TracerProvider once.

    Reads ``OTEL_EXPORTER_OTLP_ENDPOINT``: when set, spans are exported there
    over OTLP/HTTP (e.g. ``http://localhost:6006`` for the local Phoenix
    container, whose receiver shares the UI port); when unset, a no-op
    provider is installed so span creation stays cheap and offline runs never
    open a connection.

    args:
        (none)

    returns:
        None: side-effect on the global OpenTelemetry provider only.
    """
    global _setup_done, _exporter_active
    if _setup_done:
        return
    _setup_done = True

    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
    endpoint = get_settings().otel_exporter_otlp_endpoint
    if endpoint:
        traces_url = _otlp_traces_url(endpoint)
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=traces_url, timeout=10))
        )
        _exporter_active = True
        logger.info("Tracing: exporting OTLP spans to %s", traces_url)
    else:
        logger.info("Tracing: no OTEL_EXPORTER_OTLP_ENDPOINT configured — spans are no-op")
    trace.set_tracer_provider(provider)


def exporter_active() -> bool:
    """Whether an OTLP exporter was configured by :func:`setup_tracing`."""
    return _exporter_active


def flush_spans(timeout_millis: int = 5000) -> None:
    """Force pending spans to the exporter, so a backend already has the run.

    Used before posting span annotations: the BatchSpanProcessor queues spans
    asynchronously, and an annotation for a trace Phoenix has not ingested yet
    would be orphaned. No-op outside a configured provider.

    args:
        timeout_millis (int, default 5000): how long to wait for the flush.

    returns:
        None: best-effort side effect; failures are logged at debug only.
    """
    provider = trace.get_tracer_provider()
    force_flush = getattr(provider, "force_flush", None)
    if not callable(force_flush):
        return
    try:
        force_flush(timeout_millis=timeout_millis)
    except Exception:  # noqa: BLE001 - a slow backend must not break the run
        logger.debug("Span flush did not complete", exc_info=True)


def get_tracer(name: str = SERVICE_NAME):
    """Return an OTel tracer bound to the configured provider."""
    return trace.get_tracer(name)


def current_run_id() -> str:
    """The active run's id, or an empty string outside a run."""
    return _run_id.get()


def current_span_ids() -> tuple[str, str]:
    """The active run's root-span ids as ``(span_id, trace_id)``.

    Both are lowercase hex without a ``0x`` prefix (the format Phoenix and
    OpenTelemetry use), or empty strings outside a run. Kept in ContextVars
    rather than read off the shared :class:`RunTrace`, so a background
    evaluation sweep and a UI run in different threads cannot mix them up.

    args:
        (none)

    returns:
        tuple[str, str]: the span and trace ids of the current run.
    """
    return _span_id.get(), _trace_id.get()


def current_run() -> RunTrace | None:
    """The in-memory audit record of the latest run, if any."""
    return _current


def begin_run(goal: str = "") -> RunTrace:
    """Open a new :class:`RunTrace` and make its id current for this context."""
    global _current
    run = RunTrace(run_id=uuid.uuid4().hex[:8], goal=goal)
    _current = run
    _run_id.set(run.run_id)
    # Cleared here so a run that dies before its span exists can never report
    # the previous run's span ids; pipeline_span fills them after start_span.
    _span_id.set("")
    _trace_id.set("")
    logger.info("Run %s started — goal: %s", run.run_id, goal or "(none)")
    return run


@contextmanager
def pipeline_span(goal: str = "") -> Iterator[RunTrace]:
    """Wrap a whole planning run: run id, root span and error bookkeeping.

    The root span carries ``CHAIN`` kind, the goal as ``input.value`` and a
    compact run summary (node statuses, error sources) as ``output.value``,
    with an explicit OK/ERROR status for the backend's Status column.

    args:
        goal (str, default ""): the player goal, stored on the run and set as
            the root span input attribute.

    yields:
        RunTrace: the in-memory audit record for this run.
    """
    run = begin_run(goal)
    span = get_tracer().start_span(
        "pipeline.run",
        attributes=_with_run_id(
            {
                "gen_ai.user.input": clip_payload(goal),
                SPAN_KIND_ATTR: "CHAIN",
                INPUT_VALUE_ATTR: clip_payload(goal),
            }
        ),
    )
    context = span.get_span_context()
    if context.is_valid:
        run.span_id = f"{context.span_id:016x}"
        run.trace_id = f"{context.trace_id:032x}"
    _span_id.set(run.span_id)
    _trace_id.set(run.trace_id)
    with trace.use_span(span, end_on_exit=True):
        try:
            yield run
        except Exception as exc:  # noqa: BLE001 - re-raised after bookkeeping
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            run.add_error("pipeline", str(exc))
            raise
        else:
            span.set_status(Status(StatusCode.OK))
        finally:
            set_output(
                span,
                {
                    "run_id": run.run_id,
                    "nodes": [f"{n['name']}: {n['status']}" for n in run.nodes],
                    "errors": [f"{e['source']}: {e['message']}" for e in run.errors],
                },
            )


@contextmanager
def span(name: str, *, kind: str = "", input_value: Any = "", **attributes: Any) -> Iterator[Span]:
    """Trace one MCP tool call, the RAG retrieval or a validation run.

    Failures are recorded on the current :class:`RunTrace` and re-raised, so
    callers keep their own degradation logic unchanged. Every span ends with
    an explicit OK/ERROR status; use :func:`set_output` inside the block for
    the ``output.value`` payload.

    args:
        name (str): the span name, e.g. ``mcp.get_npc_schedule``.
        kind (str, default ""): OpenInference span kind (``CHAIN``, ``TOOL``,
            ``RETRIEVER``, ``LLM``), shown as Kind in the backend.
        input_value (Any, default ""): span input — a string is used as-is,
            any other payload is JSON-encoded and tagged with a JSON mime type.
        **attributes: primitive span attributes.

    yields:
        Span: the active OpenTelemetry span.
    """
    attrs = _with_run_id(attributes)
    if kind:
        attrs[SPAN_KIND_ATTR] = kind
    if input_value:
        attrs[INPUT_VALUE_ATTR] = _io_value(input_value)
        if not isinstance(input_value, str):
            attrs[INPUT_MIME_TYPE_ATTR] = JSON_MIME_TYPE
    otel_span = get_tracer().start_span(name, attributes=attrs, record_exception=False)
    started = time.perf_counter()
    with trace.use_span(otel_span, end_on_exit=True):
        try:
            yield otel_span
        except Exception as exc:  # noqa: BLE001 - recorded, then re-raised
            otel_span.set_status(Status(StatusCode.ERROR, str(exc)))
            otel_span.record_exception(exc)
            run = current_run()
            if run is not None:
                run.add_error(name, str(exc))
            raise
        else:
            otel_span.set_status(Status(StatusCode.OK))
        finally:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
            otel_span.set_attribute("termina.duration_ms", elapsed_ms)


def set_output(otel_span: Span, payload: Any) -> None:
    """Attach a span's OpenInference ``output.value`` before it ends.

    args:
        otel_span (Span): the still-open span.
        payload (Any): output payload — a string is used as-is, any other
            payload is JSON-encoded and tagged with a JSON mime type.

    returns:
        None: side-effect on the span only.
    """
    otel_span.set_attribute(OUTPUT_VALUE_ATTR, _io_value(payload))
    if not isinstance(payload, str):
        otel_span.set_attribute(OUTPUT_MIME_TYPE_ATTR, JSON_MIME_TYPE)


def record_node(name: str, duration_s: float, status: str, detail: str = "") -> None:
    """Attach one finished graph node to the current run (UI timeline)."""
    run = current_run()
    if run is None:
        return
    run.add_node(name, duration_s, status, detail)


def record_error(source: str, message: str, detail: str = "") -> None:
    """Attach one failure to the current run (UI error list)."""
    run = current_run()
    if run is None:
        return
    run.add_error(source, message, detail)


class TraceCallback(BaseCallbackHandler):
    """LangChain callback: full LLM messages into spans, summary into logs.

    Attach per invocation (``config={"callbacks": [TraceCallback()]}``): each
    call opens a ``gen_ai.chat`` span carrying the complete system/user/assistant
    content for Phoenix, while console logging shows a DEBUG-truncated copy.
    Failures are also recorded on the current run so the UI can list them.
    """

    def __init__(self) -> None:
        super().__init__()
        self._spans: dict[str, Span] = {}

    def on_chat_model_start(
        self,
        serialized: dict,
        messages: list,
        *,
        run_id: str,
        **kwargs: Any,
    ) -> None:
        """Open the gen_ai.chat span and log every outgoing message."""
        model = str(serialized.get("kwargs", {}).get("model_name", "")) if serialized else ""
        flat = list(_iter_messages(messages))
        prompt_text = "\n".join(f"[{_role_of(m)}] {_text_of(m)}" for m in flat)
        attributes = {
            "gen_ai.request.model": model,
            SPAN_KIND_ATTR: "LLM",
            INPUT_VALUE_ATTR: clip_payload(prompt_text),
        }
        # Indexed prompts follow the OpenInference GenAI convention Phoenix
        # reads: without them the whole request renders as one blob, even
        # though the LLM call itself carries distinct system/user messages.
        attributes.update(_prompt_attributes((_role_of(m), _text_of(m)) for m in flat))
        span = get_tracer().start_span(
            "gen_ai.chat",
            attributes=_with_run_id(attributes),
        )
        for message in _iter_messages(messages):
            role, content = _role_of(message), _text_of(message)
            span.add_event(
                f"gen_ai.{role}.message",
                {"message.content": clip_payload(content, SPAN_PAYLOAD_LIMIT)},
            )
            logger.info("--- %s ---\n%s", role, clip_payload(content, LLM_LOG_PAYLOAD_LIMIT))
        logger.info(
            "LLM request run_id=%s model=%s messages=%d",
            current_run_id(),
            model or "?",
            len(list(_iter_messages(messages))),
        )
        self._spans[str(run_id)] = span

    def on_llm_start(
        self, serialized: dict, prompts: list[str], *, run_id: str, **kwargs: Any
    ) -> None:
        """Fallback span for non-chat completions."""
        attributes: dict[str, Any] = {
            SPAN_KIND_ATTR: "LLM",
            INPUT_VALUE_ATTR: clip_payload("\n".join(prompts)),
        }
        attributes.update(_prompt_attributes(("user", prompt) for prompt in prompts))
        span = get_tracer().start_span(
            "gen_ai.chat",
            attributes=_with_run_id(attributes),
        )
        for prompt in prompts:
            span.add_event("gen_ai.user.message", {"message.content": clip_payload(prompt)})
        self._spans[str(run_id)] = span

    def on_llm_end(self, response: Any, *, run_id: str, **kwargs: Any) -> None:
        """Close the span with the assistant answer and token usage."""
        span = self._spans.pop(str(run_id), None)
        message = _last_message(response)
        content = _text_of(message)
        usage = getattr(message, "usage_metadata", None) or {}
        if span is not None:
            if content:
                span.add_event(
                    "gen_ai.choice", {"message.content": clip_payload(content, SPAN_PAYLOAD_LIMIT)}
                )
                span.set_attribute(OUTPUT_VALUE_ATTR, clip_payload(content, SPAN_PAYLOAD_LIMIT))
                # OpenInference GenAI completion: Phoenix renders this as the
                # assistant message instead of an anonymous output blob.
                span.set_attribute("gen_ai.completion.0.role", "assistant")
                span.set_attribute(
                    "gen_ai.completion.0.content", clip_payload(content, SPAN_PAYLOAD_LIMIT)
                )
            input_tokens = usage.get("input_tokens")
            output_tokens = usage.get("output_tokens")
            if input_tokens is not None:
                span.set_attribute("gen_ai.usage.input_tokens", int(input_tokens))
            if output_tokens is not None:
                span.set_attribute("gen_ai.usage.output_tokens", int(output_tokens))
            span.set_status(Status(StatusCode.OK))
            span.end()
        logger.info("--- assistant ---\n%s", clip_payload(content, LLM_LOG_PAYLOAD_LIMIT))
        logger.info(
            "LLM response run_id=%s tokens_in=%s tokens_out=%s",
            current_run_id(),
            input_tokens if input_tokens is not None else "?",
            output_tokens if output_tokens is not None else "?",
        )

    def on_llm_error(self, error: BaseException, *, run_id: str, **kwargs: Any) -> None:
        """Mark the span failed and record the error on the current run."""
        span = self._spans.pop(str(run_id), None)
        if span is not None:
            span.set_status(Status(StatusCode.ERROR, str(error)))
            span.end()
        logger.error("LLM invocation failed: %s", error)
        run = current_run()
        if run is not None:
            run.add_error("llm.chat", str(error))


def _with_run_id(attributes: dict[str, Any]) -> dict[str, Any]:
    """Copy span attributes and add the current run id when known."""
    out = dict(attributes)
    run_id = current_run_id()
    if run_id:
        out["termina.run_id"] = run_id
    return out


def _prompt_attributes(messages: Iterable[tuple[str, str]]) -> dict[str, Any]:
    """OpenInference ``gen_ai.prompt.N.role`` / ``.content`` attributes.

    Phoenix renders each indexed entry as its own message with its role;
    a single concatenated ``input.value`` shows up as one anonymous blob
    even when the LLM call carries distinct system/user messages.
    """
    attrs: dict[str, Any] = {}
    for index, (role, text) in enumerate(messages):
        attrs[f"gen_ai.prompt.{index}.role"] = role
        attrs[f"gen_ai.prompt.{index}.content"] = clip_payload(text, SPAN_PAYLOAD_LIMIT)
    return attrs


def _iter_messages(messages: list) -> Iterator[Any]:
    """Flatten LangChain's list-of-message-lists into single messages."""
    for group in messages:
        if isinstance(group, list):
            yield from group
        else:
            yield group


def _role_of(message: Any) -> str:
    """Map a LangChain message to its GenAI role name."""
    kind = getattr(message, "type", "") or ""
    return {
        "system": "system",
        "human": "user",
        "ai": "assistant",
        "tool": "tool",
    }.get(kind, "user")


def _text_of(message: Any) -> str:
    """Best-effort plain text of a LangChain message."""
    if message is None:
        return ""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    return str(content)


def _last_message(response: Any) -> Any:
    """First generation's message from an LLMResult, or None."""
    generations = getattr(response, "generations", None) or []
    if not generations or not generations[0]:
        return None
    return generations[0][0].message


def clip_payload(text: str, limit: int = SPAN_PAYLOAD_LIMIT) -> str:
    """Truncate *text* to *limit* chars with an explicit marker."""
    if len(text) <= limit:
        return text
    return f"{text[:limit]}... [truncated {len(text) - limit} char]"


def _io_value(payload: Any) -> str:
    """Render an input/output payload: strings as-is, anything else as JSON."""
    if isinstance(payload, str):
        return clip_payload(payload)
    return clip_payload(json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")))
