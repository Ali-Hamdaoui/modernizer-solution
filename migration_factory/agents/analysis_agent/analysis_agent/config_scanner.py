import os
import json

def scan_config_files(directory):
    inventory = {
        "profiles": [],
        "port": "8080",
        "has_datasource": False,
        "has_security": False,
        "has_actuator": False,
        "config_files_found": []
    }

    config_dir = os.path.join(directory, "src", "main", "resources")
    
    if os.path.exists(config_dir):
        for file in os.listdir(config_dir):
            if file.startswith("application") and (file.endswith(".properties") or file.endswith(".yml")):
                inventory["config_files_found"].append(file)
                path = os.path.join(config_dir, file)
                
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if "datasource" in content: inventory["has_datasource"] = True
                    if "security" in content: inventory["has_security"] = True
                    if "actuator" in content: inventory["has_actuator"] = True
                    if "server.port" in content:
                        pass

    return inventory

def save_config_inventory(context, inventory):
    output_file = context.get_output_path("config_inventory.json")
    with open(output_file, 'w') as f:
        json.dump(inventory, f, indent=4)
    return output_file