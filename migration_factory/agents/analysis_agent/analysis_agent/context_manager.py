import os
from datetime import datetime

class MigrationContext:
    def __init__(self, run_id, legacy_path, modernized_path):
        self.run_id = run_id
        # Chemins de lecture (Code source)
        self.legacy_app_path = os.path.abspath(legacy_path)
        self.modernized_app_path = os.path.abspath(modernized_path)
        
        # Chemin d'écriture (Résultats de l'analyse)
        self.output_dir = os.path.join(
            self.modernized_app_path, 
            ".migration", "runs", self.run_id, "analysis"
        )
        
        # Création automatique du dossier de sortie s'il n'existe pas
        os.makedirs(self.output_dir, exist_ok=True)

    def get_output_path(self, filename):
        """Retourne le chemin complet pour un fichier de résultat"""
        return os.path.join(self.output_dir, filename)