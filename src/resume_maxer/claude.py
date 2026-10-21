"""One structured answer from Claude, through the API or through Claude Code.

The writer and the judge both ask Claude for JSON of a fixed shape. This module
owns how the question travels: the API with a key, or Claude Code on a logged-in
subscription. Either way the caller gets an Answer whose content has been
validated against the expected model, because model output is never trusted.
"""

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import anthropic
from pydantic import BaseModel, ValidationError


@dataclass(frozen=True)
class Answer[T: BaseModel]:
    parsed: T | None  # None when the model stopped early, refused, or answered badly
    stop_reason: str | None
    usage: anthropic.types.Usage
    cost_usd: float  # list price; a subscription run is not billed per token
    request_id: str | None
    detail: str | None = None  # why there is no answer, when there is none


class ClaudeError(RuntimeError):
    """Claude could not be reached, or failed before giving any answer."""


@dataclass(frozen=True)
class Price:
    """USD per million tokens."""

    input: float
    output: float
    cache_write: float
    cache_read: float


# Claude API list prices (5-minute cache: writes 1.25x input, reads 0.1x input).
PRICES = {
    "claude-haiku-5-5": Price(input=0.10, output=0.50, cache_write=0.125, cache_read=0.01),
    "claude-sonnet-5-5": Price(input=2.00, output=10.00, cache_write=2.50, cache_read=0.20),
}


def cost_usd(model: str, usage: anthropic.types.Usage) -> float:
    price = PRICES[model]
    return (
        usage.input_tokens * price.input
        + usage.output_tokens * price.output
        + (usage.cache_creation_input_tokens or 0) * price.cache_write
        + (usage.cache_read_input_tokens or 0) * price.cache_read
    ) / 1_000_000


def _tail(text: str, lines: int = 15) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def ask_api[T: BaseModel](
    *,
    system: str,
    context: str,
    user: str,
    output: type[T],
    model: str,
    effort: str,
    client: anthropic.Anthropic | None = None,
    max_tokens: int = 20_000,
) -> Answer[T]:
    """Ask through the API (needs an API key). `context` is cached after `system`."""
    client = client or anthropic.Anthropic()
    blocks = [{"type": "text", "text": system}]
    if context:
        blocks.append({"type": "text", "text": context, "cache_control": {"type": "ephemeral"}})
    response = client.messages.parse(
        model=model,
        max_tokens=max_tokens,
        system=blocks,
        messages=[{"role": "user", "content": user}],
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        output_format=output,
    )
    complete = response.stop_reason == "end_turn"
    return Answer(
        parsed=response.parsed_output if complete else None,
        stop_reason=response.stop_reason,
        usage=response.usage,
        cost_usd=cost_usd(model, response.usage),
        request_id=response._request_id,
        detail=None if complete else f"the model stopped early ({response.stop_reason})",
    )


CLAUDE_ENV = "CLAUDE_CODE"  # full path to the claude executable, when not on PATH
CLAUDE_TIMEOUT_S = 1200


def find_claude() -> str:
    configured = os.environ.get(CLAUDE_ENV)
    if configured:
        if not Path(configured).is_file():
            raise ClaudeError(f"{CLAUDE_ENV} is set to {configured!r}, which does not exist.")
        return configured
    found = shutil.which("claude")
    if found:
        return found
    raise ClaudeError(
        "Claude Code not found. Install it (https://claude.com/claude-code), run `claude` "
        f"once to log in, or set {CLAUDE_ENV} to the executable's full path."
    )


def ask_claude_code[T: BaseModel](
    *,
    system: str,
    context: str,
    user: str,
    output: type[T],
    model: str,
    effort: str,
    what: str = "answer",
    timeout_s: float = CLAUDE_TIMEOUT_S,
) -> Answer[T]:
    """Ask through Claude Code headless, on its logged-in subscription.

    `what` names the expected answer in error details ("resume document").
    """
    exe = find_claude()
    schema = json.dumps(anthropic.transform_schema(output.model_json_schema()))
    with tempfile.TemporaryDirectory(prefix="resume-maxer-claude-") as tmp:
        system_file = Path(tmp) / "system.txt"
        system_file.write_text(f"{system}\n{context}\n" if context else system, encoding="utf-8")
        # Argument list, never a shell string. --tools "" leaves the model no tools,
        # so text planted in a job description cannot make it run commands or read
        # files. The empty temp folder as the working directory keeps any CLAUDE.md
        # or memory out of the prompt. The question goes in on stdin.
        cmd = [
            exe,
            "-p",
            "--model", model,
            "--effort", effort,
            "--tools", "",
            "--system-prompt-file", str(system_file),
            "--json-schema", schema,
            "--output-format", "json",
            "--no-session-persistence",
            "--strict-mcp-config",
        ]  # fmt: skip
        try:
            proc = subprocess.run(
                cmd,
                input=user,
                cwd=tmp,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            raise ClaudeError(f"Claude Code did not answer within {timeout_s}s.") from None

    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise ClaudeError(
            f"Claude Code exited {proc.returncode} without a result:\n"
            + _tail(proc.stderr or proc.stdout)
        ) from None

    u = out.get("usage") or {}
    result = {
        "stop_reason": out.get("terminal_reason") or out.get("subtype"),
        "usage": anthropic.types.Usage(
            input_tokens=u.get("input_tokens", 0),
            output_tokens=u.get("output_tokens", 0),
            cache_creation_input_tokens=u.get("cache_creation_input_tokens", 0),
            cache_read_input_tokens=u.get("cache_read_input_tokens", 0),
        ),
        # Claude Code's own list-price figure; its cache writes use the 1-hour rate.
        "cost_usd": float(out.get("total_cost_usd") or 0.0),
        "request_id": out.get("session_id"),
    }
    if out.get("is_error"):
        detail = f"Claude Code reported {out.get('subtype')}: {str(out.get('result'))[:500]}"
        return Answer(parsed=None, detail=detail, **result)
    try:
        parsed = output.model_validate(out.get("structured_output"))
    except ValidationError as exc:
        return Answer(parsed=None, detail=f"not a valid {what}: {exc}", **result)
    return Answer(parsed=parsed, **result)
