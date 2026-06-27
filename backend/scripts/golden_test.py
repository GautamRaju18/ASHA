"""
Golden scenario smoke test (requires Ollama running with the configured model).

Run from the backend dir:
    ./.venv/Scripts/python.exe scripts/golden_test.py

These assert SAFETY properties (the dangerous cases must escalate; the mild case
must not always refer) rather than exact wording, since the local model's prose
varies. The conservative bias means an over-escalation is not a failure.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.graph.build import run_case  # noqa: E402

REFER = {"EMERGENCY_REFER_NOW", "URGENT_REFER_TODAY"}

CASES = [
    # (name, text, must_be_one_of OR None, must_refer)
    ("hero child pneumonia (Hindi)",
     "2 saal ki bachi, do din se bukhar aur tezi se saans le rahi hai, doodh nahi pee rahi.",
     None, True),
    ("mild cold adult",
     "Adult, mild runny nose and slight cough for 1 day, eating and drinking normally, no fever.",
     None, False),
    ("diarrhoea lethargic (danger)",
     "2 year old child, watery diarrhoea, now lethargic and not drinking, sunken eyes.",
     None, True),
    ("maternal pre-eclampsia",
     "Pregnant woman, 8 months, severe headache and blurred vision with swelling of face.",
     None, True),
]


def main() -> int:
    failures = 0
    for name, text, _allowed, must_refer in CASES:
        res = run_case(text=text, session_id="golden", geo={})
        status = res.get("status")
        cat = res.get("triage_category")
        refers = cat in REFER
        if status == "needs_clarification":
            ok = not must_refer  # only acceptable for the mild/benign case
            verdict = "ASK"
        else:
            ok = (refers == must_refer) or (must_refer and refers)
            verdict = cat
        flag = "PASS" if ok else "FAIL"
        if not ok:
            failures += 1
        print(f"[{flag}] {name:34} -> {verdict} (must_refer={must_refer}, "
              f"override={res.get('danger_sign_override')})")
    print(f"\n{len(CASES) - failures}/{len(CASES)} passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
