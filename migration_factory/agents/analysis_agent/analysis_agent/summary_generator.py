def generate_summary(context, maven_data, import_data):
    summary = f"""# Rapport d'Analyse de Migration (AIMF)
**ID du Run :** {context.run_id}
**Date :** {maven_data.get('timestamp', 'N/A')}

## 1. État de la Stack (Stack & Gap)
* **Java Source :** {maven_data['source_stack']['java']} -> **Cible :** 17 [cite: 342, 443]
* **Spring Boot :** {maven_data['source_stack']['spring_boot']} -> **Cible :** 3.5.14 [cite: 342, 443]

## 2. Structure du Projet
* **Nombre de modules détectés :** {maven_data['project_structure']['module_count']} [cite: 444]
* **Modules :** {", ".join(maven_data['project_structure']['modules'])}

## 3. Inventaire de Migration (Imports)
* **Imports `javax.*` (à migrer) :** {import_data['javax_imports']} [cite: 444]
* **Imports `jakarta.*` :** {import_data['jakarta_imports']}
* **Imports Spring :** {import_data['spring_imports']}

## 4. Recommandations de l'Agent de Planning
* [ ] Migrer les dépendances du POM racine. [cite: 445]
* [ ] Remplacer les imports `javax` par `jakarta` dans {len(import_data['files_with_javax'])} fichiers. [cite: 445]
"""
    
    output_file = context.get_output_path("analysis_summary.md")
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(summary)
    
    return output_file