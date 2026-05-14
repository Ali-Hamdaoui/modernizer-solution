import xml.etree.ElementTree as ET

def scan_root_pom(file_path):
    # Namespace Maven standard
    ns = {"mvn": "http://maven.apache.org/POM/4.0.0"}
    
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()

        # Extraction de la version Spring Boot (Task #12)
        parent_version = root.find(".//mvn:parent/mvn:version", ns)
        spring_boot = parent_version.text if parent_version is not None else "unknown"

        # Extraction de la version Java (Task #12)
        java_ver_elem = root.find(".//mvn:properties/mvn:java.version", ns)
        java_version = java_ver_elem.text if java_ver_elem is not None else "unknown"

        # Extraction des modules
        modules = [m.text for m in root.findall(".//mvn:modules/mvn:module", ns)]

        # On retourne les données avec les noms de clés attendus par le rapport (Task #13, #22)
        return {
            "source_stack": {
                "java": java_version,
                "spring_boot": spring_boot
            },
            "project_structure": {
                "modules": modules,
                "module_count": len(modules)
            },
            "target_stack": {
                "java": "17",
                "spring_boot": "3.5.14"
            }
        }
    except Exception as e:
        return {"error": str(e)}