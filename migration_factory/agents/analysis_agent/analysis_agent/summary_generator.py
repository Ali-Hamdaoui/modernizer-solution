def generate_summary(context, maven_data, import_data):
    target_stack = maven_data.get("target_stack", {})
    warning_lines = "\n".join(
        f"* **Avertissement :** {warning}" for warning in maven_data.get("warnings", [])
    ) or "* Aucun avertissement de cible."

    summary = f"""# Rapport d'Analyse de Migration (AIMF)
**ID du Run :** {context.run_id}
**Date :** {maven_data.get('timestamp', 'N/A')}

## 1. Etat de la Stack (Stack & Gap)
* **Java Source :** {maven_data['source_stack']['java']} -> **Cible :** {target_stack.get('java', '17')} [cite: 342, 443]
* **Spring Boot :** {maven_data['source_stack']['spring_boot']} -> **Cible :** {target_stack.get('spring_boot', '3.5.14')} [cite: 342, 443]
* **Spring Framework Cible :** {target_stack.get('spring_framework', 'unknown')}

## 2. Structure du Projet
* **Nombre de modules detectes :** {maven_data['project_structure']['module_count']} [cite: 444]
* **Modules :** {", ".join(maven_data['project_structure']['modules'])}

## 3. Inventaire de Migration (Imports)
* **Imports `javax.*` (a migrer) :** {import_data['javax_imports']} [cite: 444]
* **Imports `jakarta.*` :** {import_data['jakarta_imports']}
* **Imports Spring :** {import_data['spring_imports']}

## 4. Recommandations de l'Agent de Planning
* [ ] Migrer les dependances du POM racine. [cite: 445]
* [ ] Remplacer les imports `javax` par `jakarta` dans {len(import_data['files_with_javax'])} fichiers. [cite: 445]

## 5. Avertissements de cible
{warning_lines}
"""

    output_file = context.get_output_path("analysis_summary.md")
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(summary)

    return output_file
