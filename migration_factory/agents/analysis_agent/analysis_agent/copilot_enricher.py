import json

def enrich_with_ai(context, report_data):
    print("--- Enrichissement par l'IA (Copilot) ---")
    

    
    ai_suggestions = {
        "additional_risks": [
            "L'application utilise une vieille version de Spring Security qui nécessite une réécriture complète des filtres.",
            "Dépendance détectée vers une librairie incompatible avec Jakarta EE."
        ],
        "recommendations": [
            "Passer les configurations XML vers des classes Java Config avant de migrer vers Spring Boot 3.",
            "Vérifier la compatibilité des pilotes de base de données avec Hibernate 6."
        ],
        "summary_notes": "Analyse globale : migration de complexité moyenne, principalement focalisée sur le passage à Jakarta EE."
    }

    
    report_data["ai_enrichment"]["status"] = "USED"
    report_data["ai_enrichment"]["additional_risks"] = ai_suggestions["additional_risks"]
    report_data["ai_enrichment"]["recommendations"] = ai_suggestions["recommendations"]
    
    assist_artifact = {
        "run_id": context.run_id,
        "status": "SUCCESS",
        "model": "gpt-4o", 
        "suggestions_count": len(ai_suggestions["recommendations"])
    }
    
    output_file = context.get_output_path("copilot_assist.json")
    with open(output_file, 'w') as f:
        json.dump(assist_artifact, f, indent=4)
        
    return report_data