"""probe_audit.py — 量化子監査レーンの受け入れプローブ(第 1 弾)

実行: python3 probe_audit.py
期待: 最終行に "AUDIT PROBE OK" が出力される(形式目印 — AGENTS.md 2.3)。

検証項目:
  P1 決定性      : 同一入力+同一タグで 2 回実行 → receipt の JSON バイト一致
  P2 全列挙性    : 語彙語の全出現が候補として捕捉される(独立ループで交差照合)
  P3 8 状態 LUT  : (backing, scope) の全状態が正しいシグナルへ写像される
  P4 本文非掲載  : Machine Receipt(JSON)に本文が現れない(ハッシュのみ)
  P5 ゲート      : RED 残留で --fail-on-unverified → 終了コード 1 / タグ適用で 0
  P6 実事故文    : フェルマー記事 F6 の修正前(RED)/修正後+定理タグ(GREEN)の区分
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sieve_referee import DEFAULT_VOCAB, audit_documents, load_tags_from_text
from sieve_referee.quantifier_audit import format_audit_report

F6_ORIGINAL = "排除は一撃で確定し、肯定は永遠に非確定だ。"
F6_FIXED = (
    "排除は一撃で確定し、肯定は単一の底の結果からは非確定だ"
    "(すべての底を試せば理論上は決定的になるが、作業量が実用性を失う)。"
)

failures = []


def check(label, ok, detail=""):
    print("[%s] %s %s" % ("PASS" if ok else "FAIL", label, detail))
    if not ok:
        failures.append(label)


# --- P1 決定性 + P4 本文非掲載 -------------------------------------------------
docs = {"draft_a.txt": F6_ORIGINAL + "この文は量化子を含まない。\n" + F6_FIXED}
r1 = audit_documents(docs)
r2 = audit_documents(docs)
b1 = json.dumps(r1.receipt, ensure_ascii=False, sort_keys=True)
b2 = json.dumps(r2.receipt, ensure_ascii=False, sort_keys=True)
check("P1 determinism", b1 == b2)
check("P4 no body in receipt", "肯定は" not in b1 and "作業量が実用性を失う" not in b1)

# --- P2 全列挙性(独立実装での交差照合) -----------------------------------------
text = "常に A。決して B はしない。どの C も D。装飾的な文。すべて E は F。絶対に G。"
cands = audit_documents({"t.txt": text}).worksheets["t.txt"]
covered = {pos for c in cands for pat in c["patterns"]
           for pos in [text.find(pat)]}
missed = []
for pat in DEFAULT_VOCAB:
    pos = text.find(pat)
    while pos != -1:
        if not any(c["start"] <= pos < c["end"] for c in cands):
            missed.append((pat, pos))
        pos = text.find(pat, pos + 1)
check("P2 full enumeration", len(cands) == 5 and not missed,
      "candidates=%d missed=%s" % (len(cands), missed))

# --- P3 8 状態 LUT -------------------------------------------------------------
sha = hashlib.sha256(F6_ORIGINAL.strip().encode("utf-8")).hexdigest()
states = {
    ("theorem", "universal"): ("GREEN", "THEOREM_BACKED_UNIVERSAL"),
    ("theorem", "measured"): ("GREEN", "THEOREM_BACKED_MEASURED"),
    ("enumerated", "universal"): ("GREEN", "ENUMERATED_UNIVERSAL"),
    ("enumerated", "measured"): ("GREEN", "ENUMERATED_MEASURED"),
    ("sample", "universal"): ("YELLOW", "SAMPLE_ONLY_UNIVERSAL"),
    ("sample", "measured"): ("GREEN", "SAMPLE_SCOPED_MEASURED"),
    ("unbacked", "universal"): ("RED", "UNBACKED_UNIVERSAL"),
    ("unbacked", "measured"): ("YELLOW", "UNBACKED_MEASURED"),
}
lut_bad = []
for (backing, scope), (want_sig, want_name) in states.items():
    if backing == "unbacked":
        # unbacked は「タグなし」でしか到達しない(設計)。scope 指定のみで measured を作る。
        tag_body = {"scope": scope} if scope == "measured" else None
    else:
        tag_body = {"backing": backing, "scope": scope}
    tags = load_tags_from_text(json.dumps({sha: tag_body})) if tag_body else {}
    rep = audit_documents({"d.txt": F6_ORIGINAL}, tags=tags)
    cand = rep.receipt["documents"][0]["candidates"][0]
    if (cand["signal"], cand["pattern_name"]) != (want_sig, want_name):
        lut_bad.append((backing, scope, cand["signal"], cand["pattern_name"]))
check("P3 8-state LUT", not lut_bad, str(lut_bad))

# --- P5 ゲート(CLI 終了コード) --------------------------------------------------
with tempfile.TemporaryDirectory() as td:
    Path(td, "draft.txt").write_text(F6_ORIGINAL, encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parent))
    cmd = [sys.executable, "-c",
           "from sieve_referee.cli import main; import sys; main()"]
    p_red = subprocess.run(
        cmd + [td, "--audit", "--fail-on-unverified", "--output-dir", td],
        capture_output=True, text=True, env=env)
    check("P5 gate exit 1 on RED", p_red.returncode == 1,
          "exit=%d" % p_red.returncode)

    tags_path = Path(td, "tags.json")
    tags_path.write_text(json.dumps({sha: "theorem"}), encoding="utf-8")
    p_tagged = subprocess.run(
        cmd + [td, "--audit", "--audit-tags", str(tags_path),
               "--fail-on-unverified", "--output-dir", td],
        capture_output=True, text=True, env=env)
    check("P5 gate exit 0 after tag", p_tagged.returncode == 0,
          "exit=%d" % p_tagged.returncode)

# --- P6 実事故文の区分 ----------------------------------------------------------
rep_orig = audit_documents({"f6.txt": F6_ORIGINAL})
cand_orig = rep_orig.receipt["documents"][0]["candidates"][0]
check("P6 original is RED/UNBACKED_UNIVERSAL",
      (cand_orig["signal"], cand_orig["pattern_name"]) == ("RED", "UNBACKED_UNIVERSAL"))

sha_fixed = hashlib.sha256(F6_FIXED.strip().encode("utf-8")).hexdigest()
rep_fixed = audit_documents({"f6.txt": F6_FIXED}, tags={sha_fixed: "theorem"})
cand_fixed = rep_fixed.receipt["documents"][0]["candidates"][0]
check("P6 fixed+theorem is GREEN/THEOREM_BACKED_UNIVERSAL",
      (cand_fixed["signal"], cand_fixed["pattern_name"]) == ("GREEN", "THEOREM_BACKED_UNIVERSAL"))

# --- Human worksheet の見本(先頭 12 行) ----------------------------------------
print("\n--- worksheet sample (draft_a.txt, untagged) ---")
print("\n".join(format_audit_report(audit_documents(docs)).splitlines()[:12]))

print()
if failures:
    print("AUDIT PROBE FAILED: %s" % failures)
    sys.exit(1)
print("AUDIT PROBE OK")
