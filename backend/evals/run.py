import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from zapagent.config import Settings
from zapagent.domain.conversation import ChatEntry, Conversation, Event
from zapagent.entrypoints.container import build_container
from zapagent.store.seed import seed_store

SCENARIOS = Path(__file__).with_name("scenarios.json")


@dataclass
class ToolRecorder:
    tools: list[str] = field(default_factory=list)

    async def publish(self, event: Event) -> None:
        if event.type == "tool_started":
            self.tools.append(event.data["tool"])


@dataclass(frozen=True)
class EvalResult:
    scenario: str
    passed: bool
    detail: str


def pickup_date() -> str:
    candidate = datetime.now(UTC).date() + timedelta(days=2)
    if candidate.weekday() == 6:
        candidate += timedelta(days=1)
    return candidate.isoformat()


def check(
    scenario: dict[str, Any], tools: list[str], handoff: bool, reply: str
) -> tuple[bool, str]:
    problems = []
    missing = [tool for tool in scenario["expected_tools"] if tool not in tools]
    if missing:
        problems.append(f"não chamou {missing}")
    forbidden = [tool for tool in scenario.get("forbidden_tools", []) if tool in tools]
    if forbidden:
        problems.append(f"chamou indevidamente {forbidden}")
    expected_handoff = scenario.get("expect_handoff")
    if expected_handoff is not None and expected_handoff != handoff:
        problems.append(f"handoff={handoff}, esperado {expected_handoff}")
    lowered = reply.lower()
    for text in scenario.get("reply_must_contain", []):
        if text.lower() not in lowered:
            problems.append(f"resposta sem '{text}'")
    for text in scenario.get("reply_must_not_contain", []):
        if text.lower() in lowered:
            problems.append(f"resposta vazou '{text}'")
    return not problems, "; ".join(problems) or f"tools={tools}"


async def evaluate(scenario: dict[str, Any], container, recorder: ToolRecorder) -> EvalResult:
    agent = container.agent(events=recorder)
    recorder.tools.clear()
    conversation = Conversation(phone=scenario["phone"], name=scenario["name"])
    history: list[ChatEntry] = []
    handoff = False
    reply = ""
    for turn in scenario["turns"]:
        text = turn.format(pickup_date=pickup_date())
        history.append(ChatEntry(scenario["phone"], "in", "customer", text))
        outcome = await agent.run(conversation, history)
        reply = outcome.reply or ""
        history.append(ChatEntry(scenario["phone"], "out", "bot", reply))
        if outcome.handoff_reason:
            handoff = True
            break
    passed, detail = check(scenario, list(recorder.tools), handoff, reply)
    return EvalResult(scenario["id"], passed, f"{detail} | resposta: {reply[:160]!r}")


async def main() -> int:
    settings = Settings()
    threshold = float(os.environ.get("EVALS_MIN_ACCURACY", "0.75"))
    container = build_container(settings)
    await seed_store(container.database)
    scenarios = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    recorder = ToolRecorder()

    results = [await evaluate(scenario, container, recorder) for scenario in scenarios]
    for result in results:
        print(f"[{'PASS' if result.passed else 'FAIL'}] {result.scenario}: {result.detail}")
    accuracy = sum(result.passed for result in results) / len(results)
    print(f"\nAcurácia: {accuracy:.0%} (mínimo exigido: {threshold:.0%})")
    return 0 if accuracy >= threshold else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
