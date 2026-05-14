import os
import json


def _collect_test_files(root_directory):
    test_files = []
    test_path = os.path.join(root_directory, "src", "test", "java")

    if os.path.exists(test_path):
        for root, _, files in os.walk(test_path):
            for file in files:
                if file.endswith("Test.java") or file.endswith("Tests.java"):
                    test_files.append(os.path.join(root, file))

    return sorted(test_files), test_path


def scan_tests(directory, modernized_directory=None):
    legacy_test_files, legacy_test_path = _collect_test_files(directory)

    inventory = {
        "test_count": len(legacy_test_files),
        "test_files": legacy_test_files,
        "surefire_reports_available": False
    }

    if modernized_directory:
        modernized_test_files, modernized_test_path = _collect_test_files(modernized_directory)

        legacy_relative = {
            os.path.relpath(path, legacy_test_path) for path in legacy_test_files
        }
        modernized_relative = {
            os.path.relpath(path, modernized_test_path) for path in modernized_test_files
        }

        missing = sorted(legacy_relative - modernized_relative)
        inventory.update(
            {
                "legacy_test_count": len(legacy_test_files),
                "modernized_test_count": len(modernized_test_files),
                "missing_tests_count": len(missing),
                "missing_tests": missing,
            }
        )

    return inventory


def save_test_inventory(context, inventory):
    output_file = context.get_output_path("test_inventory.json")
    with open(output_file, 'w') as f:
        json.dump(inventory, f, indent=4)
    return output_file
