import collections
import json
import os
import re
import subprocess
import requests

MAX_DEPS_PER_PROJECT = 50

# nome[extras] <operador> versão — usa a primeira versão citada (pino exato ou limite inferior),
# a mesma aproximação feita para o npm com `^`/`~`.
_PY_REQ_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(===|==|~=|>=)\s*([0-9][^,;\s]*)")


def _clean_version(raw: str) -> str:
    return raw.strip().lstrip("^~>=<! ").split(",")[0].strip()


def _npm_deps(path: str) -> list:
    with open(path, "r", encoding="utf-8") as pf:
        pkg_json = json.load(pf)
    deps = {**pkg_json.get("dependencies", {}), **pkg_json.get("devDependencies", {})}
    return [(name, _clean_version(ver)) for name, ver in deps.items() if isinstance(ver, str)]


def _parse_pep508(spec: str):
    match = _PY_REQ_RE.match(spec.split(";")[0])
    return (match.group(1), match.group(3)) if match else None


def _requirements_deps(path: str) -> list:
    deps = []
    with open(path, "r", encoding="utf-8") as rf:
        for line in rf:
            line = line.split(" #")[0].strip()
            if not line or line.startswith(("#", "-", "git+", "http")):
                continue
            parsed = _parse_pep508(line)
            if parsed:
                deps.append(parsed)
    return deps


def _pyproject_deps(path: str) -> list:
    import tomllib

    with open(path, "rb") as tf:
        data = tomllib.load(tf)
    deps = []
    for spec in data.get("project", {}).get("dependencies", []):
        parsed = _parse_pep508(spec)
        if parsed:
            deps.append(parsed)
    poetry = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
    for name, spec in poetry.items():
        if name.lower() == "python":
            continue
        version = spec.get("version", "") if isinstance(spec, dict) else str(spec)
        deps.append((name, _clean_version(version)))
    return deps


def _osv_queries(pkg_path: str) -> list:
    """Monta as consultas do OSV.dev a partir do manifesto (npm ou PyPI, pelo nome do arquivo)."""
    filename = os.path.basename(pkg_path).lower()
    if filename == "package.json":
        ecosystem, deps = "npm", _npm_deps(pkg_path)
    elif filename == "pyproject.toml":
        ecosystem, deps = "PyPI", _pyproject_deps(pkg_path)
    elif filename.startswith("requirements") and filename.endswith(".txt"):
        ecosystem, deps = "PyPI", _requirements_deps(pkg_path)
    else:
        return []
    return [
        {"package": {"name": name, "ecosystem": ecosystem}, "version": ver}
        for name, ver in deps[:MAX_DEPS_PER_PROJECT]
        if ver and ver[0].isdigit()
    ]


def collect(projects: list) -> str:
    """Monitora branch/commit recente e vulnerabilidades (Dependabot + OSV.dev) dos projetos."""
    if not projects:
        return "- *Nenhum repositório configurado em `supported_projects`.*"

    github_token = os.getenv("GITHUB_TOKEN", "")
    gh_headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "DailyBriefing-Security/1.0",
    }
    if github_token:
        gh_headers["Authorization"] = f"Bearer {github_token}"

    repo_lines = []
    vuln_alerts = []
    check_errors = []

    try:
        for proj in projects:
            p_name = proj["name"]
            p_path = proj.get("path")
            p_slug = proj.get("slug")
            p_branch = proj.get("branch", "main")

            if p_path and os.path.exists(p_path):
                try:
                    curr_branch = subprocess.check_output(
                        ["git", "-C", p_path, "branch", "--show-current"],
                        text=True,
                        stderr=subprocess.DEVNULL,
                    ).strip()
                    last_commit = subprocess.check_output(
                        ["git", "-C", p_path, "log", "-1", "--format=%h — %s (%cd)", "--date=relative"],
                        text=True,
                        stderr=subprocess.DEVNULL,
                    ).strip()
                    status_info = f"`{curr_branch}` • commit: {last_commit}"
                except Exception:
                    status_info = f"pasta encontrada, sem informação do git (branch esperada: `{p_branch}`)"
            elif p_slug:
                status_info = f"repositório `{p_slug}` (remoto)"
            else:
                status_info = "local não encontrado"

            repo_lines.append(f"- **{p_name}:** {status_info}")

            checked_via_gh = False
            if github_token and p_slug:
                try:
                    url_al = f"https://api.github.com/repos/{p_slug}/dependabot/alerts?state=open&severity=critical,high"
                    r_al = requests.get(url_al, headers=gh_headers, timeout=8)
                    if r_al.status_code == 200:
                        checked_via_gh = True
                        for al in r_al.json():
                            pkg_n = al.get("dependency", {}).get("package", {}).get("name", "Pacote")
                            sev = al.get("security_advisory", {}).get("severity", "high").upper()
                            cve = al.get("security_advisory", {}).get("cve_id") or al.get(
                                "security_advisory", {}
                            ).get("ghsa_id", "Alerta")
                            summary = al.get("security_advisory", {}).get("summary", "")[:90]
                            fix = al.get("security_vulnerability", {}).get("first_patched_version", {}).get(
                                "identifier", "N/D"
                            )
                            vuln_alerts.append(
                                f"🚨 **[{p_name}]** `{pkg_n}` ({sev} • {cve}): {summary}... _(Correção: {fix})_"
                            )
                except Exception as exc:
                    check_errors.append(f"{p_name} (Dependabot: {exc.__class__.__name__})")

            pkg_path = proj.get("pkg")
            if not checked_via_gh and pkg_path and os.path.exists(pkg_path):
                try:
                    queries = _osv_queries(pkg_path)
                    if queries:
                        resp_osv = requests.post(
                            "https://api.osv.dev/v1/querybatch", json={"queries": queries}, timeout=8
                        ).json()
                        pkg_vulns = collections.defaultdict(list)
                        for idx_q, r_osv in enumerate(resp_osv.get("results", [])):
                            for v in r_osv.get("vulns", []):
                                pkg_vulns[queries[idx_q]["package"]["name"]].append(v.get("id"))

                        for dep_n, v_ids in pkg_vulns.items():
                            cves_str = ", ".join(v_ids[:3]) + (f" (+{len(v_ids)-3})" if len(v_ids) > 3 else "")
                            vuln_alerts.append(
                                f"⚠️ **[{p_name}]** `{dep_n}`: {len(v_ids)} vulnerabilidade(s) conhecida(s) ({cves_str})"
                            )
                except Exception as exc:
                    check_errors.append(f"{p_name} (OSV.dev: {exc.__class__.__name__})")

        if vuln_alerts:
            status_badge = f"🚨 **Atenção:** {len(vuln_alerts)} alerta(s) de vulnerabilidade identificado(s):"
            alerts_text = "\n" + "\n".join(vuln_alerts)
        elif check_errors:
            # Uma consulta que falhou nunca pode ser reportada como "tudo seguro".
            status_badge = "⚠️ **Verificação incompleta:** nenhum alerta encontrado, mas algumas consultas falharam."
            alerts_text = ""
        else:
            status_badge = (
                "✅ **Todos os repositórios seguros:** Nenhuma vulnerabilidade crítica ou alta detectada."
            )
            alerts_text = ""

        if check_errors:
            alerts_text += "\n" + "\n".join(f"⚠️ Não foi possível verificar: {e}" for e in check_errors)

        return (
            f"* **Status de Vulnerabilidades:** {status_badge}{alerts_text}\n\n"
            f"#### 📦 Repositórios & Último Commit:\n"
            f"{chr(10).join(repo_lines)}"
        )
    except Exception as exc:
        return f"⚠️ Erro ao monitorar segurança dos repositórios: {exc}"
