from __future__ import annotations

"""Resolve run_swarm model pins against the live worker adapter union.

Pilots often pass their session model (``cursor/gpt-5-6-luna``,
``openai-codex:gpt-5.6-luna``, ``cursor/grok-4-5``). Those aliases remap to
keyed agentic rows when a matching worker auth exists, or to platform cursor
rows when Settings/platform allow Cursor workers. Unresolved pins demote to
auto-route across the live union catalog instead of failing.
"""

import re
from dataclasses import dataclass
from typing import Any, Optional

from .diag import note as _diag

# Prefer agentic (API-billed) remaps before platform cursor when both match.
_PIN_ADAPTER_ORDER = ("agentic", "cursor", "openai")
_GENERIC_MODEL_TOKENS = frozenset({
    "pro", "mini", "nano", "fast", "high", "low", "max", "latest",
    "free", "exp", "preview", "flash", "plus", "chat", "code",
})
_PIN_PROVIDER_ALIASES = {
    "codex": "openai-codex",
    "chatgpt-codex": "openai-codex",
    "codex-plan": "openai-codex",
}

# ChatGPT Codex OAuth (OPENAI_CODEX_TOKEN) rejects gpt-5.6-*-pro with HTTP 400.
# Luna/Sol/Terra Max = base id + reasoning_effort=max — never the -pro slug.
_CODEX_OAUTH_PRO_BASE = {
    "gpt-5.6-luna-pro": "gpt-5.6-luna",
    "gpt-5.6-sol-pro": "gpt-5.6-sol",
    "gpt-5.6-terra-pro": "gpt-5.6-terra",
}
_LUNA_MAX_PIN_ALIASES = frozenset({
    "luna max",
    "gpt luna max",
    "gpt-luna-max",
    "luna-max",
    "gpt-5.6-luna-max",
    "gpt-5-6-luna-max",
    "max-tier luna",
    "max tier luna",
})


def _bare_model_tail(pin: str) -> str:
    """Last path/colon segment of a pin, lowercased."""
    body = (pin or "").strip()
    if not body:
        return ""
    if ":" in body:
        body = body.split(":", 1)[1].strip() or body
    if "/" in body:
        body = body.rsplit("/", 1)[-1].strip() or body
    return body.lower()


def is_luna_max_pin(pin: str) -> bool:
    """True when the pilot/user named Luna Max (max effort), not Luna Pro."""
    raw = (pin or "").strip().lower()
    if not raw:
        return False
    if raw in _LUNA_MAX_PIN_ALIASES:
        return True
    compact = re.sub(r"[\s_]+", " ", raw).strip()
    if compact in _LUNA_MAX_PIN_ALIASES:
        return True
    bare = _bare_model_tail(pin)
    if bare in _LUNA_MAX_PIN_ALIASES or bare.endswith("luna-max"):
        return True
    # Free-text phrases inside longer pins / labels.
    if "luna max" in compact or "gpt luna max" in compact:
        return True
    return False


def remap_codex_oauth_pro_model(model_id: str) -> tuple[str, str]:
    """Remap ChatGPT Codex OAuth *-pro ids to the supported base slug.

    Returns ``(model, reason)``. Reason is empty when unchanged. Prefer remap
    over reject so Luna Max pins that wrongly resolved to luna-pro still
    dispatch as gpt-5.6-luna (caller keeps reasoning_effort).
    """
    raw = (model_id or "").strip()
    if not raw:
        return "", ""
    bare = _bare_model_tail(raw)
    base = _CODEX_OAUTH_PRO_BASE.get(bare)
    if not base:
        # Also catch hyphen/dot variants of the same pro tails.
        for pro, target in _CODEX_OAUTH_PRO_BASE.items():
            if bare == pro or bare.endswith("/" + pro) or bare.endswith(":" + pro):
                base = target
                break
    if not base:
        return raw, ""
    # Preserve any provider/agentic prefix, swap only the model tail.
    if ":" in raw:
        prov, _rest = raw.split(":", 1)
        return f"{prov}:{base}", f"codex_oauth_pro_remap:{bare}->{base}"
    if "/" in raw:
        head, _tail = raw.rsplit("/", 1)
        # agentic/openai-codex/gpt-5.6-luna-pro → agentic/openai-codex/gpt-5.6-luna
        return f"{head}/{base}", f"codex_oauth_pro_remap:{bare}->{base}"
    return base, f"codex_oauth_pro_remap:{bare}->{base}"


def normalize_swarm_model_pin_request(pin: str) -> tuple[str, dict[str, str]]:
    """Normalize pilot-supplied swarm pins before catalog resolution.

    - Luna Max / GPT Luna Max → gpt-5.6-luna (effort=max is separate).
    - ChatGPT Codex OAuth *-pro → base family id (keep effort).
    """
    requested = (pin or "").strip()
    meta: dict[str, str] = {}
    if not requested:
        return "", meta
    if is_luna_max_pin(requested):
        # Preserve an explicit openai-codex / agentic provider prefix when present.
        prov, _model = _parse_pin_provider_model(requested)
        if prov in ("openai-codex", "codex", "chatgpt-codex", "codex-plan"):
            out = f"{_normalize_pin_provider(prov)}:gpt-5.6-luna"
        elif requested.lower().startswith("agentic/openai-codex/"):
            out = "agentic/openai-codex/gpt-5.6-luna"
        elif requested.lower().startswith("agentic/"):
            out = "agentic/gpt-5.6-luna"
        else:
            out = "gpt-5.6-luna"
        meta["luna_max"] = "1"
        meta["reasoning_effort_hint"] = "max"
        meta["normalize"] = f"luna_max->{out}"
        _diag("swarm_model_pin.luna_max", msg=meta["normalize"])
        return out, meta
    remapped, reason = remap_codex_oauth_pro_model(requested)
    if reason:
        meta["codex_pro_remap"] = reason
        _diag("swarm_model_pin.codex_pro_remap", msg=reason)
        return remapped, meta
    return requested, meta


@dataclass(frozen=True)
class AgenticModelPin:
    """Immutable provider/model constraint for one agentic dispatch."""

    requested: str
    provider: str
    model: str
    router_model_id: str
    reason: str = "exact"
    policy: str = "explicit_pin"

    def payload_fields(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "auto_route": False,
            "allowed_adapters": ["agentic"],
            "pinned_adapter": "agentic",
            "pinned_model": self.router_model_id,
            "pinned_adapter_model_name": self.model,
            "pin_policy": self.policy,
            "requested_model": self.requested,
        }


def _model_family_token(model_id: str) -> str:
    """Distinctive last token (``astra``, ``luna``), or empty for generic tails."""
    bare = (model_id or "").rsplit("/", 1)[-1].strip().lower()
    parts = [p for p in re.split(r"[-_.]+", bare) if p]
    if not parts:
        return ""
    token = parts[-1]
    if token.isdigit() or token in _GENERIC_MODEL_TOKENS or len(token) < 3:
        return ""
    return token


def _normalize_pin_provider(provider: str) -> str:
    raw = (provider or "").strip().lower()
    return _PIN_PROVIDER_ALIASES.get(raw, raw)


def _parse_pin_provider_model(pin: str) -> tuple[str, str]:
    """Best-effort ``(provider, model)`` from a pilot-supplied pin."""
    body = (pin or "").strip()
    if body.lower().startswith("agentic/"):
        body = body.split("/", 1)[1].strip()
    if ":" in body:
        provider, model = body.split(":", 1)
        return _normalize_pin_provider(provider), model.strip()
    known = {
        "cursor",
        "cursor-cli",
        "codex",
        "openai",
        "openai-codex",
        "opencode-go",
        "opencode-zen",
        "openrouter",
        "native",
    }
    if "/" in body:
        head, rest = body.split("/", 1)
        if head.lower() in known:
            return _normalize_pin_provider(head), rest.strip()
    return "", body


def settings_enabled_pin_specs(
    pin: str,
    *,
    enabled: Optional[list[str]] = None,
) -> list[str]:
    """Settings specs for the same enabled model — never a different sibling.

    ``gpt-5.6-astra`` maps to enabled ``openai-codex:gpt-6-astra``. It does
    not map to Sol or Luna. Generic tails (``pro``, ``mini``) match exact ids
    only.
    """
    requested = (pin or "").strip()
    if not requested:
        return []
    if enabled is None:
        try:
            from .model_visibility import get_enabled
            enabled = get_enabled()
        except Exception as exc:
            _diag("swarm_model_pin.enabled_specs", exc)
            enabled = []
    pin_provider, pin_model = _parse_pin_provider_model(requested)
    pin_model_l = (pin_model or "").strip().lower()
    pin_token = _model_family_token(pin_model or requested)
    out: list[str] = []
    seen: set[str] = set()
    for spec in enabled or []:
        raw = str(spec or "").strip()
        if ":" not in raw:
            continue
        prov, mid = raw.split(":", 1)
        prov = _normalize_pin_provider(prov)
        mid = mid.strip()
        if not prov or not mid:
            continue
        if pin_provider and prov != pin_provider:
            continue
        exact = bool(pin_model_l) and mid.lower() == pin_model_l
        token = bool(pin_token) and _model_family_token(mid) == pin_token
        if not (exact or token):
            continue
        key = raw.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(raw)
    return out


def _direct_agentic_provider_model(pin: str) -> Optional[AgenticModelPin]:
    """Resolve ``provider/model`` when a keyed live model is not in the registry."""

    requested = (pin or "").strip()
    matches = settings_enabled_pin_specs(requested)
    if len(matches) == 1:
        provider, model = matches[0].split(":", 1)
        provider = _normalize_pin_provider(provider)
        model = model.strip()
    else:
        body = requested
        if body.lower().startswith("agentic/"):
            body = body.split("/", 1)[1].strip()
        if ":" in body:
            provider, model = body.split(":", 1)
        elif "/" in body:
            provider, model = body.split("/", 1)
        else:
            return None
        provider = _normalize_pin_provider(provider)
        model = model.strip()
    if not provider or not model:
        return None
    try:
        from .auto_registry import keyed_agentic_providers

        keyed = {str(item).strip().lower() for item in keyed_agentic_providers()}
    except Exception as exc:
        _diag("swarm_model_pin.direct_keyed", exc)
        keyed = set()
    if provider not in keyed:
        return None
    return AgenticModelPin(
        requested=requested,
        provider=provider,
        model=model,
        router_model_id=f"agentic/{provider}/{model}",
        reason="direct_provider_model",
    )


def _registry_rows(*, adapters: Optional[set[str]] = None) -> list[dict]:
    try:
        from .registry_wizard import get_models_file_path
        import json
        import os

        path = get_models_file_path()
        if not path or not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)
        models = data.get("models") if isinstance(data, dict) else None
        if not isinstance(models, list):
            return []
        allow = adapters
        out: list[dict] = []
        for row in models:
            if not isinstance(row, dict):
                continue
            adapter = str(row.get("adapter") or "").strip().lower()
            if allow is not None and adapter not in allow:
                continue
            out.append(row)
        return out
    except Exception as e:
        _diag("swarm_model_pin.registry_rows", e)
        return []


def _row_is_keyed_agentic(row: dict, keyed: set) -> bool:
    adapter = str(row.get("adapter") or "").strip().lower()
    if adapter != "agentic":
        return True
    defaults = row.get("payload_defaults")
    provider = ""
    if isinstance(defaults, dict):
        provider = str(defaults.get("provider") or "").strip()
    if keyed and provider and provider not in keyed:
        return False
    return True


def _usable_registry_rows(*, adapters: Optional[set[str]] = None) -> list[dict]:
    try:
        from .auto_registry import keyed_agentic_providers

        keyed = keyed_agentic_providers()
    except Exception as e:
        _diag("swarm_model_pin.keyed_rows", e)
        keyed = set()
    out: list[dict] = []
    seen: set[str] = set()
    for row in _registry_rows(adapters=adapters):
        mid = str(row.get("id") or "").strip()
        if not mid or mid.lower() in seen:
            continue
        if not _row_is_keyed_agentic(row, keyed):
            continue
        seen.add(mid.lower())
        out.append(row)
    return out


def _spec_preferred_registry_ids(spec: str) -> list[str]:
    """Best registry ids for a Settings spec — agentic provider rows first."""
    provider, model = _parse_pin_provider_model(spec)
    out: list[str] = []
    cursor_providers = {"cursor", "cursor-cli", "cursor-sdk"}
    if provider and model:
        if provider in cursor_providers:
            out.append(f"cursor/{model}")
        else:
            out.append(f"agentic/{provider}/{model}")
            out.append(f"agentic/{model}")
    out.extend(pin_candidates(spec))
    seen: set[str] = set()
    uniq: list[str] = []
    for item in out:
        key = item.lower()
        if not item or key in seen:
            continue
        seen.add(key)
        uniq.append(item)
    return uniq


def _enabled_registry_ids(rows: list[dict]) -> list[str]:
    """Settings-enabled picker specs mapped onto ids that exist in *rows*."""
    try:
        from .model_visibility import get_enabled

        enabled = get_enabled()
    except Exception as exc:
        _diag("swarm_model_pin.enabled_ids", exc)
        return []
    if not enabled:
        return []
    by_id = {}
    for row in rows:
        mid = str(row.get("id") or "").strip()
        if mid:
            by_id[mid.lower()] = mid
    out: list[str] = []
    seen: set[str] = set()
    for spec in enabled:
        hit = ""
        for cand in _spec_preferred_registry_ids(spec):
            found = by_id.get(cand.lower())
            if found:
                hit = found
                break
        if not hit:
            provider, model = _parse_pin_provider_model(spec)
            token = _model_family_token(model or spec)
            if token and provider:
                for row in rows:
                    mid = str(row.get("id") or "").strip()
                    if not mid or mid.lower() in seen:
                        continue
                    defaults = row.get("payload_defaults")
                    row_prov = ""
                    if isinstance(defaults, dict):
                        row_prov = str(defaults.get("provider") or "").strip().lower()
                    adapter = str(row.get("adapter") or "").strip().lower()
                    if adapter != "agentic" or row_prov != provider:
                        continue
                    if _model_family_token(mid) == token:
                        hit = mid
                        break
        if hit and hit.lower() not in seen:
            seen.add(hit.lower())
            out.append(hit)
    return out


def _ids_from_rows(rows: list[dict], limit: int) -> list[str]:
    out: list[str] = []
    for row in rows:
        mid = str(row.get("id") or "").strip()
        if not mid:
            continue
        out.append(mid)
        if len(out) >= max(1, int(limit)):
            break
    return out


def list_available_agentic_worker_models(*, limit: int = 24) -> list[str]:
    """Registry ids the agentic swarm router can actually pick right now."""
    rows = _usable_registry_rows(adapters={"agentic"})
    preferred = _enabled_registry_ids(rows)
    if preferred:
        return preferred[: max(1, int(limit))]
    return _ids_from_rows(rows, limit)


def list_available_worker_models(
    *,
    limit: int = 24,
    adapters: Optional[set[str]] = None,
) -> list[str]:
    """Registry ids across the allowed worker adapter union."""
    allow = set(adapters) if adapters is not None else None
    rows = _usable_registry_rows(adapters=allow)
    preferred = _enabled_registry_ids(rows)
    if preferred:
        return preferred[: max(1, int(limit))]
    return _ids_from_rows(rows, limit)


def swarm_model_pin_hint(*, limit: int = 16) -> str:
    """Short tool-schema suffix listing live worker models (or auto-route)."""
    try:
        from .swarm_worker_allowlist import resolve_swarm_worker_allowlist

        allow = set(resolve_swarm_worker_allowlist().get("allowed_adapters") or [])
    except Exception:
        allow = {"agentic"}
    available = list_available_worker_models(limit=limit, adapters=allow or None)
    if not available:
        return (
            "Omit model to auto-route among Models-enabled workers "
            "(OpenCode Go, OpenRouter, ChatGPT Codex OAuth, Cursor API, …). "
            "Session pilot ids are remapped when a matching worker row exists."
        )
    shown = ", ".join(available)
    return (
        "Omit model to auto-route among Models-enabled workers. Live catalog: "
        f"{shown}. Session pilot ids (openai-codex:…, cursor/…, codex/…) remap "
        "to a matching row when present; unknown pins demote to auto-route "
        "inside the enabled set."
    )


def pin_candidates(pin: str) -> list[str]:
    """Ordered alias candidates for a pilot-supplied swarm model pin."""
    original = (pin or "").strip()
    if not original:
        return []
    normalized, _meta = normalize_swarm_model_pin_request(original)
    raw = normalized or original
    out: list[str] = []
    seen: set[str] = set()

    def _add(value: str) -> None:
        v = (value or "").strip()
        if not v:
            return
        key = v.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(v)

    # Remapped Codex/Luna Max ids first so apply_model_pin never pins *-pro.
    _add(raw)
    if original.lower() != raw.lower():
        _add(original)

    # provider:model / engine/model → bare model
    bare = raw
    if ":" in bare:
        bare = bare.split(":", 1)[1].strip() or bare
    _add(bare)
    prefix_heads = {
        "cursor",
        "cursor-cli",
        "codex",
        "openai",
        "openai-codex",
        "agentic",
        "native",
        "opencode-go",
        "opencode-zen",
        "opencode",
    }
    while "/" in bare:
        head, rest = bare.split("/", 1)
        if head.lower() not in prefix_heads:
            break
        next_bare = rest.strip()
        if not next_bare:
            break
        bare = next_bare
        _add(bare)

    # Cursor registry uses hyphens in gpt-5-6-*; OpenCode Go uses dots (gpt-5.6-*).
    dotted = re.sub(r"(gpt-\d+)-(\d+)", r"\1.\2", bare, count=1, flags=re.I)
    _add(dotted)
    hyphenated = re.sub(r"(gpt-\d+)\.(\d+)", r"\1-\2", bare, count=1, flags=re.I)
    _add(hyphenated)

    for body in (bare, dotted, hyphenated):
        if not body:
            continue
        _add(f"agentic/{body}")
        # Codex curated rows use a namespaced registry id so they do not
        # collide with OpenCode Go's flat agentic/gpt-5.6-* rows.
        _add(f"openai-codex/{body}")
        _add(f"agentic/openai-codex/{body}")
        # OpenCode Go registry rows are payload_defaults.provider=opencode-go
        # with id agentic/<model> *or* agentic/opencode-go/<model>. A pin of
        # agentic/opencode/<model> (missing -go) used to demote to auto-route.
        _add(f"opencode-go/{body}")
        _add(f"agentic/opencode-go/{body}")
        # Platform cursor registry peers (only useful when bridge allows cursor).
        _add(f"cursor/{body}")
    # Common typo: agentic/opencode/X vs the real opencode-go provider slug.
    if "agentic/opencode/" in raw.lower() and "opencode-go" not in raw.lower():
        _add(re.sub(r"(?i)agentic/opencode/", "agentic/opencode-go/", raw, count=1))
    return out


def _try_apply_pin(candidate: str, *, adapter: str) -> Optional[dict]:
    try:
        from puppetmaster.model_registry import (
            AmbiguousModelPinError,
            apply_model_pin,
        )
    except Exception as e:
        _diag("swarm_model_pin.apply_import", e)
        return None
    try:
        stamped = apply_model_pin({}, candidate, adapter=adapter)
    except AmbiguousModelPinError as exc:
        _diag("swarm_model_pin.ambiguous", msg=f"pin={candidate!r} err={exc}")
        return None
    except Exception as e:
        _diag("swarm_model_pin.apply", e, msg=f"pin={candidate!r} adapter={adapter}")
        return None
    if not isinstance(stamped, dict) or not stamped.get("pinned_model"):
        return None
    stamped = dict(stamped)
    stamped["pinned_adapter"] = adapter
    return stamped


def _allowed_pin_adapters(
    allowed_adapters: Optional[list[str] | set[str] | tuple[str, ...]],
) -> list[str]:
    if allowed_adapters:
        ordered = [a for a in _PIN_ADAPTER_ORDER if a in set(allowed_adapters)]
        for a in allowed_adapters:
            name = str(a or "").strip().lower()
            if name and name not in ordered:
                ordered.append(name)
        return ordered or ["agentic"]
    try:
        from .swarm_worker_allowlist import resolve_swarm_worker_allowlist

        return list(
            resolve_swarm_worker_allowlist().get("allowed_adapters") or ["agentic"]
        )
    except Exception:
        return ["agentic"]


def resolve_swarm_model_pin(
    pin: str,
    *,
    allowed_adapters: Optional[list[str] | set[str] | tuple[str, ...]] = None,
) -> dict[str, Any]:
    """Resolve a swarm model pin or demote to auto-route.

    Tries each adapter in the Settings/platform union (agentic first, then
    cursor, then openai) so a Cursor Grok pin is not rejected just because the
    agentic catalog lacks that id.

    Returns:
      {
        "pin_fields": dict,   # merged into worker payload when pinned
        "auto_route": bool,
        "requested": str,
        "resolved": str,      # empty when demoted
        "demoted": bool,
        "reason": str,
        "adapter": str,       # adapter that accepted the pin (or "")
      }
    """
    original = (pin or "").strip()
    requested, norm_meta = normalize_swarm_model_pin_request(original)
    empty = {
        "pin_fields": {},
        "auto_route": True,
        "requested": original,
        "resolved": "",
        "demoted": False,
        "reason": "empty",
        "adapter": "",
    }
    if not original:
        return empty
    if not requested:
        requested = original

    # Refresh catalog against live keys so alias resolution sees OpenCode Go /
    # OpenRouter / etc. as they exist *now*, not a stale peer machine catalog.
    try:
        from .auto_registry import ensure_keyed_provider_registry_health

        ensure_keyed_provider_registry_health()
    except Exception as e:
        _diag("swarm_model_pin.health", e)

    adapters = _allowed_pin_adapters(allowed_adapters)
    candidates = list(pin_candidates(requested))
    seen_cands = {c.lower() for c in candidates}
    for spec in settings_enabled_pin_specs(requested):
        for extra in pin_candidates(spec):
            key = extra.lower()
            if key in seen_cands:
                continue
            seen_cands.add(key)
            candidates.append(extra)
    for candidate in candidates:
        for adapter in adapters:
            stamped = _try_apply_pin(candidate, adapter=adapter)
            if not stamped:
                continue
            resolved = str(stamped.get("pinned_model") or "").strip()
            pin_fields = {**stamped, "auto_route": False}
            # Fail closed: never dispatch ChatGPT Codex OAuth *-pro ids.
            for key in ("model", "pinned_adapter_model_name"):
                cur = str(pin_fields.get(key) or "").strip()
                remapped, reason = remap_codex_oauth_pro_model(cur)
                if reason and remapped:
                    pin_fields[key] = remapped
                    _diag("swarm_model_pin.codex_pro_remap_fields", msg=f"{key}:{reason}")
            if norm_meta.get("reasoning_effort_hint") and not pin_fields.get("reasoning_effort"):
                pin_fields["reasoning_effort"] = norm_meta["reasoning_effort_hint"]
            reason = (
                "exact"
                if candidate == original
                else f"alias:{candidate}"
            )
            if norm_meta.get("normalize"):
                reason = f"{norm_meta['normalize']};{reason}"
            elif norm_meta.get("codex_pro_remap"):
                reason = f"{norm_meta['codex_pro_remap']};{reason}"
            return {
                "pin_fields": pin_fields,
                "auto_route": False,
                "requested": original,
                "resolved": str(pin_fields.get("pinned_model") or resolved).strip(),
                "demoted": False,
                "reason": reason,
                "adapter": adapter,
            }

    available = list_available_worker_models(limit=8, adapters=set(adapters))
    reason = (
        f"pin {original!r} not in keyed worker registry "
        f"(adapters={adapters}); "
        f"auto-routing among {available or ['(none keyed)']}"
    )
    _diag("swarm_model_pin.demote", msg=reason)
    return {
        "pin_fields": {},
        "auto_route": True,
        "requested": requested,
        "resolved": "",
        "demoted": True,
        "reason": reason,
        "adapter": "",
    }


def resolve_agentic_model_pin(pin: str) -> tuple[Optional[AgenticModelPin], str]:
    """Resolve an explicit agentic pin without swarm's auto-route demotion."""

    requested = (pin or "").strip()
    if not requested:
        return None, ""

    resolved = resolve_swarm_model_pin(
        requested,
        allowed_adapters=["agentic"],
    )
    if not resolved.get("demoted") and resolved.get("adapter") == "agentic":
        fields = dict(resolved.get("pin_fields") or {})
        provider = str(fields.get("provider") or "").strip().lower()
        model = str(
            fields.get("pinned_adapter_model_name")
            or fields.get("model")
            or ""
        ).strip()
        router_model_id = str(
            fields.get("pinned_model") or resolved.get("resolved") or ""
        ).strip()
        if provider and model and router_model_id:
            return AgenticModelPin(
                requested=requested,
                provider=provider,
                model=model,
                router_model_id=router_model_id,
                reason=str(resolved.get("reason") or "exact"),
            ), ""

    direct = _direct_agentic_provider_model(requested)
    if direct is not None:
        return direct, ""

    available = list_available_agentic_worker_models(limit=8)
    reason = str(resolved.get("reason") or "").strip()
    if not reason:
        reason = f"pin {requested!r} is not available to the agentic adapter"
    hints = ", ".join(available) if available else "(none keyed)"
    return None, f"{reason}. Available agentic models: {hints}"


def agentic_pin_matches_routed_model(
    pin: Optional[AgenticModelPin],
    routed_model: str,
) -> bool:
    """Fail closed only when the provider reports a different known model."""

    if pin is None or not (routed_model or "").strip():
        return True

    def _normalized(value: str) -> str:
        text = (value or "").strip().lower()
        if text.startswith("agentic/"):
            text = text.split("/", 1)[1]
        return text

    served = _normalized(routed_model)
    accepted = {
        _normalized(pin.router_model_id),
        _normalized(f"{pin.provider}/{pin.model}"),
        _normalized(pin.model),
    }
    return served in accepted
