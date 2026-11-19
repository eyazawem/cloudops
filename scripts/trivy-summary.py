"""Prints one line per Trivy finding from a JSON report, then a total."""
import collections
import json
import sys

data = json.load(open(sys.argv[1]))
lines = []
for result in data.get("Results") or []:
    target = result.get("Target")
    for v in result.get("Vulnerabilities") or []:
        fixed = v.get("FixedVersion", "no fix")
        lines.append((v["Severity"], "VULN", f'{v["VulnerabilityID"]} {v["PkgName"]} {v["InstalledVersion"]} -> {fixed} | {target}'))
    for m in result.get("Misconfigurations") or []:
        lines.append((m["Severity"], "MISCONF", f'{m["ID"]} {m["Title"]} | {target}'))
    for s in result.get("Secrets") or []:
        lines.append((s["Severity"], "SECRET", f'{s["RuleID"]} {s["Title"]} | {target}'))
for severity, kind, text in sorted(lines):
    print(severity, kind, text)
counts = collections.Counter(severity for severity, _, _ in lines)
print("TOTAL:", len(lines), dict(counts) if lines else "no finding")
