"""操作层：注册 / 核验 / 对账的唯一实现，CLI 与自检脚本共用。

三条硬规则在这里落地：
1. 注册即拒：判据不合规、claim 含糊、数据源当下取不到、窗口超出到期日，
   一律拒绝，账本一个字都不写。
2. 判定冻结：一旦出现 hit / miss，不再允许重跑；只有 undetermined 可以
   补跑一次（并在记录里写 ``supersedes`` / ``retry_of_undetermined``），
   防止「重跑到命中」。
3. 时间全显式：所有写入时刻来自调用方 ``at``，本模块不读系统时钟。
"""
from __future__ import annotations

import re
from datetime import date

import criterion as C
import evaluate as E
import ledger as L
import reconcile as R
import sources as S
import timeutil as T

ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,63}$")
REQUIRED_PAYLOAD = ("id", "claim", "registered_at", "expires_on", "criterion")
ALLOWED_PAYLOAD = REQUIRED_PAYLOAD + ("provenance",)
PROVENANCE_KINDS = ("live", "backfill_selftest")


class RegistrationRejected(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class FrozenVerdict(RuntimeError):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _provenance(payload: dict) -> dict:
    raw = payload.get("provenance")
    if raw is None:
        return {"kind": "live", "note": ""}
    if not isinstance(raw, dict) or set(raw) - {"kind", "note"}:
        raise RegistrationRejected("PROVENANCE_INVALID",
                                   "provenance 只允许 kind / note 两个字段")
    kind = raw.get("kind", "live")
    if kind not in PROVENANCE_KINDS:
        raise RegistrationRejected("PROVENANCE_INVALID",
                                   f"provenance.kind 必须是 {PROVENANCE_KINDS} 之一")
    note = raw.get("note", "")
    if not isinstance(note, str):
        raise RegistrationRejected("PROVENANCE_INVALID", "provenance.note 必须是字符串")
    return {"kind": kind, "note": note}


def build_registration(payload: dict, at: str, ledger_path) -> dict:
    """校验一条注册请求并落账，返回账本记录。不写系统时间。"""
    if not isinstance(payload, dict):
        raise RegistrationRejected("PAYLOAD_INVALID", "注册请求必须是 JSON 对象")
    T.parse_iso_utc(at)  # 写入时刻不合法直接拒绝
    unknown = sorted(set(payload) - set(ALLOWED_PAYLOAD))
    if unknown:
        raise RegistrationRejected("UNKNOWN_FIELD", f"注册请求含未知字段 {unknown}")
    missing = [k for k in REQUIRED_PAYLOAD if k not in payload]
    if missing:
        raise RegistrationRejected("MISSING_FIELD", f"注册请求缺少字段 {missing}")

    reg_id = payload["id"]
    if not isinstance(reg_id, str) or not ID_PATTERN.fullmatch(reg_id):
        raise RegistrationRejected("ID_INVALID",
                                   "id 必须匹配 ^[A-Za-z0-9][A-Za-z0-9._:-]{2,63}$")

    entries = L.read_entries(ledger_path)
    if any(e.get("kind") == "registration" and e.get("id") == reg_id for e in entries):
        raise RegistrationRejected("DUPLICATE_ID", f"id {reg_id} 已注册")

    C.lint_claim(payload["claim"])
    criterion = C.validate(payload["criterion"])  # 结构化判据：不合规即拒

    registered_at = payload["registered_at"]
    registered_date = T.utc_date(registered_at)
    expires_text = payload["expires_on"]
    if not isinstance(expires_text, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", expires_text):
        raise RegistrationRejected("DATE_FORMAT", "expires_on 必须是 YYYY-MM-DD")
    try:
        expires = date.fromisoformat(expires_text)
    except ValueError as exc:
        raise RegistrationRejected("DATE_FORMAT",
                                   f"expires_on 不是合法日期：{expires_text!r}") from exc
    if registered_date > expires:
        raise RegistrationRejected("REGISTERED_AFTER_EXPIRY",
                                   f"registered_at {registered_date} 晚于到期日 {expires}")
    window_end = date.fromisoformat(criterion["window"]["end"])
    if window_end > expires:
        raise RegistrationRejected("WINDOW_AFTER_EXPIRY",
                                   f"判据窗口末 {window_end} 超出到期日 {expires}")

    provenance = _provenance(payload)
    write_date = T.utc_date(at)
    if write_date < registered_date:
        raise RegistrationRejected("WRITE_BEFORE_REGISTRATION",
                                   f"写入时刻 {write_date} 早于申报的注册时刻 {registered_date}")
    if provenance["kind"] == "live" and write_date > expires:
        raise RegistrationRejected(
            "REGISTRATION_AFTER_EXPIRY",
            f"live 注册在到期日 {expires} 之后才写入（{write_date}）；"
            f"历史补录必须标 provenance.kind=backfill_selftest")

    src = criterion["source"]
    try:
        _, fingerprint = S.probe(src["provider"], src["id"], src["field"], at)
    except S.SourceUnavailable as exc:
        raise RegistrationRejected(
            exc.code, f"数据源当下取不到，拒绝注册：{exc.detail}") from exc

    record = {
        "kind": "registration",
        "id": reg_id,
        "claim": payload["claim"],
        "claim_canonical": C.render_claim(criterion),
        "registered_at": registered_at,
        "expires_on": expires_text,
        "criterion": criterion,
        "criterion_sha256": C.criterion_sha256(criterion),
        "source_probe": fingerprint,
        "provenance": provenance,
    }
    return L.append(ledger_path, record, at=at)


def _check_criterion_unchanged(reg: dict) -> None:
    if reg.get("criterion_sha256") != C.criterion_sha256(C.validate(reg["criterion"])):
        raise L.LedgerError("CRITERION_TAMPERED",
                            f"{reg['id']} 的判据与注册时哈希不一致，拒绝据此判定")


def verify_one(reg: dict, at: str, ledger_path, entries: list[dict] | None = None) -> dict:
    """核验一条注册。命中/未命中已存在则抛 ``FrozenVerdict``；未到期抛 ``E.NotDue``。"""
    _check_criterion_unchanged(reg)
    entries = entries if entries is not None else L.read_entries(ledger_path)
    previous = R.latest_verdicts(entries).get(reg["id"])
    if previous and previous["verdict"] in (E.HIT, E.MISS):
        raise FrozenVerdict(
            f"{reg['id']} 已于 {previous['at']} 判定为 {previous['verdict']}，不允许重跑")
    record = E.evaluate(reg, at)
    if previous:
        record["supersedes"] = previous["at"]
        record["retry_of_undetermined"] = True
    return L.append(ledger_path, record, at=at)


def verify_all(at: str, ledger_path, only_id: str | None = None) -> list[dict]:
    """核验全部到期事件，返回逐条状态。"""
    T.parse_iso_utc(at)
    entries = L.read_entries(ledger_path)
    registrations = [e for e in entries if e.get("kind") == "registration"]
    if only_id is not None and not any(r["id"] == only_id for r in registrations):
        raise RegistrationRejected("ID_NOT_FOUND", f"账本里没有 id {only_id}")

    results: list[dict] = []
    for reg in registrations:
        if only_id is not None and reg["id"] != only_id:
            continue
        previous = R.latest_verdicts(entries).get(reg["id"])
        if previous and previous["verdict"] in (E.HIT, E.MISS):
            results.append({"id": reg["id"], "status": "frozen",
                            "verdict": previous["verdict"], "reason_code": None})
            continue
        try:
            record = verify_one(reg, at, ledger_path, entries)
        except E.NotDue as exc:
            results.append({"id": reg["id"], "status": "not_due", "verdict": None,
                            "reason_code": None, "detail": exc.message})
            continue
        entries.append(record)
        results.append({"id": reg["id"], "status": record["verdict"],
                        "verdict": record["verdict"],
                        "reason_code": record["reason_code"],
                        "value": (record["observed"] or {}).get("value")})
    return results


def reconcile(ledger_path, point_min: int = R.POINT_ESTIMATE_MIN) -> dict:
    return R.summarize(L.read_entries(ledger_path), point_min=point_min)
