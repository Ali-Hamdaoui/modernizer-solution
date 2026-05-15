from rewrite_impact_analyzer import analyze_rewrite_patch


LOW_PATCH = """diff --git a/src/test/java/A.java b/src/test/java/A.java
--- a/src/test/java/A.java
+++ b/src/test/java/A.java
+import jakarta.foo.Bar;
-import javax.foo.Bar;
"""


HIGH_PATCH = """diff --git a/pom.xml b/pom.xml
--- a/pom.xml
+++ b/pom.xml
+<dependency>new</dependency>
-dummy
""" + "\n".join([f"+line{i}" for i in range(260)])


def test_low_impact_patch_summary():
    out = analyze_rewrite_patch(LOW_PATCH)
    assert out["impact"] == "LOW"
    assert out["changed_file_count"] == 1
    assert out["test_files_changed"] == 1


def test_high_impact_patch_summary():
    out = analyze_rewrite_patch(HIGH_PATCH)
    assert out["impact"] == "HIGH"
    assert out["pom_files_changed"] == 1
