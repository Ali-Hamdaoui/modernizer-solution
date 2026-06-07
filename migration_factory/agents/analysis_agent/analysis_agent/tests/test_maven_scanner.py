import pytest

from maven_scanner import scan_root_pom, scan_root_pom_with_prefixes


def _write_java_source(tmp_path, relative_path, content):
    source_file = tmp_path / "src" / "main" / "java" / relative_path
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text(content, encoding="utf-8")


def test_scan_root_pom_extracts_correct_versions(tmp_path):
    fake_pom = tmp_path / "pom.xml"
    _write_java_source(tmp_path, "com/example/LibraryType.java", "package com.example;\nclass LibraryType {}\n")
    fake_pom.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
    <project xmlns="http://maven.apache.org/POM/4.0.0">
        <parent>
            <version>2.7.18</version>
        </parent>
        <properties>
            <java.version>11</java.version>
        </properties>
        <modules>
            <module>shoppoc-core</module>
            <module>shoppoc-api</module>
        </modules>
    </project>
    """,
        encoding="utf-8",
    )

    result = scan_root_pom(str(fake_pom))

    assert result["source_stack"]["java"] == "11"
    assert result["source_stack"]["spring_boot"] == "2.7.18"
    assert result["source_stack"]["build_tool"] == "maven"
    assert result["project_structure"]["modules"] == ["shoppoc-core", "shoppoc-api"]
    assert result["project_structure"]["module_count"] == 2
    assert result["target_stack"]["java"] == "17"
    assert result["target_stack"]["spring_boot"] == "3.5.14"
    assert result["project_kind"] == "shared_library"
    assert result["has_spring_boot_main"] is False
    assert result["has_rest_contracts"] is False
    assert result["has_juneau_contracts"] is False
    assert result["packaging"] == "jar"
    assert result["internal_dependencies_count"] == 0
    assert result["internal_dependencies"] == []
    assert "warnings" in result


def test_scan_root_pom_resolves_nested_primary_pom_from_project_root(tmp_path):
    module_root = tmp_path / "common-utils"
    module_root.mkdir(parents=True)
    _write_java_source(module_root, "com/example/NestedLibrary.java", "package com.example;\nclass NestedLibrary {}\n")
    (module_root / "pom.xml").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
    <project xmlns="http://maven.apache.org/POM/4.0.0">
        <properties>
            <java.version>11</java.version>
            <spring-boot.version>2.1.6.RELEASE</spring-boot.version>
        </properties>
    </project>
    """,
        encoding="utf-8",
    )

    result = scan_root_pom(str(tmp_path))

    assert result["source_stack"]["java"] == "11"
    assert result["source_stack"]["spring_boot"] == "2.1.6.RELEASE"
    assert result["source_stack"]["build_tool"] == "maven"
    assert any("Resolved primary Maven project POM" in warning for warning in result["warnings"])


def test_scan_root_pom_prefers_parent_boot_version(tmp_path):
    fake_pom = tmp_path / "pom.xml"
    _write_java_source(tmp_path, "com/example/App.java", "package com.example;\nclass App {}\n")
    fake_pom.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
    <project xmlns="http://maven.apache.org/POM/4.0.0">
        <parent>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-parent</artifactId>
            <version>2.7.18</version>
        </parent>
        <properties>
            <spring-boot.version>2.6.9</spring-boot.version>
            <java.version>11</java.version>
        </properties>
        <dependencyManagement>
            <dependencies>
                <dependency>
                    <groupId>org.springframework.boot</groupId>
                    <artifactId>spring-boot-dependencies</artifactId>
                    <version>2.5.14</version>
                    <type>pom</type>
                    <scope>import</scope>
                </dependency>
            </dependencies>
        </dependencyManagement>
    </project>
    """,
        encoding="utf-8",
    )

    result = scan_root_pom(str(fake_pom))

    assert result["source_stack"]["spring_boot"] == "2.7.18"


@pytest.mark.parametrize("property_name", ["spring-boot.version", "spring.boot.version", "springBoot.version"])
def test_scan_root_pom_detects_property_boot_version(tmp_path, property_name):
    fake_pom = tmp_path / "pom.xml"
    _write_java_source(tmp_path, "com/example/Props.java", "package com.example;\nclass Props {}\n")
    fake_pom.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
    <project xmlns="http://maven.apache.org/POM/4.0.0">
        <properties>
            <java.version>11</java.version>
            <{property_name}>2.1.6.RELEASE</{property_name}>
        </properties>
    </project>
    """,
        encoding="utf-8",
    )

    result = scan_root_pom(str(fake_pom))

    assert result["source_stack"]["spring_boot"] == "2.1.6.RELEASE"


def test_scan_root_pom_detects_dependency_management_boot_version(tmp_path):
    fake_pom = tmp_path / "pom.xml"
    _write_java_source(tmp_path, "com/example/Bom.java", "package com.example;\nclass Bom {}\n")
    fake_pom.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
    <project xmlns="http://maven.apache.org/POM/4.0.0">
        <properties>
            <java.version>11</java.version>
            <boot.bom.version>2.1.6.RELEASE</boot.bom.version>
        </properties>
        <dependencyManagement>
            <dependencies>
                <dependency>
                    <groupId>org.springframework.boot</groupId>
                    <artifactId>spring-boot-dependencies</artifactId>
                    <version>${boot.bom.version}</version>
                    <type>pom</type>
                    <scope>import</scope>
                </dependency>
            </dependencies>
        </dependencyManagement>
    </project>
    """,
        encoding="utf-8",
    )

    result = scan_root_pom(str(fake_pom))

    assert result["source_stack"]["spring_boot"] == "2.1.6.RELEASE"


def test_scan_root_pom_detects_explicit_dependency_boot_version(tmp_path):
    fake_pom = tmp_path / "pom.xml"
    _write_java_source(tmp_path, "com/example/Web.java", "package com.example;\nclass Web {}\n")
    fake_pom.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
    <project xmlns="http://maven.apache.org/POM/4.0.0">
        <properties>
            <java.version>11</java.version>
            <boot.version>2.1.6.RELEASE</boot.version>
        </properties>
        <dependencies>
            <dependency>
                <groupId>org.springframework.boot</groupId>
                <artifactId>spring-boot-starter-web</artifactId>
                <version>${boot.version}</version>
            </dependency>
        </dependencies>
    </project>
    """,
        encoding="utf-8",
    )

    result = scan_root_pom(str(fake_pom))

    assert result["source_stack"]["spring_boot"] == "2.1.6.RELEASE"


def test_scan_root_pom_reports_unknown_without_boot_signal(tmp_path):
    fake_pom = tmp_path / "pom.xml"
    _write_java_source(tmp_path, "com/example/PlainLibrary.java", "package com.example;\nclass PlainLibrary {}\n")
    fake_pom.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
    <project xmlns="http://maven.apache.org/POM/4.0.0">
        <properties>
            <java.version>17</java.version>
        </properties>
        <dependencies>
            <dependency>
                <groupId>org.springframework</groupId>
                <artifactId>spring-context</artifactId>
                <version>5.3.39</version>
            </dependency>
        </dependencies>
    </project>
    """,
        encoding="utf-8",
    )

    result = scan_root_pom(str(fake_pom))

    assert result["source_stack"]["spring_boot"] == "unknown"
    assert result["project_kind"] == "shared_library"


def test_scan_root_pom_uses_profile_target_and_boot4_warnings(tmp_path):
    fake_pom = tmp_path / "pom.xml"
    _write_java_source(tmp_path, "com/example/Boot4Risk.java", "package com.example;\nclass Boot4Risk {}\n")
    fake_pom.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
    <project xmlns="http://maven.apache.org/POM/4.0.0">
        <parent>
            <version>2.7.18</version>
        </parent>
        <properties>
            <java.version>1.8</java.version>
        </properties>
    </project>
    """,
        encoding="utf-8",
    )

    result = scan_root_pom(
        str(fake_pom),
        target_stack={
            "java": "21",
            "spring_boot": "4.0.0",
            "spring_framework": "7.x",
            "build": "maven",
        },
    )

    assert result["target_stack"]["java"] == "21"
    assert result["target_stack"]["spring_boot"] == "4.0.0"
    assert result["target_stack"]["spring_framework"] == "7.x"
    assert any("Spring Framework 7" in warning for warning in result["warnings"])
    assert any("Servlet 6.1" in warning for warning in result["warnings"])


def test_scan_root_pom_parse_failure_keeps_analysis_contract(tmp_path):
    fake_pom = tmp_path / "pom.xml"
    fake_pom.write_text("<project>", encoding="utf-8")

    result = scan_root_pom(str(fake_pom), target_stack={"java": "21", "spring_boot": "4.0.0"})

    assert result["source_stack"] == {
        "java": "unknown",
        "spring_boot": "unknown",
        "build_tool": "maven",
    }
    assert result["target_stack"]["java"] == "21"
    assert result["target_stack"]["spring_boot"] == "4.0.0"
    assert result["project_structure"]["module_count"] == 0
    assert result["internal_dependencies_count"] == 0
    assert result["internal_dependencies"] == []
    assert any("Unable to parse root pom.xml" in warning for warning in result["warnings"])


def test_scan_root_pom_classifies_spring_boot_application(tmp_path):
    fake_pom = tmp_path / "pom.xml"
    _write_java_source(
        tmp_path,
        "com/example/Application.java",
        """package com.example;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class Application {
    public static void main(String[] args) {
        SpringApplication.run(Application.class, args);
    }
}
""",
    )
    fake_pom.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
    <project xmlns="http://maven.apache.org/POM/4.0.0">
        <packaging>jar</packaging>
    </project>
    """,
        encoding="utf-8",
    )

    result = scan_root_pom(str(fake_pom))

    assert result["project_kind"] == "spring_boot_application"
    assert result["has_spring_boot_main"] is True
    assert result["has_rest_contracts"] is False
    assert result["has_juneau_contracts"] is False
    assert result["packaging"] == "jar"


def test_scan_root_pom_classifies_plain_shared_library(tmp_path):
    fake_pom = tmp_path / "pom.xml"
    _write_java_source(tmp_path, "com/example/dto/CustomerDto.java", "package com.example.dto;\npublic record CustomerDto(String id) {}\n")
    fake_pom.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
    <project xmlns="http://maven.apache.org/POM/4.0.0">
        <packaging>jar</packaging>
    </project>
    """,
        encoding="utf-8",
    )

    result = scan_root_pom(str(fake_pom))

    assert result["project_kind"] == "shared_library"
    assert result["has_spring_boot_main"] is False
    assert result["has_rest_contracts"] is False
    assert result["has_juneau_contracts"] is False
    assert result["packaging"] == "jar"


def test_scan_root_pom_classifies_spring_rest_contract_library(tmp_path):
    fake_pom = tmp_path / "pom.xml"
    _write_java_source(
        tmp_path,
        "com/example/contract/CustomerApi.java",
        """package com.example.contract;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;

@RequestMapping("/customers")
public interface CustomerApi {
    @GetMapping("/{id}")
    String getCustomer();
}
""",
    )
    fake_pom.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
    <project xmlns="http://maven.apache.org/POM/4.0.0">
        <packaging>jar</packaging>
    </project>
    """,
        encoding="utf-8",
    )

    result = scan_root_pom(str(fake_pom))

    assert result["project_kind"] == "contract_library"
    assert result["has_spring_boot_main"] is False
    assert result["has_rest_contracts"] is True
    assert result["has_juneau_contracts"] is False
    assert result["packaging"] == "jar"


def test_scan_root_pom_classifies_juneau_contract_library(tmp_path):
    fake_pom = tmp_path / "pom.xml"
    _write_java_source(
        tmp_path,
        "com/example/contract/RemoteContract.java",
        """package com.example.contract;
import org.apache.juneau.http.annotation.RemoteResource;

@RemoteResource(path="/remote")
public interface RemoteContract {
}
""",
    )
    fake_pom.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
    <project xmlns="http://maven.apache.org/POM/4.0.0">
        <packaging>jar</packaging>
    </project>
    """,
        encoding="utf-8",
    )

    result = scan_root_pom(str(fake_pom))

    assert result["project_kind"] == "contract_library"
    assert result["has_spring_boot_main"] is False
    assert result["has_rest_contracts"] is False
    assert result["has_juneau_contracts"] is True
    assert result["packaging"] == "jar"


def test_scan_root_pom_classifies_unknown_minimal_project(tmp_path):
    fake_pom = tmp_path / "pom.xml"
    fake_pom.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
    <project xmlns="http://maven.apache.org/POM/4.0.0">
        <packaging>pom</packaging>
    </project>
    """,
        encoding="utf-8",
    )

    result = scan_root_pom(str(fake_pom))

    assert result["project_kind"] == "unknown"
    assert result["has_spring_boot_main"] is False
    assert result["has_rest_contracts"] is False
    assert result["has_juneau_contracts"] is False
    assert result["packaging"] == "pom"


def test_scan_root_pom_reports_no_internal_dependencies(tmp_path):
    fake_pom = tmp_path / "pom.xml"
    _write_java_source(tmp_path, "com/example/App.java", "package com.example;\nclass App {}\n")
    fake_pom.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
    <project xmlns="http://maven.apache.org/POM/4.0.0">
        <dependencies>
            <dependency>
                <groupId>org.springframework.boot</groupId>
                <artifactId>spring-boot-starter</artifactId>
                <version>2.7.18</version>
            </dependency>
        </dependencies>
    </project>
    """,
        encoding="utf-8",
    )

    result = scan_root_pom(str(fake_pom))

    assert result["internal_dependencies_count"] == 0
    assert result["internal_dependencies"] == []


def test_scan_root_pom_detects_internal_dependency_with_property_placeholder_version(tmp_path):
    fake_pom = tmp_path / "pom.xml"
    _write_java_source(tmp_path, "com/example/App.java", "package com.example;\nclass App {}\n")
    fake_pom.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
    <project xmlns="http://maven.apache.org/POM/4.0.0">
        <properties>
            <msa-dto.version>1.2.3</msa-dto.version>
        </properties>
        <dependencies>
            <dependency>
                <groupId>com.total.corp</groupId>
                <artifactId>msa-dto</artifactId>
                <version>${msa-dto.version}</version>
            </dependency>
        </dependencies>
    </project>
    """,
        encoding="utf-8",
    )

    result = scan_root_pom(str(fake_pom))

    assert result["internal_dependencies_count"] == 1
    assert result["internal_dependencies"] == [
        {
            "groupId": "com.total.corp",
            "artifactId": "msa-dto",
            "version": "${msa-dto.version}",
            "scope": "compile",
            "optional": False,
            "source": "pom",
            "classification": "internal_candidate",
        }
    ]


def test_scan_root_pom_detects_multiple_internal_dependencies(tmp_path):
    fake_pom = tmp_path / "pom.xml"
    _write_java_source(tmp_path, "com/example/App.java", "package com.example;\nclass App {}\n")
    fake_pom.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
    <project xmlns="http://maven.apache.org/POM/4.0.0">
        <dependencies>
            <dependency>
                <groupId>com.total.corp</groupId>
                <artifactId>platform-bom-client</artifactId>
                <version>1.0.0</version>
            </dependency>
            <dependency>
                <groupId>com.total.corp.foundation</groupId>
                <artifactId>contract-api</artifactId>
                <version>2.0.0</version>
            </dependency>
            <dependency>
                <groupId>org.springframework</groupId>
                <artifactId>spring-core</artifactId>
                <version>5.3.39</version>
            </dependency>
        </dependencies>
    </project>
    """,
        encoding="utf-8",
    )

    result = scan_root_pom(str(fake_pom))

    assert result["internal_dependencies_count"] == 2
    assert [item["artifactId"] for item in result["internal_dependencies"]] == [
        "platform-bom-client",
        "contract-api",
    ]


def test_scan_root_pom_ignores_external_dependencies_for_internal_detection(tmp_path):
    fake_pom = tmp_path / "pom.xml"
    _write_java_source(tmp_path, "com/example/App.java", "package com.example;\nclass App {}\n")
    fake_pom.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
    <project xmlns="http://maven.apache.org/POM/4.0.0">
        <dependencies>
            <dependency>
                <groupId>org.apache.commons</groupId>
                <artifactId>commons-lang3</artifactId>
                <version>3.17.0</version>
            </dependency>
            <dependency>
                <groupId>org.springframework.boot</groupId>
                <artifactId>spring-boot-starter-web</artifactId>
                <version>2.7.18</version>
            </dependency>
        </dependencies>
    </project>
    """,
        encoding="utf-8",
    )

    result = scan_root_pom(str(fake_pom))

    assert result["internal_dependencies_count"] == 0
    assert result["internal_dependencies"] == []


def test_scan_root_pom_preserves_scope_and_optional_for_internal_dependency(tmp_path):
    fake_pom = tmp_path / "pom.xml"
    _write_java_source(tmp_path, "com/example/App.java", "package com.example;\nclass App {}\n")
    fake_pom.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
    <project xmlns="http://maven.apache.org/POM/4.0.0">
        <dependencies>
            <dependency>
                <groupId>com.total.corp</groupId>
                <artifactId>shared-contract</artifactId>
                <version>3.4.5</version>
                <scope>test</scope>
                <optional>true</optional>
            </dependency>
        </dependencies>
    </project>
    """,
        encoding="utf-8",
    )

    result = scan_root_pom(str(fake_pom))

    assert result["internal_dependencies"] == [
        {
            "groupId": "com.total.corp",
            "artifactId": "shared-contract",
            "version": "3.4.5",
            "scope": "test",
            "optional": True,
            "source": "pom",
            "classification": "internal_candidate",
        }
    ]


def test_scan_root_pom_accepts_custom_internal_group_prefix(tmp_path):
    fake_pom = tmp_path / "pom.xml"
    _write_java_source(tmp_path, "com/example/App.java", "package com.example;\nclass App {}\n")
    fake_pom.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
    <project xmlns="http://maven.apache.org/POM/4.0.0">
        <dependencies>
            <dependency>
                <groupId>com.cgi.platform</groupId>
                <artifactId>core-contract</artifactId>
                <version>9.9.9</version>
            </dependency>
        </dependencies>
    </project>
    """,
        encoding="utf-8",
    )

    default_result = scan_root_pom(str(fake_pom))
    custom_result = scan_root_pom_with_prefixes(str(fake_pom), internal_group_prefixes=("com.cgi",))

    assert default_result["internal_dependencies_count"] == 0
    assert custom_result["internal_dependencies_count"] == 1
    assert custom_result["internal_dependencies"][0]["artifactId"] == "core-contract"


def test_scan_root_pom_internal_detection_is_not_artifactid_specific(tmp_path):
    fake_pom = tmp_path / "pom.xml"
    _write_java_source(tmp_path, "com/example/App.java", "package com.example;\nclass App {}\n")
    fake_pom.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
    <project xmlns="http://maven.apache.org/POM/4.0.0">
        <dependencies>
            <dependency>
                <groupId>com.total.corp</groupId>
                <artifactId>customer-platform-starter</artifactId>
                <version>4.2.0</version>
            </dependency>
        </dependencies>
    </project>
    """,
        encoding="utf-8",
    )

    result = scan_root_pom(str(fake_pom))

    assert result["internal_dependencies_count"] == 1
    assert result["internal_dependencies"][0]["artifactId"] == "customer-platform-starter"
