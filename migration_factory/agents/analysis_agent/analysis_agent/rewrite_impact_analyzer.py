import re


def analyze_rewrite_patch(patch_text):
    files = set()
    java_files = 0
    pom_files = 0
    config_files = 0
    test_files = 0
    high_risk = []
    migration_signals = set()
    added = 0
    removed = 0

    current_file = None
    for line in patch_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                current_file = parts[3].removeprefix("b/")
                files.add(current_file)

                if current_file.endswith(".java"):
                    java_files += 1
                if current_file.endswith("pom.xml") or current_file == "pom.xml":
                    pom_files += 1
                if any(current_file.endswith(ext) for ext in (".yml", ".yaml", ".properties", ".xml", ".conf")):
                    config_files += 1
                if re.search(r"(^|/)src/test/|Test\.java$", current_file):
                    test_files += 1
                if current_file.endswith("pom.xml") or "src/main/java" in current_file:
                    high_risk.append(current_file)

        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
            if "jakarta." in line or "javax." in line or "spring.boot3" in line.lower():
                migration_signals.add("api_or_boot_upgrade")
        elif line.startswith("-"):
            removed += 1
            if "javax." in line:
                migration_signals.add("javax_removed")

    if not files:
        level = "UNKNOWN"
    elif pom_files > 0 or len(high_risk) > 3 or (added + removed) > 250:
        level = "HIGH"
    elif (added + removed) > 50 or java_files > 5:
        level = "MEDIUM"
    else:
        level = "LOW"

    return {
        "changed_file_count": len(files),
        "patch_lines_added": added,
        "patch_lines_removed": removed,
        "java_files_changed": java_files,
        "pom_files_changed": pom_files,
        "config_files_changed": config_files,
        "test_files_changed": test_files,
        "high_risk_files": sorted(set(high_risk)),
        "migration_signals": sorted(migration_signals),
        "impact": level,
    }
