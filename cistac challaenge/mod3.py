"""Brino coach integration. Groq is optional; scoring remains deterministic."""
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

import database1 as db

BASE_DIR = Path(__file__).resolve().parent
_loader = SourceFileLoader("ai4brain_meesi", str(BASE_DIR / "meesi"))
_spec = spec_from_loader(_loader.name, _loader)
meesi = module_from_spec(_spec)
_loader.exec_module(meesi)
GROQ_MODEL = meesi.MODEL


def llm_available():
    return meesi.groq_available()


def _rule_indicators(messages):
    users = [str(m.get("content", "")) for m in messages if m.get("role") == "user"]
    text = " ".join(users).lower()
    entries = {}
    groups = {
        "precise_objective": ("help", "explain", "make", "create", "plan", "give", "what", "how"),
        "provides_context": ("because", "currently", "my ", "i am", "project", "for "),
        "specifies_constraints": ("don't", "do not", "only", "under", "without", "must", "keep"),
        "requests_justification": ("why", "explain", "reason", "source"),
        "checks_information": ("check", "verify", "sure", "source", "test", "confirm"),
        "detects_errors": ("wrong", "error", "mistake", "incorrect", "actually"),
        "requests_improvement": ("improve", "change", "fix", "correct", "better", "revise"),
        "reformulates_request": ("instead", "i mean", "what i meant", "to clarify"),
        "refines_result": ("keep", "add", "remove", "more", "less", "format"),
        "proposes_own_ideas": ("i think", "i suggest", "my idea", "i would"),
        "explains_reasoning": ("because", "my reason", "so that", "since"),
        "makes_own_decisions": ("i'll", "i will", "i choose", "i prefer", "decided"),
        "protects_sensitive_data": ("private", "personal data", "password", "email", "consent"),
        "recognizes_ai_limitations": ("may be wrong", "limitations", "not sure", "verify", "source"),
        "uses_ai_responsibly": ("responsible", "ethical", "safe", "consent", "privacy"),
    }
    for name, terms in groups.items():
        found = next((term for term in terms if term in text), None)
        # No matching evidence means "not observed", not a negative score.
        entries[name] = {"score": 1 if found else None, "confidence": "medium", "evidence": f"User wording included: {found}" if found else None}
    return entries


def _reply(messages, profile, plan):
    fallback = {"answer": "I can help explain your practice scores, suggest a game, or review your weekly plan.",
                "feedback": "Try asking one specific question about your recent practice."}
    if not llm_available():
        return fallback
    profile = {**profile, "weekly_plan": plan}
    result = meesi.generate_ai_coach_feedback(profile, messages[-12:])
    if not isinstance(result, dict):
        return fallback
    answer = result.get("ai_response", "").strip()
    feedback = result.get("coaching_feedback", "").strip()
    if not answer or db.forbidden_terms_found(answer + " " + feedback):
        return fallback
    return {"answer": answer, "feedback": feedback}


def coach_turn(user_id, name, consent, messages, twin=None, chat_sid=None, elo=None, objective=None):
    twin = twin or {}
    dims = twin.get("dimensions", twin)
    facts = db.detect_weakness(dims)
    indicators = _rule_indicators(messages)
    collab = db.aggregate_collaboration(indicators)
    collab["source"] = "rules"
    collab["saved"] = False
    sid = chat_sid
    if user_id:
        db.ensure_user(user_id, name or "", consent)
        if consent:
            collab = db.save_collaboration_session(user_id, indicators, chat_sid)
            collab["source"] = "rules"
            collab["saved"] = bool(collab.get("available"))
            sid = collab.get("session_id", chat_sid)
    cfg = db._config()["adaptive_bridge"]["weekly_plan"]
    current = {d: (dims.get(d) or {}).get("score", cfg["provisional_score"]) for d in ("WM", "AT", "PS", "SP")}
    names = {"WM": ("Working Memory", "Memory Flip"), "AT": ("Attention", "Focus Sprint"),
             "PS": ("Problem Solving", "Pattern Quest"), "SP": ("Processing Speed", "Speed Match")}
    plan = [{"dimension": d, "name": names[d][0], "game": names[d][1],
             "target_score": cfg["target_score"], "current_score": current[d]} for d in current]
    scores = {d: {k: v for k, v in (dims.get(d) or {}).items() if k in ("score", "uncertainty")}
              for d in ("WM", "AT", "PS", "SP") if isinstance(dims.get(d), dict)}
    objective = objective if isinstance(objective, dict) else {}
    objective_names = {"balanced": "Balanced growth", "WM": "Working memory", "AT": "Attention",
                       "PS": "Problem solving", "SP": "Processing speed"}
    focus = objective.get("dimension") if objective.get("dimension") in objective_names else "balanced"
    try:
        weekly_sessions = max(1, min(7, int(objective.get("weekly_sessions", 3))))
    except (TypeError, ValueError):
        weekly_sessions = 3
    target_score = None
    if focus != "balanced":
        try:
            target_score = max(1, min(100, int(objective.get("target_score", cfg["target_score"]))))
        except (TypeError, ValueError):
            target_score = cfg["target_score"]
    user_objective = {"focus_dimension": objective_names[focus], "weekly_sessions": weekly_sessions,
                      "target_score": target_score}
    profile = {"name": name, "weakest_dimension": facts["weakest_name"], "scores": scores,
               "user_objective": user_objective}
    coach = _reply(messages, profile, plan)
    reply = coach["answer"]
    if coach["feedback"]:
        reply += "\n\nCoach's note: " + coach["feedback"]
    return {"reply": reply, "answer": coach["answer"],
            "collab": collab, "chat_sid": sid,
            "facts": {"weakest_dimension": facts["weakest_name"], "weakest_code": facts["weakest"]}}
