import subprocess
import os
import json

def run_dependency_tree(context):
    cmd = ["mvn", "dependency:tree", "-DoutputType=text"]
    
    try:
        result = subprocess.run(
            cmd, cwd=context.legacy_app_path, 
            capture_output=True, text=True, check=True
        )
        
        raw_path = context.get_output_path("dependency-tree.raw.txt")
        with open(raw_path, "w") as f:
            f.write(result.stdout)
            
        graph = {
            "available": True,
            "raw_file": "dependency-tree.raw.txt",
            "summary": "Arbre de dépendances extrait via Maven"
        }
        
        output_file = context.get_output_path("dependency_graph.json")
        with open(output_file, 'w') as f:
            json.dump(graph, f, indent=4)
            
        return graph
    except Exception as e:
        return {"available": False, "error": str(e)}