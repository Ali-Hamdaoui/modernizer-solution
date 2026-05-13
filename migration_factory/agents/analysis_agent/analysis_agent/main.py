import argparse
import sys
import json
from context_manager import MigrationContext
from maven_scanner import scan_root_pom
from import_scanner import scan_java_imports
from dependency_adapter import run_dependency_tree
from test_scanner import scan_tests, save_test_inventory
from report_assembler import assemble_report
from summary_generator import generate_summary
from copilot_enricher import enrich_with_ai
from config_scanner import scan_config_files, save_config_inventory
from surefire_parser import parse_surefire_reports
from openrewrite_adapter import run_openrewrite_dryrun

def main():
    parser = argparse.ArgumentParser(description="AIMF Analysis Agent CLI")
    parser.add_argument("--run-id", required=True, help="ID unique de la migration")
    parser.add_argument("--legacy", required=True, help="Chemin vers l'application source")
    parser.add_argument("--modernized", required=True, help="Chemin vers le dossier de sortie")

    args = parser.parse_args()

    try:
        print(f"🚀 [AIMF] Démarrage de l'analyse - Run ID: {args.run_id}")

        ctx = MigrationContext(args.run_id, args.legacy, args.modernized)

        print("🔍 Scan du projet Maven (pom.xml)...")
        maven_results = scan_root_pom(f"{args.legacy}/pom.xml")
        
        print("🌳 Extraction de l'arbre des dépendances...")
        run_dependency_tree(ctx)
        
        print("📄 Analyse des imports Java (recherche de javax.*)...")
        import_results = scan_java_imports(args.legacy)
        
        print("⚙️ Scan des fichiers de configuration...")
        config_inv = scan_config_files(args.legacy)
        save_config_inventory(ctx, config_inv)
        
        print("🧪 Inventaire des tests et analyse Surefire...")
        test_inventory = scan_tests(args.legacy)
        test_inventory["surefire_summary"] = parse_surefire_reports(args.legacy)
        save_test_inventory(ctx, test_inventory)

        run_openrewrite_dryrun(ctx)

        print("🏗️ Assemblage du rapport technique...")
        report_data = assemble_report(ctx, maven_results, import_results)

        print("🧠 Enrichissement sémantique par GitHub Copilot...")
        final_report = enrich_with_ai(ctx, report_data)
        
        report_path = ctx.get_output_path("analysis_report.json")
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(final_report, f, indent=4)

        summary_path = generate_summary(ctx, maven_results, import_results)

        print("-" * 50)
        print(f"✅ ANALYSE TERMINÉE AVEC SUCCÈS")
        print(f"📂 Rapport JSON : {report_path}")
        print(f"📄 Résumé MD    : {summary_path}")
        print("-" * 50)

    except Exception as e:
        print(f"❌ ERREUR CRITIQUE : {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()