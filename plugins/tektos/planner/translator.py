"""plugins.tektos.planner.translator — natural language → technical English.

Rewritten from donor ``tektos-ultima/src/tektos/agents/planner/translator.py``
per ADR-106 D2. All three donor substitution maps (``_FILLERS``,
``_VAGUE_TO_PRECISE``, ``_PHRASE_REPLACEMENTS``) preserved verbatim; only the
module surface changes (``Any`` typing collapses to ``dict[str, object] | None``).

The LLM is the translator layer; Python is the computation engine. The
Translator never does computation.
"""

from __future__ import annotations

import re

# Fillers and hedging language to strip — verbatim from donor.
_FILLERS: dict[str, str] = {
    "i think": "",
    "i believe": "",
    "i feel": "",
    "i would": "",
    "i would like to": "",
    "i want": "",
    "i need": "",
    "i would like": "",
    "i was thinking": "",
    "maybe we could": "",
    "perhaps we should": "",
    "feel free to": "",
    "you can": "",
    "you should": "",
    "it would be good to": "",
    "it might be nice to": "",
    "it would be better if": "",
    "i was wondering if": "",
    "could you please": "",
    "would you mind": "",
    "just": " ",
    "simply": " ",
    "basically": "",
    "essentially": "",
    "actually": "",
    "really": "",
    "very": "",
    "quite": "",
    "rather": "",
    "somewhat": "",
    "a bit": "",
    "a little": "",
    "a": " ",
    "an": " ",
}

# Common vague terms with their precise replacements — verbatim from donor.
_VAGUE_TO_PRECISE: dict[str, str] = {
    "fast": "low-latency",
    "slow": "high-latency",
    "good": "meets acceptance criteria",
    "bad": "fails acceptance criteria",
    "big": "large-scale",
    "small": "minimal",
    "simple": "straightforward",
    "complex": "requires careful design",
    "secure": "meets security standards",
    "reliable": "meets uptime/accuracy standards",
    "scalable": "handles increased load",
    "efficient": "optimal resource usage",
    "clean": "well-structured code",
    "modern": "current best practices",
    "user-friendly": "intuitive interface with minimal cognitive load",
    "real-time": "sub-second response time",
}

# Common NL phrases → precise technical descriptions — verbatim from donor.
_PHRASE_REPLACEMENTS: dict[str, str] = {
    "build me an api": "implement RESTful API with",
    "create a database": "design database schema with",
    "write a function": "implement function that",
    "make a website": "develop web application with",
    "add authentication": "implement authentication with",
    "handle errors": "implement error handling with",
    "save to disk": "persist data to",
    "load from file": "read data from",
    "send an email": "send email notification via",
    "call an endpoint": "make HTTP request to",
    "parse json": "deserialize JSON response from",
    "format output": "serialize output as",
    "run tests": "execute test suite with",
    "deploy to production": "deploy to production environment",
    "clone the repo": "clone repository from",
    "install the package": "install package from",
    "update the config": "update configuration with",
    "restart the server": "restart server process",
    "kill the process": "terminate process by",
    "check the logs": "review logs from",
    "look at the code": "analyze code in",
    "fix the bug": "resolve the issue in",
    "refactor this": "restructure for clarity and performance in",
    "optimize this": "optimize for performance in",
    "test this": "write test coverage for",
    "document this": "generate documentation for",
    "add logging": "add structured logging for",
    "add monitoring": "add metrics collection for",
    "add caching": "add caching layer for",
    "add rate limiting": "add rate limiting to",
    "add validation": "add input validation for",
    "add type hints": "add type annotations to",
    "add documentation": "add docstrings and type hints to",
    "remove dead code": "remove unused code from",
    "merge the changes": "merge pull request with",
    "create a branch": "create branch named",
    "commit the changes": "commit changes with message",
    "push to remote": "push to remote repository",
    "pull from remote": "pull from remote repository",
    "reset the branch": "reset branch to",
    "revert the commit": "revert commit with hash",
    "squash the commits": "squash commits into single commit",
    "rebase onto": "rebase onto",
    "check the diff": "review diff between",
    "compare versions": "compare versions and",
    "check the status": "check status of",
    "check the health": "verify health of",
    "check the performance": "measure performance of",
    "check the security": "audit security of",
    "check the tests": "verify test coverage of",
    "check the docs": "review documentation of",
    "check the config": "validate configuration for",
    "check the metrics": "collect metrics from",
    "check the alerts": "check alerts for",
    "check the deployments": "check deployments for",
    "check the backups": "verify backups of",
    "check the snapshots": "verify snapshots of",
    "check the state": "verify state of",
    "check the data": "verify data integrity of",
    "check the schema": "verify schema of",
    "check the migrations": "verify migrations for",
    "check the models": "verify models for",
    "check the routes": "verify routes for",
    "check the handlers": "verify handlers for",
    "check the middlewares": "verify middlewares for",
    "check the plugins": "verify plugins for",
    "check the extensions": "verify extensions for",
    "check the adapters": "verify adapters for",
    "check the providers": "verify providers for",
    "check the services": "verify services for",
    "check the controllers": "verify controllers for",
    "check the views": "verify views for",
    "check the templates": "verify templates for",
    "check the styles": "verify styles for",
    "check the scripts": "verify scripts for",
    "check the assets": "verify assets for",
    "check the images": "verify images for",
    "check the fonts": "verify fonts for",
    "check the icons": "verify icons for",
    "check the translations": "verify translations for",
    "check the locales": "verify locales for",
    "check the i18n": "verify internationalization for",
    "check the a11y": "verify accessibility for",
    "check the seo": "verify SEO for",
    "check the analytics": "verify analytics for",
    "check the tracking": "verify tracking for",
    "check the privacy": "verify privacy for",
    "check the gdpr": "verify GDPR compliance for",
    "check the pci": "verify PCI compliance for",
    "check the hipaa": "verify HIPAA compliance for",
    "check the soc": "verify SOC compliance for",
    "check the iso": "verify ISO compliance for",
    "check the nist": "verify NIST compliance for",
    "check the cisa": "verify CISA compliance for",
    "check the mitre": "verify MITRE compliance for",
    "check the owasp": "verify OWASP compliance for",
}


def translate_to_technical_english(text: str) -> str:
    """Convert natural language to Proper Technical English.

    Verbatim port of donor ``translate_to_technical_english`` — same substitution
    order (fillers → vague → phrases), same whitespace collapse + trailing
    punctuation strip.
    """
    result = text.lower().strip()

    for filler, replacement in _FILLERS.items():
        result = re.sub(rf"\b{re.escape(filler)}\b", replacement, result, flags=re.IGNORECASE)

    for vague, precise in _VAGUE_TO_PRECISE.items():
        result = re.sub(rf"\b{re.escape(vague)}\b", precise, result, flags=re.IGNORECASE)

    for phrase, replacement in _PHRASE_REPLACEMENTS.items():
        result = re.sub(rf"\b{re.escape(phrase)}\b", replacement, result, flags=re.IGNORECASE)

    result = re.sub(r"\s+", " ", result).strip()
    result = result.rstrip(".!,;")

    return result


def add_spec_context(text: str, context: dict[str, object] | None = None) -> str:
    """Add context to a translated prompt for completeness."""
    if not context:
        return text

    parts = [text]
    if context.get("language_game"):
        parts.append(f"language_game: {context['language_game']}")
    tech_stack = context.get("tech_stack")
    if tech_stack:
        parts.append(f"tech_stack: {', '.join(str(t) for t in tech_stack)}")  # type: ignore[arg-type]
    constraints = context.get("constraints")
    if constraints:
        parts.append(f"constraints: {', '.join(str(c) for c in constraints)}")  # type: ignore[arg-type]

    return "\n".join(parts)


__all__ = ["translate_to_technical_english", "add_spec_context"]
