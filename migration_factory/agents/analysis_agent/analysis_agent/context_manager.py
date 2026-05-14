import os

class SecurityViolationError(Exception):
    """Exception critique levée si l'agent tente une opération illégale sur les chemins."""
    pass

class MigrationContext:
    def __init__(self, run_id, legacy_path, modernized_path):
        self.run_id = run_id
        
        # 1. Normalisation absolue des chemins (empêche les ambiguïtés)
        self.legacy_app_path = os.path.abspath(legacy_path)
        self.modernized_app_path = os.path.abspath(modernized_path)
        
        # 2. Définition stricte de l'ALLOWLIST (La seule zone de droite)
        self.output_dir = os.path.abspath(os.path.join(
            self.modernized_app_path, 
            ".migration", "runs", self.run_id, "analysis"
        ))
        
        # HARD GUARD : Le dossier de sortie ne peut JAMAIS être dans les sources legacy
        if self.output_dir.startswith(self.legacy_app_path):
            raise SecurityViolationError(
                "CRITIQUE : Configuration illégale. Le dossier de sortie chevauche le code source protégé."
            )

        os.makedirs(self.output_dir, exist_ok=True)

    def get_output_path(self, filename):
        """Génère un chemin et le valide contre la Allowlist et la Denylist (Problème 7)."""
        
        # 1. Anti-Path Traversal (Bloque les attaques de type "../../../etc/passwd")
        if ".." in filename:
            raise SecurityViolationError(f"CRITIQUE : Tentative de Path Traversal bloquée : {filename}")
            
        final_path = os.path.abspath(os.path.join(self.output_dir, filename))
        
        # 2. ALLOWLIST : Le fichier DOIT être dans l'espace de sortie désigné
        if not final_path.startswith(self.output_dir):
            raise SecurityViolationError(f"CRITIQUE : Écriture hors de l'Allowlist bloquée : {final_path}")
            
        # 3. DENYLIST : Protection absolue des sources contre l'écrasement
        # On interdit formellement d'écrire dans un dossier "src" ou d'écraser des fichiers de config.
        forbidden_patterns = ["\\src\\", "/src/", "pom.xml", "application.properties", "application.yml"]
        for pattern in forbidden_patterns:
            if pattern in final_path:
                raise SecurityViolationError(f"CRITIQUE : Écriture sur un motif interdit (Denylist) : {final_path}")
                
        return final_path
        
    def validate_read_path(self, target_path):
        """Garantit qu'on ne lit que dans les dossiers du projet (Problème 6)."""
        abs_target = os.path.abspath(target_path)
        if not (abs_target.startswith(self.legacy_app_path) or abs_target.startswith(self.modernized_app_path)):
            raise SecurityViolationError(f"CRITIQUE : Tentative de lecture d'un fichier externe bloquée : {abs_target}")
        return abs_target