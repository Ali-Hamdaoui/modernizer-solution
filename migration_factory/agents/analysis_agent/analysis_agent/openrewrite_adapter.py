import subprocess
import json

def run_openrewrite_dryrun(context):
    print("🔮 Lancement de la simulation OpenRewrite (Dry-Run)...")
    cmd = [
        "mvn", "rewrite:dryRun",
        "-Drewrite.recipeArtifactCoordinates=org.openrewrite.recipe:rewrite-spring:RELEASE",
        "-Drewrite.activeRecipes=org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_0"
    ]
    
    result_data = {"status": "SKIPPED", "warnings": []}
    
    try:
        subprocess.run(cmd, cwd=context.legacy_app_path, capture_output=True, text=True, check=True)
        result_data["status"] = "SUCCESS"
        
        output_file = context.get_output_path("rewrite_preview.json")
        with open(output_file, 'w') as f:
            json.dump(result_data, f, indent=4)
            
    except Exception as e:
        result_data["status"] = "FAILED"
        result_data["warnings"].append(f"Échec du dry-run OpenRewrite : {str(e)}")
        print("⚠️ Avertissement : La simulation OpenRewrite a échoué, mais l'analyse continue.")
        
    return result_data