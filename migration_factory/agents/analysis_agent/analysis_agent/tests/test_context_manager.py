import pytest
from context_manager import MigrationContext, SecurityViolationError

def test_context_manager_blocks_legacy_overlap():
    """Prouve que l'agent refuse de configurer sa zone de sortie DANS les sources du client."""
    with pytest.raises(SecurityViolationError, match="chevauche le code source protégé"):
        # On tente de mettre l'output dans le même dossier que le legacy
        MigrationContext(run_id="run_1", legacy_path="/fake/legacy", modernized_path="/fake/legacy")

def test_context_manager_blocks_path_traversal():
    """Prouve que l'agent bloque les attaques de type '../' pour remonter l'arborescence."""
    ctx = MigrationContext("run_1", "/fake/legacy", "/fake/modernized")
    
    with pytest.raises(SecurityViolationError, match="Path Traversal"):
        ctx.get_output_path("../../../etc/passwd")

def test_context_manager_enforces_denylist():
    """Prouve que l'agent refuse formellement d'écraser un fichier pom.xml ou des sources."""
    ctx = MigrationContext("run_1", "/fake/legacy", "/fake/modernized")
    
    with pytest.raises(SecurityViolationError, match="motif interdit"):
        ctx.get_output_path("pom.xml")