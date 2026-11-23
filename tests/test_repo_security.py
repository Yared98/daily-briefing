import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import requests

import collectors.repo_security as repo_sec
from collectors import Section


def _md(result):
    return result.markdown if isinstance(result, Section) else result


class TestRepoSecurityOSV(unittest.TestCase):
    def setUp(self):
        repo_sec._OSV_VULN_CACHE.clear()

    def test_version_read_from_package_lock_v3_instead_of_package_json(self):
        """Versão lida do package-lock.json (v3) em vez do package.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_json = os.path.join(tmpdir, "package.json")
            lock_json = os.path.join(tmpdir, "package-lock.json")

            with open(pkg_json, "w", encoding="utf-8") as f:
                json.dump({"dependencies": {"vite": "^5.0.0"}}, f)

            with open(lock_json, "w", encoding="utf-8") as f:
                json.dump({
                    "lockfileVersion": 3,
                    "packages": {
                        "": {"name": "app", "version": "1.0.0"},
                        "node_modules/vite": {"version": "5.0.10"}
                    }
                }, f)

            app_cfg = {
                "supported_projects": [{
                    "name": "MyProject",
                    "pkg": pkg_json
                }]
            }

            def mock_post(url, json=None, timeout=None):
                mock_resp = MagicMock()
                mock_resp.json.return_value = {
                    "results": [
                        {"vulns": [{"id": "GHSA-1234"}]}
                    ]
                }
                return mock_resp

            def mock_get(url, timeout=None):
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {
                    "id": "GHSA-1234",
                    "database_specific": {"severity": "MODERATE"},
                    "affected": [{
                        "package": {"name": "vite", "ecosystem": "npm"},
                        "ranges": [{
                            "events": [{"fixed": "5.0.12"}]
                        }]
                    }]
                }
                return mock_resp

            with patch("requests.post", side_effect=mock_post) as p_post, \
                 patch("requests.get", side_effect=mock_get):
                out = _md(repo_sec.collect({}, app_cfg))

                # Verifica que a query usou a versão instalada no lockfile (5.0.10), e não ^5.0.0 ou 5.0.0
                call_args = p_post.call_args[1]["json"]["queries"]
                self.assertEqual(call_args[0]["version"], "5.0.10")

                # Verifica o formato da linha com a versão 5.0.10
                self.assertIn("`vite` 5.0.10:", out)
                self.assertNotIn("`vite` 5.0.0:", out)

    def test_version_read_from_package_lock_v1(self):
        """Versão lida do package-lock.json (v1) quando não há 'packages'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_json = os.path.join(tmpdir, "package.json")
            lock_json = os.path.join(tmpdir, "package-lock.json")

            with open(pkg_json, "w", encoding="utf-8") as f:
                json.dump({"dependencies": {"lodash": "^4.17.0"}}, f)

            with open(lock_json, "w", encoding="utf-8") as f:
                json.dump({
                    "lockfileVersion": 1,
                    "dependencies": {
                        "lodash": {"version": "4.17.21"}
                    }
                }, f)

            app_cfg = {
                "supported_projects": [{
                    "name": "AppV1",
                    "pkg": pkg_json
                }]
            }

            with patch("requests.post") as p_post, patch("requests.get") as p_get:
                p_post.return_value.json.return_value = {"results": [{"vulns": []}]}
                repo_sec.collect({}, app_cfg)
                queries = p_post.call_args[1]["json"]["queries"]
                self.assertEqual(queries[0]["version"], "4.17.21")

    def test_no_lockfile_fallback_to_declared_minimum_version(self):
        """Sem package-lock.json, mantém comportamento atual (versão mínima declarada)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_json = os.path.join(tmpdir, "package.json")
            with open(pkg_json, "w", encoding="utf-8") as f:
                json.dump({"dependencies": {"react": "^18.2.0"}}, f)

            app_cfg = {
                "supported_projects": [{
                    "name": "NoLockApp",
                    "pkg": pkg_json
                }]
            }

            with patch("requests.post") as p_post, patch("requests.get") as p_get:
                p_post.return_value.json.return_value = {"results": [{"vulns": []}]}
                repo_sec.collect({}, app_cfg)
                queries = p_post.call_args[1]["json"]["queries"]
                self.assertEqual(queries[0]["version"], "18.2.0")

    def test_dev_dependencies_generates_dev_tag_and_warning_even_with_high(self):
        """devDependencies gera '(dev)' e ⚠️ mesmo com HIGH."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_json = os.path.join(tmpdir, "package.json")
            with open(pkg_json, "w", encoding="utf-8") as f:
                json.dump({"devDependencies": {"vitest": "1.0.0"}}, f)

            app_cfg = {
                "supported_projects": [{
                    "name": "DevTest",
                    "pkg": pkg_json
                }]
            }

            def mock_post(url, json=None, timeout=None):
                mock_resp = MagicMock()
                mock_resp.json.return_value = {
                    "results": [{"vulns": [{"id": "GHSA-high-dev"}]}]
                }
                return mock_resp

            def mock_get(url, timeout=None):
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {
                    "id": "GHSA-high-dev",
                    "database_specific": {"severity": "HIGH"},
                    "affected": [{
                        "package": {"name": "vitest", "ecosystem": "npm"},
                        "ranges": [{"events": [{"fixed": "1.0.4"}]}]
                    }]
                }
                return mock_resp

            with patch("requests.post", side_effect=mock_post), \
                 patch("requests.get", side_effect=mock_get):
                out = _md(repo_sec.collect({}, app_cfg))

                # Deve conter emoji ⚠️, tag (dev) e gravidade máxima HIGH
                self.assertIn("⚠️ **[DevTest]** `vitest` 1.0.0 (dev): 1 vulnerabilidade(s), gravidade máxima HIGH; corrigido em 1.0.4 (GHSA-high-dev)", out)
                # Não deve conter 🚨
                self.assertNotIn("🚨", out)
                # Status no topo de menor risco
                self.assertIn("⚠️ **Vulnerabilidades de menor risco:** 1 pacote(s) com alertas (gravidade baixa/média ou desconhecida, ou só de desenvolvimento).", out)
                self.assertNotIn("🚨 **Atenção:**", out)

    def test_normal_dependency_with_high_generates_alert_and_atencao_status(self):
        """Dependência normal com HIGH gera 🚨 e o status 'Atenção'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_json = os.path.join(tmpdir, "package.json")
            with open(pkg_json, "w", encoding="utf-8") as f:
                json.dump({"dependencies": {"express": "4.17.1"}}, f)

            app_cfg = {
                "supported_projects": [{
                    "name": "ProdTest",
                    "pkg": pkg_json
                }]
            }

            def mock_post(url, json=None, timeout=None):
                mock_resp = MagicMock()
                mock_resp.json.return_value = {
                    "results": [{"vulns": [{"id": "GHSA-high-prod"}]}]
                }
                return mock_resp

            def mock_get(url, timeout=None):
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {
                    "id": "GHSA-high-prod",
                    "database_specific": {"severity": "HIGH"},
                    "affected": [{
                        "package": {"name": "express", "ecosystem": "npm"},
                        "ranges": [{"events": [{"fixed": "4.18.2"}]}]
                    }]
                }
                return mock_resp

            with patch("requests.post", side_effect=mock_post), \
                 patch("requests.get", side_effect=mock_get):
                out = _md(repo_sec.collect({}, app_cfg))

                # Deve conter 🚨, não ter (dev)
                self.assertIn("🚨 **[ProdTest]** `express` 4.17.1: 1 vulnerabilidade(s), gravidade máxima HIGH; corrigido em 4.18.2 (GHSA-high-prod)", out)
                self.assertNotIn("(dev)", out)
                # Status no topo 'Atenção'
                self.assertIn("🚨 **Atenção:** 1 alerta(s) de vulnerabilidade identificado(s):", out)

    def test_fix_version_largest_of_smallest_fixed_above_installed(self):
        """Versão que corrige = maior dos menores fixed acima da instalada."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_json = os.path.join(tmpdir, "package.json")
            with open(pkg_json, "w", encoding="utf-8") as f:
                json.dump({"dependencies": {"foo": "1.0.0"}}, f)

            app_cfg = {
                "supported_projects": [{
                    "name": "ProjMulti",
                    "pkg": pkg_json
                }]
            }

            def mock_post(url, json=None, timeout=None):
                mock_resp = MagicMock()
                mock_resp.json.return_value = {
                    "results": [{"vulns": [{"id": "GHSA-1"}, {"id": "GHSA-2"}]}]
                }
                return mock_resp

            # Vuln 1: fixed em 0.9.0 (menor), 1.0.5 e 1.2.0 -> menor > 1.0.0 é 1.0.5
            # Vuln 2: fixed em 1.1.0 e 2.0.0 -> menor > 1.0.0 é 1.1.0
            # Maior entre 1.0.5 e 1.1.0 é 1.1.0
            def mock_get(url, timeout=None):
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                if "GHSA-1" in url:
                    mock_resp.json.return_value = {
                        "id": "GHSA-1",
                        "database_specific": {"severity": "LOW"},
                        "affected": [{
                            "package": {"name": "foo", "ecosystem": "npm"},
                            "ranges": [{"events": [
                                {"fixed": "0.9.0"},
                                {"fixed": "1.0.5"},
                                {"fixed": "1.2.0"}
                            ]}]
                        }]
                    }
                else:
                    mock_resp.json.return_value = {
                        "id": "GHSA-2",
                        "database_specific": {"severity": "MODERATE"},
                        "affected": [{
                            "package": {"name": "foo", "ecosystem": "npm"},
                            "ranges": [{"events": [
                                {"fixed": "1.1.0"},
                                {"fixed": "2.0.0"}
                            ]}]
                        }]
                    }
                return mock_resp

            with patch("requests.post", side_effect=mock_post), \
                 patch("requests.get", side_effect=mock_get):
                out = _md(repo_sec.collect({}, app_cfg))

                self.assertIn("corrigido em 1.1.0", out)
                self.assertIn("gravidade máxima MODERATE", out)

    def test_vuln_without_fixed_generates_sem_correcao_publicada(self):
        """Vuln sem fixed gera 'sem correção publicada'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_json = os.path.join(tmpdir, "package.json")
            with open(pkg_json, "w", encoding="utf-8") as f:
                json.dump({"dependencies": {"bar": "1.0.0"}}, f)

            app_cfg = {
                "supported_projects": [{
                    "name": "ProjNoFix",
                    "pkg": pkg_json
                }]
            }

            def mock_post(url, json=None, timeout=None):
                mock_resp = MagicMock()
                mock_resp.json.return_value = {
                    "results": [{"vulns": [{"id": "GHSA-nofix"}]}]
                }
                return mock_resp

            def mock_get(url, timeout=None):
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {
                    "id": "GHSA-nofix",
                    "database_specific": {"severity": "LOW"},
                    "affected": [{
                        "package": {"name": "bar", "ecosystem": "npm"},
                        "ranges": [{"events": [{"introduced": "0"}]}]  # Sem fixed
                    }]
                }
                return mock_resp

            with patch("requests.post", side_effect=mock_post), \
                 patch("requests.get", side_effect=mock_get):
                out = _md(repo_sec.collect({}, app_cfg))

                self.assertIn("sem correção publicada", out)
                self.assertNotIn("corrigido em", out)

    def test_one_vuln_fixed_and_one_unfixed_generates_sem_correcao_publicada(self):
        """Se uma das vulnerabilidades não tiver fixed, mostra 'sem correção publicada'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_json = os.path.join(tmpdir, "package.json")
            with open(pkg_json, "w", encoding="utf-8") as f:
                json.dump({"dependencies": {"baz": "1.0.0"}}, f)

            app_cfg = {
                "supported_projects": [{
                    "name": "ProjPartialFix",
                    "pkg": pkg_json
                }]
            }

            def mock_post(url, json=None, timeout=None):
                mock_resp = MagicMock()
                mock_resp.json.return_value = {
                    "results": [{"vulns": [{"id": "GHSA-fix"}, {"id": "GHSA-nofix"}]}]
                }
                return mock_resp

            def mock_get(url, timeout=None):
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                if "GHSA-fix" in url:
                    mock_resp.json.return_value = {
                        "id": "GHSA-fix",
                        "database_specific": {"severity": "LOW"},
                        "affected": [{
                            "package": {"name": "baz", "ecosystem": "npm"},
                            "ranges": [{"events": [{"fixed": "1.0.1"}]}]
                        }]
                    }
                else:
                    mock_resp.json.return_value = {
                        "id": "GHSA-nofix",
                        "database_specific": {"severity": "LOW"},
                        "affected": [{
                            "package": {"name": "baz", "ecosystem": "npm"},
                            "ranges": [{"events": [{"introduced": "0"}]}]
                        }]
                    }
                return mock_resp

            with patch("requests.post", side_effect=mock_post), \
                 patch("requests.get", side_effect=mock_get):
                out = _md(repo_sec.collect({}, app_cfg))

                self.assertIn("sem correção publicada", out)

    def test_get_detail_failure_does_not_crash_and_yields_unknown_severity(self):
        """Falha no GET de detalhe não derruba: gravidade UNKNOWN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_json = os.path.join(tmpdir, "package.json")
            with open(pkg_json, "w", encoding="utf-8") as f:
                json.dump({"dependencies": {"failpkg": "2.0.0"}}, f)

            app_cfg = {
                "supported_projects": [{
                    "name": "FailGetProj",
                    "pkg": pkg_json
                }]
            }

            def mock_post(url, json=None, timeout=None):
                mock_resp = MagicMock()
                mock_resp.json.return_value = {
                    "results": [{"vulns": [{"id": "GHSA-timeout"}]}]
                }
                return mock_resp

            def mock_get(url, timeout=None):
                raise requests.RequestException("OSV api timed out")

            with patch("requests.post", side_effect=mock_post), \
                 patch("requests.get", side_effect=mock_get):
                out = _md(repo_sec.collect({}, app_cfg))

                self.assertIn("gravidade máxima UNKNOWN", out)
                self.assertIn("versão que corrige não verificada", out)
                self.assertIn("⚠️ **[FailGetProj]** `failpkg` 2.0.0: 1 vulnerabilidade(s)", out)

    def test_cache_and_max_60_calls_per_run(self):
        """Usa cache no nível do módulo e limita a 60 chamadas por execução."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_json = os.path.join(tmpdir, "package.json")
            with open(pkg_json, "w", encoding="utf-8") as f:
                json.dump({"dependencies": {"bigpkg": "1.0.0"}}, f)

            app_cfg = {
                "supported_projects": [{
                    "name": "CacheProj",
                    "pkg": pkg_json
                }]
            }

            vuln_ids = [f"GHSA-test-{i}" for i in range(70)]

            def mock_post(url, json=None, timeout=None):
                mock_resp = MagicMock()
                mock_resp.json.return_value = {
                    "results": [{"vulns": [{"id": vid} for vid in vuln_ids]}]
                }
                return mock_resp

            get_call_count = 0

            def mock_get(url, timeout=None):
                nonlocal get_call_count
                get_call_count += 1
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {
                    "id": "some-id",
                    "database_specific": {"severity": "LOW"},
                    "affected": []
                }
                return mock_resp

            with patch("requests.post", side_effect=mock_post), \
                 patch("requests.get", side_effect=mock_get):
                repo_sec.collect({}, app_cfg)

                # Deve ter chamado no máximo 60 vezes
                self.assertEqual(get_call_count, 60)

            # Nova execução usando os mesmos IDs que já estão em cache não deve disparar novas chamadas para esses IDs
            get_call_count = 0
            with patch("requests.post", side_effect=mock_post), \
                 patch("requests.get", side_effect=mock_get):
                cached_ids = vuln_ids[:60]
                def mock_post_cached(url, json=None, timeout=None):
                    mock_resp = MagicMock()
                    mock_resp.json.return_value = {
                        "results": [{"vulns": [{"id": vid} for vid in cached_ids]}]
                    }
                    return mock_resp

                with patch("requests.post", side_effect=mock_post_cached):
                    repo_sec.collect({}, app_cfg)
                    self.assertEqual(get_call_count, 0)

    def test_pypi_dependencies_always_dev_false(self):
        """Para PyPI, dev é sempre False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            req_file = os.path.join(tmpdir, "requirements.txt")
            with open(req_file, "w", encoding="utf-8") as f:
                f.write("django==4.0.0\n")

            app_cfg = {
                "supported_projects": [{
                    "name": "PyProj",
                    "pkg": req_file
                }]
            }

            def mock_post(url, json=None, timeout=None):
                mock_resp = MagicMock()
                mock_resp.json.return_value = {
                    "results": [{"vulns": [{"id": "GHSA-django"}]}]
                }
                return mock_resp

            def mock_get(url, timeout=None):
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {
                    "id": "GHSA-django",
                    "database_specific": {"severity": "CRITICAL"},
                    "affected": [{
                        "package": {"name": "django", "ecosystem": "PyPI"},
                        "ranges": [{"events": [{"fixed": "4.0.10"}]}]
                    }]
                }
                return mock_resp

            with patch("requests.post", side_effect=mock_post), \
                 patch("requests.get", side_effect=mock_get):
                out = _md(repo_sec.collect({}, app_cfg))

                # PyPI não tem dev=True, e com CRITICAL gera 🚨
                self.assertIn("🚨 **[PyProj]** `django` 4.0.0: 1 vulnerabilidade(s), gravidade máxima CRITICAL; corrigido em 4.0.10 (GHSA-django)", out)
                self.assertNotIn("(dev)", out)
                self.assertIn("🚨 **Atenção:** 1 alerta(s) de vulnerabilidade identificado(s):", out)

    def test_package_in_both_dependencies_and_dev_dependencies_is_not_dev(self):
        """Pacote listado em dependencies e devDependencies não é dev-only."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_json = os.path.join(tmpdir, "package.json")
            with open(pkg_json, "w", encoding="utf-8") as f:
                json.dump({
                    "dependencies": {"shared": "1.0.0"},
                    "devDependencies": {"shared": "1.0.0"}
                }, f)

            app_cfg = {
                "supported_projects": [{
                    "name": "BothProj",
                    "pkg": pkg_json
                }]
            }

            def mock_post(url, json=None, timeout=None):
                mock_resp = MagicMock()
                mock_resp.json.return_value = {
                    "results": [{"vulns": [{"id": "GHSA-shared"}]}]
                }
                return mock_resp

            def mock_get(url, timeout=None):
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {
                    "id": "GHSA-shared",
                    "database_specific": {"severity": "HIGH"},
                    "affected": [{
                        "package": {"name": "shared", "ecosystem": "npm"},
                        "ranges": [{"events": [{"fixed": "1.0.1"}]}]
                    }]
                }
                return mock_resp

            with patch("requests.post", side_effect=mock_post), \
                 patch("requests.get", side_effect=mock_get):
                out = _md(repo_sec.collect({}, app_cfg))

                self.assertNotIn("(dev)", out)
                self.assertIn("🚨 **[BothProj]** `shared` 1.0.0: 1 vulnerabilidade(s)", out)

    def test_more_than_three_vuln_ids_formatting(self):
        """Mais de 3 IDs formata como: (ID-1, ID-2, ID-3 (+k))."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_json = os.path.join(tmpdir, "package.json")
            with open(pkg_json, "w", encoding="utf-8") as f:
                json.dump({"dependencies": {"manyvulns": "1.0.0"}}, f)

            app_cfg = {
                "supported_projects": [{
                    "name": "ManyVulnsProj",
                    "pkg": pkg_json
                }]
            }

            def mock_post(url, json=None, timeout=None):
                mock_resp = MagicMock()
                mock_resp.json.return_value = {
                    "results": [{"vulns": [
                        {"id": "GHSA-1"},
                        {"id": "GHSA-2"},
                        {"id": "GHSA-3"},
                        {"id": "GHSA-4"},
                        {"id": "GHSA-5"},
                    ]}]
                }
                return mock_resp

            def mock_get(url, timeout=None):
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {
                    "id": "some-id",
                    "database_specific": {"severity": "LOW"},
                    "affected": [{
                        "package": {"name": "manyvulns", "ecosystem": "npm"},
                        "ranges": [{"events": [{"fixed": "1.0.1"}]}]
                    }]
                }
                return mock_resp

            with patch("requests.post", side_effect=mock_post), \
                 patch("requests.get", side_effect=mock_get):
                out = _md(repo_sec.collect({}, app_cfg))

                self.assertIn("(GHSA-1, GHSA-2, GHSA-3 (+2))", out)

    def test_low_or_moderate_normal_dep_generates_warning_emoji_and_status(self):
        """Dependência normal com gravidade LOW/MODERATE gera ⚠️ e status 'Vulnerabilidades de menor risco'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_json = os.path.join(tmpdir, "package.json")
            with open(pkg_json, "w", encoding="utf-8") as f:
                json.dump({"dependencies": {"lowpkg": "1.0.0"}}, f)

            app_cfg = {
                "supported_projects": [{
                    "name": "LowProj",
                    "pkg": pkg_json
                }]
            }

            def mock_post(url, json=None, timeout=None):
                mock_resp = MagicMock()
                mock_resp.json.return_value = {
                    "results": [{"vulns": [{"id": "GHSA-low"}]}]
                }
                return mock_resp

            def mock_get(url, timeout=None):
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = {
                    "id": "GHSA-low",
                    "database_specific": {"severity": "MODERATE"},
                    "affected": [{
                        "package": {"name": "lowpkg", "ecosystem": "npm"},
                        "ranges": [{"events": [{"fixed": "1.0.2"}]}]
                    }]
                }
                return mock_resp

            with patch("requests.post", side_effect=mock_post), \
                 patch("requests.get", side_effect=mock_get):
                out = _md(repo_sec.collect({}, app_cfg))

                self.assertIn("⚠️ **[LowProj]** `lowpkg` 1.0.0: 1 vulnerabilidade(s), gravidade máxima MODERATE; corrigido em 1.0.2 (GHSA-low)", out)
                self.assertIn("⚠️ **Vulnerabilidades de menor risco:** 1 pacote(s) com alertas (gravidade baixa/média ou desconhecida, ou só de desenvolvimento).", out)
                self.assertNotIn("🚨", out)

    def test_check_errors_preserved_on_failure(self):
        """Falha na chamada do OSV.dev gera check_errors e status 'Verificação incompleta'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_json = os.path.join(tmpdir, "package.json")
            with open(pkg_json, "w", encoding="utf-8") as f:
                json.dump({"dependencies": {"anypkg": "1.0.0"}}, f)

            app_cfg = {
                "supported_projects": [{
                    "name": "ErrProj",
                    "pkg": pkg_json
                }]
            }

            with patch("requests.post", side_effect=requests.ConnectionError("Network down")):
                out = _md(repo_sec.collect({}, app_cfg))

                self.assertIn("⚠️ **Verificação incompleta:** nenhum alerta encontrado, mas algumas consultas falharam.", out)
                self.assertIn("⚠️ Não foi possível verificar: ErrProj (OSV.dev: ConnectionError)", out)

    def test_pyproject_toml_parsing(self):
        """Verifica leitura de dependências a partir de pyproject.toml."""
        with tempfile.TemporaryDirectory() as tmpdir:
            toml_path = os.path.join(tmpdir, "pyproject.toml")
            with open(toml_path, "w", encoding="utf-8") as f:
                f.write("""
[project]
dependencies = [
    "requests>=2.28.0",
]

[tool.poetry.dependencies]
python = "^3.11"
pydantic = "^2.0.0"
""")

            app_cfg = {
                "supported_projects": [{
                    "name": "TomlProj",
                    "pkg": toml_path
                }]
            }

            with patch("requests.post") as p_post:
                p_post.return_value.json.return_value = {"results": [{"vulns": []}, {"vulns": []}]}
                repo_sec.collect({}, app_cfg)
                queries = p_post.call_args[1]["json"]["queries"]
                pkg_names = [q["package"]["name"] for q in queries]
                self.assertIn("requests", pkg_names)
                self.assertIn("pydantic", pkg_names)
                self.assertNotIn("python", pkg_names)


    def _one_vuln(self, tmpdir, detail, post_ok=True):
        pkg_json = os.path.join(tmpdir, "package.json")
        with open(pkg_json, "w", encoding="utf-8") as f:
            json.dump({"dependencies": {"express": "4.17.1"}}, f)
        app_cfg = {"supported_projects": [{"name": "P", "pkg": pkg_json}]}

        def mock_post(url, json=None, timeout=None):
            if not post_ok:
                raise requests.exceptions.ConnectionError("offline")
            r = MagicMock()
            r.json.return_value = {"results": [{"vulns": [{"id": "GHSA-x"}]}]}
            return r

        def mock_get(url, timeout=None):
            r = MagicMock()
            if detail is None:
                r.status_code = 500
                r.raise_for_status.side_effect = requests.exceptions.HTTPError("500")
            else:
                r.status_code = 200
                r.json.return_value = detail
            return r

        with patch("requests.post", side_effect=mock_post), patch("requests.get", side_effect=mock_get):
            return repo_sec.collect({}, app_cfg)

    def test_faixa_git_nao_vira_versao(self):
        detail = {"id": "GHSA-x", "database_specific": {"severity": "HIGH"}, "affected": [{
            "package": {"name": "express", "ecosystem": "npm"},
            "ranges": [{"type": "GIT", "events": [{"fixed": "4c18a1f"}]},
                       {"type": "SEMVER", "events": [{"fixed": "4.18.2"}]}]}]}
        with tempfile.TemporaryDirectory() as tmpdir:
            out = _md(self._one_vuln(tmpdir, detail))
        self.assertIn("corrigido em 4.18.2", out)
        self.assertNotIn("4c18a1f", out)

    def test_detalhe_indisponivel_nao_afirma_sem_correcao(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = _md(self._one_vuln(tmpdir, None))
        self.assertIn("versão que corrige não verificada", out)
        self.assertNotIn("sem correção publicada", out)

    def test_metrica_de_historico(self):
        detail = {"id": "GHSA-x", "database_specific": {"severity": "LOW"}, "affected": []}
        with tempfile.TemporaryDirectory() as tmpdir:
            res = self._one_vuln(tmpdir, detail)
        self.assertIsInstance(res, Section)
        self.assertEqual(res.metrics["Pacotes vulneráveis"]["value"], ["P: express 4.17.1"])

    def test_verificacao_incompleta_nao_grava_metrica(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            res = self._one_vuln(tmpdir, None, post_ok=False)
        self.assertIn("Verificação incompleta", _md(res))
        self.assertEqual(getattr(res, "metrics", {}), {})


if __name__ == "__main__":
    unittest.main()
