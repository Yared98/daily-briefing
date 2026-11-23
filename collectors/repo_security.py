import collections
import json
import os
import re
import subprocess
import requests

from collectors import register

MAX_DEPS_PER_PROJECT = 50
MAX_OSV_CALLS_PER_RUN = 60

SEVERITY_ORDER = {
    "UNKNOWN": 0,
    "LOW": 1,
    "MODERATE": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}

_OSV_VULN_CACHE: dict = {}

# nome[extras] <operador> versão — usa a primeira versão citada (pino exato ou limite inferior),
# a mesma aproximação feita para o npm com `^`/`~`.
_PY_REQ_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(===|==|~=|>=)\s*([0-9][^,;\s]*)")


def _clean_version(raw: str) -> str:
    return raw.strip().lstrip("^~>=<! ").split(",")[0].strip()


def _version_key(ver_str: str) -> tuple:
    """Extrai tupla de inteiros a partir dos números da string de versão, ignorando sufixos."""
    base = str(ver_str).split("-")[0].split("+")[0]
    nums = re.findall(r"\d+", base)
    return tuple(int(x) for x in nums)


def _npm_deps(path: str) -> list:
    with open(path, "r", encoding="utf-8") as pf:
        pkg_json = json.load(pf)

    prod_deps = pkg_json.get("dependencies", {})
    if not isinstance(prod_deps, dict):
        prod_deps = {}
    dev_deps = pkg_json.get("devDependencies", {})
    if not isinstance(dev_deps, dict):
        dev_deps = {}

    lock_path = os.path.join(os.path.dirname(path), "package-lock.json")
    lock_packages = None
    lock_dependencies = None
    if os.path.exists(lock_path):
        try:
            with open(lock_path, "r", encoding="utf-8") as lf:
                lock_data = json.load(lf)
            if isinstance(lock_data, dict):
                lock_packages = lock_data.get("packages")
                lock_dependencies = lock_data.get("dependencies")
        except Exception:
            pass

    dep_names = []
    for name in prod_deps:
        if isinstance(name, str) and name not in dep_names:
            dep_names.append(name)
    for name in dev_deps:
        if isinstance(name, str) and name not in dep_names:
            dep_names.append(name)

    deps = []
    for name in dep_names:
        is_dev = (name in dev_deps) and (name not in prod_deps)
        installed_ver = None
        if isinstance(lock_packages, dict):
            pkg_entry = lock_packages.get(f"node_modules/{name}")
            if isinstance(pkg_entry, dict) and "version" in pkg_entry:
                installed_ver = str(pkg_entry["version"]).strip()
        if installed_ver is None and isinstance(lock_dependencies, dict):
            dep_entry = lock_dependencies.get(name)
            if isinstance(dep_entry, dict) and "version" in dep_entry:
                installed_ver = str(dep_entry["version"]).strip()

        if installed_ver is None:
            raw_ver = prod_deps.get(name) or dev_deps.get(name)
            if isinstance(raw_ver, str):
                installed_ver = _clean_version(raw_ver)
            else:
                installed_ver = ""

        deps.append((name, installed_ver, is_dev))
    return deps


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
                deps.append((parsed[0], parsed[1], False))
    return deps


def _pyproject_deps(path: str) -> list:
    import tomllib

    with open(path, "rb") as tf:
        data = tomllib.load(tf)
    deps = []
    for spec in data.get("project", {}).get("dependencies", []):
        parsed = _parse_pep508(spec)
        if parsed:
            deps.append((parsed[0], parsed[1], False))
    poetry = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
    for name, spec in poetry.items():
        if name.lower() == "python":
            continue
        version = spec.get("version", "") if isinstance(spec, dict) else str(spec)
        deps.append((name, _clean_version(version), False))
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
        {
            "package": {"name": item[0], "ecosystem": ecosystem},
            "version": item[1],
            "dev": item[2] if len(item) > 2 else False,
        }
        for item in deps[:MAX_DEPS_PER_PROJECT]
        if item[1] and item[1][0].isdigit()
    ]


@register("repo_security", title="## 🛡️ Radar de Segurança & Repositórios", order=30,
          focus="🛡️ **Segurança & Repositórios** (alertas de vulnerabilidades)")
def collect(cfg: dict, app_cfg: dict) -> str:
    """Monitora branch/commit recente e vulnerabilidades (Dependabot + OSV.dev) dos projetos."""
    projects = app_cfg.get("supported_projects") or []
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
    get_calls_count = 0

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
                        clean_queries = [{"package": q["package"], "version": q["version"]} for q in queries]
                        resp_osv = requests.post(
                            "https://api.osv.dev/v1/querybatch", json={"queries": clean_queries}, timeout=8
                        ).json()
                        pkg_vulns = collections.defaultdict(list)
                        pkg_meta = {}
                        for idx_q, r_osv in enumerate(resp_osv.get("results", [])):
                            if idx_q < len(queries):
                                q = queries[idx_q]
                                dep_name = q["package"]["name"]
                                pkg_meta[dep_name] = q
                                for v in r_osv.get("vulns", []):
                                    vid = v.get("id")
                                    if vid and vid not in pkg_vulns[dep_name]:
                                        pkg_vulns[dep_name].append(vid)

                        unique_ids = []
                        for v_ids in pkg_vulns.values():
                            for vid in v_ids:
                                if vid not in unique_ids:
                                    unique_ids.append(vid)

                        for vid in unique_ids:
                            if vid not in _OSV_VULN_CACHE:
                                if get_calls_count < MAX_OSV_CALLS_PER_RUN:
                                    try:
                                        r = requests.get(f"https://api.osv.dev/v1/vulns/{vid}", timeout=8)
                                        get_calls_count += 1
                                        if r.status_code == 200:
                                            _OSV_VULN_CACHE[vid] = r.json()
                                        else:
                                            _OSV_VULN_CACHE[vid] = None
                                    except Exception:
                                        get_calls_count += 1
                                        _OSV_VULN_CACHE[vid] = None
                                else:
                                    _OSV_VULN_CACHE[vid] = None

                        for dep_n, v_ids in pkg_vulns.items():
                            meta = pkg_meta.get(dep_n, {})
                            installed_ver = meta.get("version", "")
                            is_dev = meta.get("dev", False)
                            ecosystem = meta.get("package", {}).get("ecosystem", "")

                            vuln_sevs = []
                            vuln_fixes = []
                            all_have_fix = True

                            for vid in v_ids:
                                v_detail = _OSV_VULN_CACHE.get(vid)
                                sev = "UNKNOWN"
                                if isinstance(v_detail, dict):
                                    db_spec = v_detail.get("database_specific")
                                    if isinstance(db_spec, dict):
                                        raw_sev = str(db_spec.get("severity") or "").strip().upper()
                                        if raw_sev in SEVERITY_ORDER:
                                            sev = raw_sev
                                vuln_sevs.append(sev)

                                best_fixed_for_vuln = None
                                if isinstance(v_detail, dict):
                                    matching_fixed = []
                                    for aff in v_detail.get("affected", []):
                                        if isinstance(aff, dict):
                                            aff_pkg = aff.get("package", {})
                                            if isinstance(aff_pkg, dict):
                                                if (aff_pkg.get("name", "").lower() == dep_n.lower() and
                                                    aff_pkg.get("ecosystem", "").lower() == ecosystem.lower()):
                                                    for r in aff.get("ranges", []):
                                                        if isinstance(r, dict):
                                                            for ev in r.get("events", []):
                                                                if isinstance(ev, dict) and "fixed" in ev:
                                                                    f_val = str(ev["fixed"]).strip()
                                                                    if f_val:
                                                                        matching_fixed.append(f_val)
                                    inst_key = _version_key(installed_ver)
                                    candidates = [f for f in matching_fixed if _version_key(f) > inst_key]
                                    if candidates:
                                        best_fixed_for_vuln = min(candidates, key=_version_key)

                                if best_fixed_for_vuln is not None:
                                    vuln_fixes.append(best_fixed_for_vuln)
                                else:
                                    all_have_fix = False

                            max_sev = max(vuln_sevs, key=lambda s: SEVERITY_ORDER.get(s, 0)) if vuln_sevs else "UNKNOWN"

                            if all_have_fix and vuln_fixes:
                                fix_ver = max(vuln_fixes, key=_version_key)
                                fix_str = f"corrigido em {fix_ver}"
                            else:
                                fix_str = "sem correção publicada"

                            is_high_or_crit = max_sev in ("HIGH", "CRITICAL")
                            emoji = "🚨" if (is_high_or_crit and not is_dev) else "⚠️"
                            dev_suffix = " (dev)" if is_dev else ""
                            cves_str = ", ".join(v_ids[:3]) + (f" (+{len(v_ids)-3})" if len(v_ids) > 3 else "")

                            vuln_alerts.append(
                                f"{emoji} **[{p_name}]** `{dep_n}` {installed_ver}{dev_suffix}: "
                                f"{len(v_ids)} vulnerabilidade(s), gravidade máxima {max_sev}; {fix_str} ({cves_str})"
                            )
                except Exception as exc:
                    check_errors.append(f"{p_name} (OSV.dev: {exc.__class__.__name__})")

        if vuln_alerts:
            has_urgent = any(al.startswith("🚨") for al in vuln_alerts)
            if has_urgent:
                status_badge = f"🚨 **Atenção:** {len(vuln_alerts)} alerta(s) de vulnerabilidade identificado(s):"
            else:
                status_badge = (
                    f"⚠️ **Vulnerabilidades de menor risco:** {len(vuln_alerts)} "
                    f"pacote(s) com alertas (baixa/média gravidade ou só de desenvolvimento)."
                )
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
