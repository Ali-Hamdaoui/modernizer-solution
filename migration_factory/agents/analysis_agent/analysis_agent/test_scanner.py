import os
import json

def scan_tests(directory):
    test_files = []
    test_path = os.path.join(directory, "src", "test", "java")
    
    if os.path.exists(test_path):
        for root, _, files in os.walk(test_path):
            for file in files:
                if file.endswith("Test.java") or file.endswith("Tests.java"):
                    test_files.append(os.path.join(root, file))
    
    inventory = {
        "test_count": len(test_files),
        "test_files": test_files,
        "surefire_reports_available": False 
    }
    
    return inventory

def save_test_inventory(context, inventory):
    output_file = context.get_output_path("test_inventory.json")
    with open(output_file, 'w') as f:
        json.dump(inventory, f, indent=4)
    return output_file