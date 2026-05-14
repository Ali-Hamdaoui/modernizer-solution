import os
import json
import datetime
import copy

class CopilotAuthResolver:
    """Résout l'authentification via Token Utilisateur ou GitHub App (Exigence Audit)."""
    @staticmethod
    def get_token():
        token = os.environ.get("GITHUB_COPILOT_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not token:
            raise PermissionError("Auth Resolver : Aucun token GITHUB_TOKEN trouvé. Accès refusé.")
        return token

class ModelResolver:
    """Détermine le modèle autorisé, avec fallback (Exigence Audit)."""
    @staticmethod
    def resolve():
        # Fallback sur un modèle par défaut si la variable d'environnement n'est pas définie
        return os.environ.get("COPILOT_ANALYSIS_MODEL", "gpt-4o")

class GuardrailValidator:
    """Garde-fou strict pour empêcher l'IA d'altérer les faits déterministes (Exigence Audit)."""
    @staticmethod
    def validate_no_tampering(original_report, enriched_report):
        # On vérifie que l'IA n'a pas secrètement changé la version de Java ou de Spring Boot
        if original_report["source_stack"] != enriched_report["source_stack"]:
            raise ValueError("Guardrail Violation : L'IA a tenté de modifier la stack source !")
        
        # On vérifie qu'elle n'a pas altéré le comptage exact des imports
        if original_report["project_metadata"]["import_stats"] != enriched_report["project_metadata"]["import_stats"]:
            raise ValueError("Guardrail Violation : L'IA a falsifié les statistiques du code !")
        
        return True

def enrich_with_ai(context, report_data):
    print("🧠 Initialisation du SDK Copilot (Agent: aimf-analysis-assist)...")
    
    # 1. Copie de sécurité (Immutable baseline)
    original_data_backup = copy.deepcopy(report_data)
    
    # 2. Préparation du journal d'audit de l'IA
    assist_artifact = {
        "run_id": context.run_id,
        "status": "SKIPPED",
        "model": None,
        "suggestions_count": 0,
        "timestamp": datetime.datetime.now().isoformat()
    }

    try:
        # 3. Résolution de l'authentification et du modèle
        token = CopilotAuthResolver.get_token()
        model = ModelResolver.resolve()
        assist_artifact["model"] = model

        # 4. Configuration stricte de l'agent (Exigence Audit)
        agent_config = {
            "name": "aimf-analysis-assist",
            "tools": ["grep", "glob", "view"], # Interdiction d'utiliser bash/write
            "system_prompt": (
                "Tu es un agent d'analyse en lecture seule. Règles ABSOLUES :\n"
                "1. Interdiction de modifier les versions détectées.\n"
                "2. Interdiction d'inventer des faits ou fichiers.\n"
                "3. Interdiction de suggérer des modifications directes dans le code.\n"
                "4. Ne génère QUE des recommandations d'architecture basées sur le rapport."
            )
        }

        # --- SIMULATION DE L'APPEL RÉSEAU SDK ---
        # Dans la vraie vie, ici nous ferions : client.chat.completions.create(...)
        # Si on arrive ici (token valide), on simule la réponse de l'API
        ai_response = {
            "additional_risks": ["L'utilisation massive de javax.persistence nécessitera un renommage complet du package."],
            "recommendations": ["Privilégier OpenRewrite pour automatiser le passage à jakarta.*"]
        }
        # ---------------------------------------

        # 5. Application de l'enrichissement
        report_data["ai_enrichment"]["status"] = "USED"
        report_data["ai_enrichment"]["additional_risks"] = ai_response["additional_risks"]
        report_data["ai_enrichment"]["recommendations"] = ai_response["recommendations"]

        # 6. APPLICATION DU GARDE-FOU (Guardrail)
        GuardrailValidator.validate_no_tampering(original_data_backup, report_data)

        # Si le garde-fou valide, c'est un succès
        assist_artifact["status"] = "SUCCESS"
        assist_artifact["suggestions_count"] = len(ai_response["recommendations"])

    except PermissionError as pe:
        # Erreur "normale" si pas de token : on fail-open
        print(f"⚠️ Copilot désactivé : {str(pe)}")
        report_data["ai_enrichment"]["status"] = "SKIPPED"
        assist_artifact["status"] = "SKIPPED"
        assist_artifact["error"] = str(pe)

    except Exception as e:
        # Si l'IA hallucine ou si le Guardrail la bloque : on rejette ses changements
        print(f"❌ Rejet de l'IA (Fail-Open) : {str(e)}")
        report_data = original_data_backup # Restauration des faits réels !
        report_data["ai_enrichment"]["status"] = "FAILED"
        assist_artifact["status"] = "FAILED"
        assist_artifact["error"] = str(e)

    finally:
        # 7. Écriture obligatoire du rapport d'audit Copilot
        output_file = context.get_output_path("copilot_assist.json")
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(assist_artifact, f, indent=4)

    return report_data